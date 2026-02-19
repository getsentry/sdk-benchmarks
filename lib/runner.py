"""Benchmark runner — orchestrates container builds and benchmark execution."""

from __future__ import annotations

import json
import logging
import math
import os
import subprocess
import threading
from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader
from scipy import stats

logger = logging.getLogger(__name__)

PROJECT_ROOT = Path(__file__).resolve().parent.parent


def load_config(app: str) -> dict:
    """Load benchmark config for an app like 'python/django'."""
    config_name = app.replace("/", "-") + ".yaml"
    config_path = PROJECT_ROOT / "configs" / config_name
    with open(config_path) as f:
        return yaml.safe_load(f)


def render_compose(config: dict, variant: str, results_dir: str) -> str:
    """Render docker-compose.yml from Jinja2 template. Returns the YAML string."""
    env = Environment(
        loader=FileSystemLoader(str(PROJECT_ROOT / "templates")),
        keep_trailing_newline=True,
    )
    template = env.get_template("docker-compose.yml.j2")
    return template.render(
        language=config["language"],
        framework=config["framework"],
        variant=variant,
        config=config,
        project_root=str(PROJECT_ROOT),
        results_dir=results_dir,
    )


def _docker_compose(
    *args: str, compose_file: str, project_name: str
) -> subprocess.CompletedProcess:
    """Run a docker compose command."""
    cmd = [
        "docker",
        "compose",
        "-f",
        compose_file,
        "-p",
        project_name,
        *args,
    ]
    logger.debug("Running: %s", " ".join(cmd))
    return subprocess.run(cmd, capture_output=True, text=True, check=True)


def _poll_docker_stats(
    container_name: str,
    samples: list[dict],
    stop_event: threading.Event,
    interval: float = 1.0,
) -> None:
    """Poll docker stats for a container in a background thread."""
    while not stop_event.is_set():
        try:
            result = subprocess.run(
                [
                    "docker",
                    "stats",
                    "--no-stream",
                    "--format",
                    '{"cpu":{{.CPUPerc}},"mem":"{{.MemUsage}}","mem_pct":{{.MemPerc}}}',
                    container_name,
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode == 0 and result.stdout.strip():
                raw = result.stdout.strip()
                # docker stats formats CPU as "12.34%" — strip the %
                raw = raw.replace("%", "")
                sample = json.loads(raw)
                samples.append(sample)
        except (subprocess.TimeoutExpired, json.JSONDecodeError, subprocess.SubprocessError):
            pass
        stop_event.wait(interval)


def _parse_mem_usage(mem_str: str) -> float:
    """Parse docker stats mem usage like '45.2MiB / 512MiB' into MB."""
    used = mem_str.split("/")[0].strip()
    if used.endswith("GiB"):
        return float(used[:-3]) * 1024
    if used.endswith("MiB"):
        return float(used[:-3])
    if used.endswith("KiB"):
        return float(used[:-3]) / 1024
    return 0.0


def run_variant(
    config: dict,
    variant: str,
    iteration: int,
    results_base: str,
) -> dict:
    """Run a single benchmark iteration for a variant (baseline or instrumented).

    Returns a dict with iteration results including vegeta metrics and docker stats.
    """
    results_dir = os.path.abspath(os.path.join(results_base, variant, f"iter-{iteration}"))
    os.makedirs(results_dir, exist_ok=True)

    compose_yaml = render_compose(config, variant, results_dir)
    project_name = f"bench-{variant}-{iteration}"

    # Write compose file to a temp location
    compose_file = os.path.join(results_dir, "docker-compose.yml")
    with open(compose_file, "w") as f:
        f.write(compose_yaml)

    try:
        # Build images first
        logger.info("[%s iter=%d] Building images...", variant, iteration)
        _docker_compose("build", compose_file=compose_file, project_name=project_name)

        # Start services in detached mode
        logger.info("[%s iter=%d] Starting services...", variant, iteration)
        _docker_compose("up", "-d", compose_file=compose_file, project_name=project_name)

        # Start polling docker stats for the app container
        app_container = f"{project_name}-app-1"
        stats_samples: list[dict] = []
        stop_event = threading.Event()
        stats_thread = threading.Thread(
            target=_poll_docker_stats,
            args=(app_container, stats_samples, stop_event),
            daemon=True,
        )
        stats_thread.start()

        # Wait for loadgen to finish (it exits when done)
        logger.info("[%s iter=%d] Waiting for load generator to finish...", variant, iteration)
        _docker_compose("wait", "loadgen", compose_file=compose_file, project_name=project_name)

        # Read vegeta results
        vegeta_results_path = os.path.join(results_dir, "results.json")
        vegeta_report_path = os.path.join(results_dir, "report.txt")

        vegeta_results = None
        if os.path.exists(vegeta_results_path):
            with open(vegeta_results_path) as f:
                # vegeta encode --to json outputs one JSON object per line (NDJSON)
                vegeta_results = [json.loads(line) for line in f if line.strip()]

        vegeta_report = None
        if os.path.exists(vegeta_report_path):
            with open(vegeta_report_path) as f:
                vegeta_report = f.read()

        return {
            "variant": variant,
            "iteration": iteration,
            "vegeta_results": vegeta_results,
            "vegeta_report": vegeta_report,
            "docker_stats": stats_samples,
        }

    finally:
        # Stop stats collection
        stop_event.set()
        stats_thread.join(timeout=5)

        # Always clean up containers
        logger.info("[%s iter=%d] Cleaning up...", variant, iteration)
        try:
            _docker_compose(
                "down",
                "-v",
                "--remove-orphans",
                compose_file=compose_file,
                project_name=project_name,
            )
        except subprocess.CalledProcessError as e:
            logger.warning("Cleanup failed: %s", e.stderr)


def run_single_iteration(
    app: str,
    sdk_version: str,
    iteration: int,
    output_dir: str = "results/",
    latest_sdk_version: str | None = None,
) -> dict:
    """Run a single benchmark iteration (all variants) without adaptive loop.

    Runs baseline, latest_release (optional), and current_branch for a single
    iteration number. Writes iteration-{N}.json with the raw per-variant results.

    Args:
        app: App to benchmark (e.g. 'go/net-http').
        sdk_version: SDK version for the current branch.
        iteration: Iteration number to run.
        output_dir: Directory to write results to.
        latest_sdk_version: If provided, also benchmark the latest stable release.

    Returns a dict with the iteration results for all variants.
    """
    config = load_config(app)
    has_latest_release = latest_sdk_version is not None

    results_base = os.path.join(output_dir, f"{config['language']}-{config['framework']}")
    os.makedirs(results_base, exist_ok=True)

    variants_in_round = ["baseline"]
    if has_latest_release:
        variants_in_round.append("latest_release")
    variants_in_round.append("current_branch")

    logger.info("=== Running iteration %d (%s) ===", iteration, ", ".join(variants_in_round))

    iteration_results = []

    # Baseline — no SDK
    logger.info("--- baseline iteration %d ---", iteration)
    result = run_variant(config, "baseline", iteration, results_base)
    iteration_results.append(result)

    # Latest release — instrumented with stable SDK
    if has_latest_release:
        logger.info("--- latest_release iteration %d ---", iteration)
        _prepare_sdk_version(config, latest_sdk_version)
        result = run_variant(config, "latest_release", iteration, results_base)
        iteration_results.append(result)

    # Current branch — instrumented with PR's SDK
    logger.info("--- current_branch iteration %d ---", iteration)
    _prepare_sdk_version(config, sdk_version)
    result = run_variant(config, "current_branch", iteration, results_base)
    iteration_results.append(result)

    output = {
        "app": app,
        "sdk_version": sdk_version,
        "latest_sdk_version": latest_sdk_version,
        "iteration": iteration,
        "results": iteration_results,
    }

    output_path = os.path.join(results_base, f"iteration-{iteration}.json")
    with open(output_path, "w") as f:
        json.dump(output, f, indent=2, default=str)

    logger.info("Iteration results written to %s", output_path)
    return output


def run_benchmark(
    app: str,
    sdk_version: str,
    iterations: int = 10,
    output_dir: str = "results/",
    latest_sdk_version: str | None = None,
) -> dict:
    """Run a full benchmark with adaptive iteration.

    Runs baseline, latest_release (optional), and current_branch iterations until
    the results converge (95% CI half-width for p95 overhead < 2 percentage points)
    or the maximum number of iterations is reached.

    Args:
        app: App to benchmark (e.g. 'python/django').
        sdk_version: SDK version for the current branch.
        iterations: Maximum number of iterations.
        output_dir: Directory to write results to.
        latest_sdk_version: If provided, also benchmark the latest stable release
            for 3-way comparison (baseline vs latest_release vs current_branch).

    Returns the full results dict and writes it to output_dir.
    """
    config = load_config(app)
    has_latest_release = latest_sdk_version is not None

    results_base = os.path.join(output_dir, f"{config['language']}-{config['framework']}")
    os.makedirs(results_base, exist_ok=True)

    all_results = {
        "app": app,
        "sdk_version": sdk_version,
        "latest_sdk_version": latest_sdk_version,
        "config": config,
        "iterations": [],
    }

    min_iterations = 3
    for i in range(1, iterations + 1):
        variants_in_round = ["baseline"]
        if has_latest_release:
            variants_in_round.append("latest_release")
        variants_in_round.append("current_branch")

        logger.info("=== Running iteration %d/%d (%s) ===", i, iterations, ", ".join(variants_in_round))

        # Baseline — no SDK
        logger.info("--- baseline iteration %d ---", i)
        result = run_variant(config, "baseline", i, results_base)
        all_results["iterations"].append(result)

        # Latest release — instrumented with stable SDK
        if has_latest_release:
            logger.info("--- latest_release iteration %d ---", i)
            _prepare_sdk_version(config, latest_sdk_version)
            result = run_variant(config, "latest_release", i, results_base)
            all_results["iterations"].append(result)

        # Current branch — instrumented with PR's SDK
        logger.info("--- current_branch iteration %d ---", i)
        _prepare_sdk_version(config, sdk_version)
        result = run_variant(config, "current_branch", i, results_base)
        all_results["iterations"].append(result)

        if i >= min_iterations:
            summary = _compute_summary(all_results["iterations"], has_latest_release)
            if summary["converged"]:
                logger.info("Converged after %d iterations", i)
                break
    else:
        summary = _compute_summary(all_results["iterations"], has_latest_release)

    all_results["summary"] = summary
    all_results["load"] = {
        "rps": config.get("load", {}).get("rps"),
        "duration": config.get("load", {}).get("duration"),
    }

    results_path = os.path.join(results_base, "results.json")
    with open(results_path, "w") as f:
        json.dump(all_results, f, indent=2, default=str)

    logger.info("Results written to %s", results_path)
    return all_results


def _percentile(sorted_values: list[float], p: float) -> float:
    """Compute the p-th percentile from a sorted list of values."""
    if not sorted_values:
        return 0.0
    k = (len(sorted_values) - 1) * (p / 100.0)
    f = math.floor(k)
    c = math.ceil(k)
    if f == c:
        return sorted_values[int(k)]
    return sorted_values[f] * (c - k) + sorted_values[c] * (k - f)


def _extract_per_iteration_latencies(
    iterations: list[dict], variant: str
) -> dict[int, list[float]]:
    """Extract latencies grouped by iteration number for a given variant.

    Returns {iteration_number: [latency_ns, ...], ...}.
    """
    by_iter: dict[int, list[float]] = {}
    for it in iterations:
        if it.get("variant") != variant:
            continue
        iter_num = it["iteration"]
        latencies = [req["latency"] for req in (it.get("vegeta_results") or [])]
        if latencies:
            by_iter[iter_num] = latencies
    return by_iter


# Convergence threshold: 95% CI half-width for p95 overhead must be below this
# (in absolute percentage points).
_CONVERGENCE_THRESHOLD = 2.0

# Minimum effect size (percentage points) for flagging a regression.
_REGRESSION_THRESHOLD = 2.0


def _compute_pairwise_overhead(
    iterations: list[dict], base_variant: str, test_variant: str
) -> dict:
    """Compute overhead of test_variant vs base_variant using per-iteration comparison.

    For each metric (p50, p99, mean), computes per-iteration overhead percentages,
    then uses a t-distribution CI and one-sample t-test to assess significance.

    Returns a dict with overhead, confidence_intervals, p_values, converged, and
    iterations_used.
    """
    base_by_iter = _extract_per_iteration_latencies(iterations, base_variant)
    test_by_iter = _extract_per_iteration_latencies(iterations, test_variant)

    # Find paired iterations (both variants exist)
    paired_iters = sorted(set(base_by_iter) & set(test_by_iter))

    if not paired_iters:
        return {
            "overhead": {},
            "confidence_intervals": {},
            "p_values": {},
            "converged": False,
            "iterations_used": 0,
        }

    metrics = [("p95", 95), ("p99", 99)]
    overhead = {}
    confidence_intervals = {}
    p_values = {}

    for name, p in metrics:
        per_iter_overhead = []
        for i in paired_iters:
            base_lats = sorted(base_by_iter[i])
            test_lats = sorted(test_by_iter[i])

            base_val = _percentile(base_lats, p)
            test_val = _percentile(test_lats, p)

            if base_val > 0:
                per_iter_overhead.append((test_val - base_val) / base_val * 100.0)

        if not per_iter_overhead:
            continue

        mean_overhead = sum(per_iter_overhead) / len(per_iter_overhead)
        overhead[name] = round(mean_overhead, 2)

        # Need at least 2 samples for CI and t-test
        if len(per_iter_overhead) < 2:
            continue

        # t-based 95% confidence interval
        n = len(per_iter_overhead)
        sem = stats.sem(per_iter_overhead)
        t_crit = stats.t.ppf(0.975, df=n - 1)
        ci_lower = mean_overhead - t_crit * sem
        ci_upper = mean_overhead + t_crit * sem
        confidence_intervals[name] = {
            "lower": round(ci_lower, 2),
            "upper": round(ci_upper, 2),
        }

        # One-sample t-test: H0 = mean overhead is 0
        t_stat, p_val = stats.ttest_1samp(per_iter_overhead, 0.0)
        p_values[name] = round(p_val, 4)

    # Convergence: check if p95 CI half-width is narrow enough
    converged = False
    p95_ci = confidence_intervals.get("p95")
    if p95_ci:
        half_width = (p95_ci["upper"] - p95_ci["lower"]) / 2
        converged = bool(half_width < _CONVERGENCE_THRESHOLD)

    return {
        "overhead": overhead,
        "confidence_intervals": confidence_intervals,
        "p_values": p_values,
        "converged": converged,
        "iterations_used": len(paired_iters),
    }


def _compute_summary(
    iterations: list[dict], has_latest_release: bool = False
) -> dict:
    """Compute overhead summary comparing variants against the baseline.

    When has_latest_release is True, computes overhead for both latest_release
    and current_branch vs baseline, plus regression detection based on whether
    current_branch is worse than latest_release.

    When False, computes overhead for current_branch vs baseline only.
    """
    variants = ["current_branch"]
    if has_latest_release:
        variants = ["latest_release", "current_branch"]

    comparisons = {}
    for variant in variants:
        comparisons[variant] = _compute_pairwise_overhead(
            iterations, "baseline", variant
        )

    # Use current_branch comparison for convergence
    cb = comparisons["current_branch"]
    converged = cb["converged"]
    iterations_used = cb["iterations_used"]

    # Regression detection
    regression = False
    if converged or iterations_used >= 3:
        if has_latest_release:
            # Compare current_branch directly against latest_release.
            # This detects whether the current branch is slower than the latest
            # release, eliminating noise from baseline comparisons.
            direct = _compute_pairwise_overhead(
                iterations, "latest_release", "current_branch"
            )
            comparisons["cb_vs_latest"] = direct
            d_p95_p = direct["p_values"].get("p95", 1.0)
            d_p95_ci = direct["confidence_intervals"].get("p95")
            if (
                d_p95_ci
                and d_p95_p < 0.05
                and d_p95_ci["lower"] > _REGRESSION_THRESHOLD
            ):
                regression = True
        else:
            cb_p95_p = cb["p_values"].get("p95", 1.0)
            cb_p95_ci = cb["confidence_intervals"].get("p95")
            if (
                cb_p95_ci
                and cb_p95_p < 0.05
                and cb_p95_ci["lower"] > _REGRESSION_THRESHOLD
            ):
                regression = True

    return {
        "comparisons": comparisons,
        "regression": regression,
        "converged": converged,
        "iterations_used": iterations_used,
    }


def _prepare_sdk_version(config: dict, sdk_version: str) -> None:
    """Template the SDK version into requirements files."""
    app_dir = PROJECT_ROOT / config["app_dir"]
    language = config.get("language", "")

    if language == "go":
        _prepare_go_sdk_version(app_dir, sdk_version)
        return

    # Python: render requirements-sentry.txt from template
    tmpl_path = app_dir / "requirements-sentry.txt.tmpl"
    if tmpl_path.exists():
        with open(tmpl_path) as f:
            template_content = f.read()
        rendered = template_content.replace("{{ sdk_version }}", sdk_version)
        output_path = app_dir / "requirements-sentry.txt"
        with open(output_path, "w") as f:
            f.write(rendered)
        logger.info("Rendered %s with sdk_version=%s", output_path, sdk_version)


def _prepare_go_sdk_version(app_dir: Path, sdk_version: str) -> None:
    """Update sentry-go module versions in a Go app's go.mod."""
    go_mod = app_dir / "go.mod"
    if not go_mod.exists():
        return

    # Find all sentry-go modules referenced in go.mod
    with open(go_mod) as f:
        content = f.read()

    sentry_modules = []
    for line in content.splitlines():
        line = line.strip()
        if "github.com/getsentry/sentry-go" in line and not line.startswith("module"):
            parts = line.split()
            for part in parts:
                if part.startswith("github.com/getsentry/sentry-go"):
                    sentry_modules.append(part)
                    break

    if not sentry_modules:
        logger.warning("No sentry-go modules found in %s", go_mod)
        return

    # Use go get to update each sentry-go module to the target version
    version_spec = f"@v{sdk_version}" if sdk_version != "latest" and not sdk_version.startswith("v") else f"@{sdk_version}"
    get_args = [f"{mod}{version_spec}" for mod in sentry_modules]

    logger.info("Updating sentry-go modules in %s: %s", app_dir, get_args)
    subprocess.run(
        ["go", "get"] + get_args,
        cwd=str(app_dir),
        check=True,
    )
    subprocess.run(
        ["go", "mod", "tidy"],
        cwd=str(app_dir),
        check=True,
    )
    logger.info("Updated go.mod in %s to sentry-go %s", app_dir, sdk_version)
