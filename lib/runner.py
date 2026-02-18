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


def run_benchmark(
    app: str,
    sdk_version: str,
    iterations: int = 10,
    output_dir: str = "results/",
) -> dict:
    """Run a full benchmark with adaptive iteration.

    Runs paired baseline/instrumented iterations until the results converge
    (95% CI half-width for p50 overhead < 2 percentage points) or the maximum
    number of iterations is reached.

    Returns the full results dict and writes it to output_dir.
    """
    config = load_config(app)
    _prepare_sdk_version(config, sdk_version)

    results_base = os.path.join(output_dir, f"{config['language']}-{config['framework']}")
    os.makedirs(results_base, exist_ok=True)

    all_results = {
        "app": app,
        "sdk_version": sdk_version,
        "config": config,
        "iterations": [],
    }

    min_iterations = 3
    for i in range(1, iterations + 1):
        logger.info("=== Running paired iteration %d/%d ===", i, iterations)

        for variant in ("baseline", "instrumented"):
            logger.info("--- %s iteration %d ---", variant, i)
            result = run_variant(config, variant, i, results_base)
            all_results["iterations"].append(result)

        if i >= min_iterations:
            summary = _compute_summary(all_results["iterations"])
            if summary["converged"]:
                logger.info("Converged after %d iterations", i)
                break
    else:
        summary = _compute_summary(all_results["iterations"])

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


def _extract_latencies(iterations: list[dict], variant: str) -> list[float]:
    """Extract all latency values (in nanoseconds) for a given variant."""
    latencies = []
    for it in iterations:
        if it.get("variant") != variant:
            continue
        for req in it.get("vegeta_results") or []:
            latencies.append(req["latency"])
    return latencies


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


# Convergence threshold: 95% CI half-width for p50 overhead must be below this
# (in absolute percentage points).
_CONVERGENCE_THRESHOLD = 2.0

# Minimum effect size (percentage points) for flagging a regression.
_REGRESSION_THRESHOLD = 2.0


def _compute_summary(iterations: list[dict]) -> dict:
    """Compute overhead summary using per-iteration statistical comparison.

    For each metric (p50, p99, mean), computes per-iteration overhead percentages,
    then uses a t-distribution CI and one-sample t-test to assess significance.
    """
    baseline_by_iter = _extract_per_iteration_latencies(iterations, "baseline")
    instrumented_by_iter = _extract_per_iteration_latencies(iterations, "instrumented")

    # Find paired iterations (both baseline and instrumented exist)
    paired_iters = sorted(set(baseline_by_iter) & set(instrumented_by_iter))

    if not paired_iters:
        logger.warning("No paired iterations found for summary computation")
        return {
            "overhead": {},
            "confidence_intervals": {},
            "p_values": {},
            "regression": False,
            "converged": False,
            "iterations_used": 0,
        }

    metrics = [("p50", 50), ("p99", 99), ("mean", None)]
    overhead = {}
    confidence_intervals = {}
    p_values = {}

    for name, p in metrics:
        per_iter_overhead = []
        for i in paired_iters:
            base_lats = sorted(baseline_by_iter[i])
            inst_lats = sorted(instrumented_by_iter[i])

            if name == "mean":
                base_val = sum(base_lats) / len(base_lats)
                inst_val = sum(inst_lats) / len(inst_lats)
            else:
                base_val = _percentile(base_lats, p)
                inst_val = _percentile(inst_lats, p)

            if base_val > 0:
                per_iter_overhead.append((inst_val - base_val) / base_val * 100.0)

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

    # Convergence: check if p50 CI half-width is narrow enough
    converged = False
    p50_ci = confidence_intervals.get("p50")
    if p50_ci:
        half_width = (p50_ci["upper"] - p50_ci["lower"]) / 2
        converged = bool(half_width < _CONVERGENCE_THRESHOLD)

    # Regression: significant positive overhead above threshold
    regression = False
    if converged or len(paired_iters) >= 3:
        p50_p = p_values.get("p50", 1.0)
        p50_ci = confidence_intervals.get("p50")
        if p50_ci and p50_p < 0.05 and p50_ci["lower"] > _REGRESSION_THRESHOLD:
            regression = True

    return {
        "overhead": overhead,
        "confidence_intervals": confidence_intervals,
        "p_values": p_values,
        "regression": regression,
        "converged": converged,
        "iterations_used": len(paired_iters),
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
        # Match lines like: github.com/getsentry/sentry-go v0.42.0
        # or: github.com/getsentry/sentry-go/gin v0.42.0
        if "github.com/getsentry/sentry-go" in line and not line.startswith("module"):
            parts = line.split()
            if parts:
                mod = parts[0]
                if mod.startswith("github.com/getsentry/sentry-go"):
                    sentry_modules.append(mod)

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
