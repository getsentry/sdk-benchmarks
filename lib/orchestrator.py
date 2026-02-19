"""Orchestrator — dispatches parallel benchmark iterations via GitHub Actions."""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time

logger = logging.getLogger(__name__)

REPO = "getsentry/sdk-benchmarks"
WORKFLOW_FILE = "iteration.yml"

# How often to poll for run creation / completion
_POLL_FIND_INTERVAL = 5  # seconds
_POLL_FIND_TIMEOUT = 120  # seconds
_POLL_STATUS_INTERVAL = 30  # seconds

# Minimum iterations needed for valid statistics
_MIN_ITERATIONS = 3


def _gh_api(
    endpoint: str, method: str = "GET", token: str | None = None, input_data: dict | None = None
) -> dict | list | None:
    """Call the GitHub API via the gh CLI."""
    cmd = ["gh", "api", endpoint, "--method", method]
    if input_data:
        cmd += ["--input", "-"]

    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token

    result = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        input=json.dumps(input_data) if input_data else None,
        env=env,
    )

    if result.returncode != 0:
        # 204 No Content is expected for dispatch
        if "HTTP 204" in result.stderr or result.stdout.strip() == "":
            return None
        raise RuntimeError(f"gh api {endpoint} failed: {result.stderr}")

    if not result.stdout.strip():
        return None
    return json.loads(result.stdout)


def dispatch_iteration(
    app: str,
    sdk_version: str,
    latest_sdk_version: str | None,
    iteration: int,
    run_key: str,
    benchmarks_ref: str,
    token: str,
) -> None:
    """Dispatch a single iteration workflow run."""
    inputs = {
        "app": app,
        "sdk-version": sdk_version,
        "iteration": str(iteration),
        "run-key": run_key,
        "benchmarks-ref": benchmarks_ref,
    }
    if latest_sdk_version:
        inputs["latest-sdk-version"] = latest_sdk_version

    endpoint = f"/repos/{REPO}/actions/workflows/{WORKFLOW_FILE}/dispatches"
    _gh_api(
        endpoint,
        method="POST",
        token=token,
        input_data={"ref": benchmarks_ref, "inputs": inputs},
    )
    logger.info("Dispatched iteration %d with run-key=%s", iteration, run_key)


def find_run_id(run_key: str, token: str) -> int | None:
    """Poll for a workflow run matching the given run-key in its name.

    Returns the run ID or None if not found within the timeout.
    """
    target_name = f"bench-iteration {run_key}"
    deadline = time.time() + _POLL_FIND_TIMEOUT

    while time.time() < deadline:
        endpoint = f"/repos/{REPO}/actions/runs?event=workflow_dispatch&per_page=20"
        data = _gh_api(endpoint, token=token)
        if data and "workflow_runs" in data:
            for run in data["workflow_runs"]:
                if run.get("name") == target_name:
                    logger.info("Found run %d for key=%s", run["id"], run_key)
                    return run["id"]
        time.sleep(_POLL_FIND_INTERVAL)

    logger.warning("Timed out finding run for key=%s", run_key)
    return None


def wait_for_runs(
    run_ids: dict[str, int], token: str, timeout: int
) -> dict[str, str]:
    """Wait for multiple workflow runs to complete.

    Args:
        run_ids: Mapping of run-key to run ID.
        token: GitHub token.
        timeout: Overall timeout in seconds.

    Returns a mapping of run-key to conclusion ('success', 'failure', 'timed_out').
    """
    deadline = time.time() + timeout
    conclusions: dict[str, str] = {}
    pending = dict(run_ids)

    while pending and time.time() < deadline:
        for run_key, run_id in list(pending.items()):
            endpoint = f"/repos/{REPO}/actions/runs/{run_id}"
            data = _gh_api(endpoint, token=token)
            if data and data.get("status") == "completed":
                conclusion = data.get("conclusion", "unknown")
                conclusions[run_key] = conclusion
                del pending[run_key]
                logger.info(
                    "Run %d (key=%s) completed: %s", run_id, run_key, conclusion
                )

        if pending:
            time.sleep(_POLL_STATUS_INTERVAL)

    # Mark remaining as timed_out
    for run_key in pending:
        conclusions[run_key] = "timed_out"
        logger.warning("Run key=%s timed out", run_key)

    return conclusions


def download_artifact(run_key: str, output_dir: str, token: str) -> str | None:
    """Download the iteration artifact for a given run-key.

    Returns the path to the downloaded directory, or None on failure.
    """
    artifact_name = f"iteration-{run_key}"
    dest = os.path.join(output_dir, artifact_name)
    os.makedirs(dest, exist_ok=True)

    env = os.environ.copy()
    if token:
        env["GH_TOKEN"] = token

    result = subprocess.run(
        [
            "gh", "run", "download",
            "--repo", REPO,
            "--name", artifact_name,
            "--dir", dest,
        ],
        capture_output=True,
        text=True,
        env=env,
    )

    if result.returncode != 0:
        logger.warning(
            "Failed to download artifact %s: %s", artifact_name, result.stderr
        )
        return None

    logger.info("Downloaded artifact %s to %s", artifact_name, dest)
    return dest


def collect_iteration_results(
    artifact_dirs: list[str],
) -> list[dict]:
    """Load iteration results from downloaded artifact directories.

    Each directory should contain an iteration-{N}.json file with variant results.
    Returns the collected iteration result dicts.
    """
    all_iteration_data = []
    for artifact_dir in artifact_dirs:
        for dirpath, _dirnames, filenames in os.walk(artifact_dir):
            for filename in filenames:
                if filename.startswith("iteration-") and filename.endswith(".json"):
                    filepath = os.path.join(dirpath, filename)
                    with open(filepath) as f:
                        data = json.load(f)
                    all_iteration_data.append(data)
    return all_iteration_data


def orchestrate(
    app: str,
    sdk_version: str,
    latest_sdk_version: str | None,
    iterations: int,
    timeout: int,
    output_dir: str,
    benchmarks_ref: str,
    token: str,
    caller_run_id: str,
) -> dict:
    """Orchestrate parallel benchmark iterations.

    Dispatches N iteration workflows, polls for completion, downloads artifacts,
    and computes summary statistics.

    Returns the full results dict (same format as run_benchmark).
    """
    from lib.runner import _compute_summary, load_config

    config = load_config(app)
    has_latest_release = latest_sdk_version is not None

    # 1. Dispatch all iterations
    run_keys = []
    for i in range(1, iterations + 1):
        run_key = f"{app.replace('/', '-')}-iter{i}-{caller_run_id}"
        dispatch_iteration(
            app=app,
            sdk_version=sdk_version,
            latest_sdk_version=latest_sdk_version,
            iteration=i,
            run_key=run_key,
            benchmarks_ref=benchmarks_ref,
            token=token,
        )
        run_keys.append(run_key)

    # 2. Find run IDs for all dispatched iterations
    logger.info("Finding run IDs for %d dispatched iterations...", len(run_keys))
    run_ids: dict[str, int] = {}
    for run_key in run_keys:
        run_id = find_run_id(run_key, token)
        if run_id:
            run_ids[run_key] = run_id
        else:
            logger.warning("Could not find run for key=%s, skipping", run_key)

    if not run_ids:
        raise RuntimeError("Failed to find any dispatched workflow runs")

    # 3. Wait for all runs to complete
    logger.info("Waiting for %d runs to complete (timeout=%ds)...", len(run_ids), timeout)
    conclusions = wait_for_runs(run_ids, token, timeout)

    # 4. Download artifacts from successful runs
    successful_keys = [k for k, v in conclusions.items() if v == "success"]
    failed_keys = [k for k, v in conclusions.items() if v != "success"]

    if failed_keys:
        logger.warning(
            "%d iterations failed/timed out: %s",
            len(failed_keys),
            {k: conclusions[k] for k in failed_keys},
        )

    if len(successful_keys) < _MIN_ITERATIONS:
        raise RuntimeError(
            f"Only {len(successful_keys)} iterations succeeded "
            f"(minimum {_MIN_ITERATIONS} required). "
            f"Failures: {failed_keys}"
        )

    artifact_dirs = []
    for run_key in successful_keys:
        artifact_dir = download_artifact(run_key, output_dir, token)
        if artifact_dir:
            artifact_dirs.append(artifact_dir)

    # 5. Collect and summarize results
    iteration_data = collect_iteration_results(artifact_dirs)

    # Flatten variant results from all iterations into the format _compute_summary expects
    all_iterations = []
    for iter_data in iteration_data:
        all_iterations.extend(iter_data.get("results", []))

    summary = _compute_summary(all_iterations, has_latest_release)

    results = {
        "app": app,
        "sdk_version": sdk_version,
        "latest_sdk_version": latest_sdk_version,
        "config": config,
        "iterations": all_iterations,
        "summary": summary,
        "load": {
            "rps": config.get("load", {}).get("rps"),
            "duration": config.get("load", {}).get("duration"),
        },
        "orchestration": {
            "total_dispatched": len(run_keys),
            "successful": len(successful_keys),
            "failed": len(failed_keys),
            "conclusions": conclusions,
        },
    }

    results_base = os.path.join(output_dir, f"{config['language']}-{config['framework']}")
    os.makedirs(results_base, exist_ok=True)
    results_path = os.path.join(results_base, "results.json")
    with open(results_path, "w") as f:
        json.dump(results, f, indent=2, default=str)

    logger.info("Results written to %s", results_path)
    return results
