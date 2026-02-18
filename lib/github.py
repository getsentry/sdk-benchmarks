"""GitHub integration — posting results as PR comments and managing artifacts."""

from __future__ import annotations

import json
import subprocess


COMMENT_MARKER = "<!-- sdk-benchmark-results -->"


def _status_label(summary: dict) -> str:
    """Return a human-readable status string from a result summary."""
    regression = summary.get("regression", False)
    converged = summary.get("converged", True)
    if regression:
        return "**Regression detected**"
    if not converged:
        return "Inconclusive (not converged)"
    return "No regression"


def _status_emoji(summary: dict) -> str:
    regression = summary.get("regression", False)
    converged = summary.get("converged", True)
    if regression:
        return ":warning:"
    if not converged:
        return ":grey_question:"
    return ":white_check_mark:"


def _overhead_table(summary: dict) -> list[str]:
    """Render the overhead table rows for a summary dict."""
    overhead = summary.get("overhead", {})
    cis = summary.get("confidence_intervals", {})
    p_vals = summary.get("p_values", {})

    lines = [
        "| Metric | Overhead | 95% CI | p-value |",
        "|--------|----------|--------|---------|",
    ]

    for metric in ["p50", "p99", "mean"]:
        value = overhead.get(metric)
        if not isinstance(value, (int, float)):
            continue
        ci = cis.get(metric)
        ci_str = f"[{ci['lower']:+.2f}%, {ci['upper']:+.2f}%]" if ci else "N/A"
        p_val = p_vals.get(metric)
        p_str = f"{p_val:.4f}" if p_val is not None else "N/A"
        lines.append(f"| {metric} | {value:+.2f}% | {ci_str} | {p_str} |")

    return lines


def format_comment(results: dict) -> str:
    """Format benchmark results as a Markdown PR comment."""
    summary = results.get("summary", {})
    app = results.get("app", "unknown")
    sdk_version = results.get("sdk_version", "unknown")

    status = _status_label(summary)

    lines = [
        COMMENT_MARKER,
        f"## SDK Benchmark Results — `{app}`",
        "",
        f"SDK version: `{sdk_version}`",
        f"Status: {status}",
        "",
        "### Latency Overhead",
        "",
    ]

    lines.extend(_overhead_table(summary))

    iterations_used = summary.get("iterations_used")
    converged = summary.get("converged")

    lines.extend([
        "",
        "<details>",
        "<summary>Details</summary>",
        "",
    ])

    if iterations_used is not None:
        lines.append(f"- Iterations used: {iterations_used}")
    else:
        iters = results.get("iterations")
        count = len(iters) if isinstance(iters, list) else iters
        lines.append(f"- Iterations: {count if count is not None else 'N/A'}")

    if converged is not None:
        lines.append(f"- Converged: {'yes' if converged else 'no'}")

    lines.extend([
        f"- RPS: {results.get('load', {}).get('rps', 'N/A')}",
        f"- Duration: {results.get('load', {}).get('duration', 'N/A')}",
        "",
        "</details>",
    ])

    return "\n".join(lines)


def format_combined_comment(results_list: list[dict]) -> str:
    """Format results from multiple apps into a single combined PR comment."""
    lines = [
        COMMENT_MARKER,
        "## SDK Benchmark Results",
        "",
    ]

    # Summary table
    lines.extend([
        "| App | SDK Version | Status | p50 Overhead | p99 Overhead |",
        "|-----|-------------|--------|-------------|-------------|",
    ])

    for results in results_list:
        summary = results.get("summary", {})
        app = results.get("app", "unknown")
        sdk_version = results.get("sdk_version", "unknown")
        overhead = summary.get("overhead", {})
        emoji = _status_emoji(summary)
        status = _status_label(summary)

        p50 = overhead.get("p50")
        p99 = overhead.get("p99")
        p50_str = f"{p50:+.2f}%" if isinstance(p50, (int, float)) else "N/A"
        p99_str = f"{p99:+.2f}%" if isinstance(p99, (int, float)) else "N/A"

        lines.append(f"| `{app}` | `{sdk_version}` | {emoji} {status} | {p50_str} | {p99_str} |")

    # Per-app details
    for results in results_list:
        summary = results.get("summary", {})
        app = results.get("app", "unknown")
        sdk_version = results.get("sdk_version", "unknown")

        status = _status_label(summary)
        iterations_used = summary.get("iterations_used")
        converged = summary.get("converged")

        lines.extend([
            "",
            f"### `{app}` — {status}",
            "",
            f"SDK version: `{sdk_version}`",
            "",
        ])

        lines.extend(_overhead_table(summary))

        lines.extend([
            "",
            "<details>",
            "<summary>Details</summary>",
            "",
        ])

        if iterations_used is not None:
            lines.append(f"- Iterations used: {iterations_used}")
        if converged is not None:
            lines.append(f"- Converged: {'yes' if converged else 'no'}")
        lines.extend([
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
