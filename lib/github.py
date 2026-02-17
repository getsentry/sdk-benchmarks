"""GitHub integration — posting results as PR comments and managing artifacts."""

import json
import subprocess


COMMENT_MARKER = "<!-- sdk-benchmark-results -->"


def format_comment(results: dict) -> str:
    """Format benchmark results as a Markdown PR comment."""
    summary = results.get("summary", {})
    app = results.get("app", "unknown")
    sdk_version = results.get("sdk_version", "unknown")
    overhead = summary.get("overhead", {})
    regression = summary.get("regression", False)

    status = "**Regression detected**" if regression else "No regression"

    lines = [
        COMMENT_MARKER,
        f"## SDK Benchmark Results — `{app}`",
        "",
        f"SDK version: `{sdk_version}`",
        f"Status: {status}",
        "",
        "### Latency Overhead",
        "",
        "| Metric | Overhead |",
        "|--------|----------|",
    ]

    for metric in ["p50", "p90", "p95", "p99", "mean"]:
        value = overhead.get(metric)
        if value is not None:
            lines.append(f"| {metric} | {value:+.2f}% |")

    endpoints = results.get("endpoints", {})
    if endpoints:
        lines.extend(["", "### Per-Endpoint Breakdown", ""])
        lines.append("| Endpoint | p50 Overhead | p99 Overhead | CPU Overhead | Mem Overhead |")
        lines.append("|----------|-------------|-------------|-------------|-------------|")
        for name, data in endpoints.items():
            ep_overhead = data.get("overhead", {})
            lines.append(
                f"| {name} "
                f"| {ep_overhead.get('p50', 'N/A'):+.2f}% "
                f"| {ep_overhead.get('p99', 'N/A'):+.2f}% "
                f"| {ep_overhead.get('cpu', 'N/A'):+.2f}% "
                f"| {ep_overhead.get('memory', 'N/A'):+.2f}% |"
            )

    lines.extend([
        "",
        "<details>",
        "<summary>Details</summary>",
        "",
        f"- Iterations: {results.get('iterations', 'N/A')}",
        f"- RPS: {results.get('load', {}).get('rps', 'N/A')}",
        f"- Duration: {results.get('load', {}).get('duration', 'N/A')}",
        "",
        "</details>",
    ])

    return "\n".join(lines)


def post_comment(repo: str, pr_number: int, body: str) -> None:
    """Post or update a sticky comment on a GitHub PR.

    Uses `gh` CLI to find an existing comment with our marker and update it,
    or create a new one if none exists.
    """
    # Find existing comment
    existing = _find_existing_comment(repo, pr_number)

    if existing:
        # Update existing comment
        subprocess.run(
            ["gh", "api", "--method", "PATCH",
             f"repos/{repo}/issues/comments/{existing}",
             "-f", f"body={body}"],
            check=True,
            capture_output=True,
        )
    else:
        # Create new comment
        subprocess.run(
            ["gh", "api", "--method", "POST",
             f"repos/{repo}/issues/{pr_number}/comments",
             "-f", f"body={body}"],
            check=True,
            capture_output=True,
        )


def _find_existing_comment(repo: str, pr_number: int) -> int | None:
    """Find an existing benchmark comment on a PR, return its ID or None."""
    result = subprocess.run(
        ["gh", "api", f"repos/{repo}/issues/{pr_number}/comments",
         "--jq", f'[.[] | select(.body | startswith("{COMMENT_MARKER}"))][0].id'],
        capture_output=True,
        text=True,
    )
    if result.returncode == 0 and result.stdout.strip():
        try:
            return int(result.stdout.strip())
        except ValueError:
            return None
    return None


def post_results(repo: str, pr_number: int, results_file: str) -> None:
    """Load results from a JSON file and post as a PR comment."""
    with open(results_file) as f:
        results = json.load(f)
    body = format_comment(results)
    post_comment(repo, pr_number, body)
