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


def _format_overhead_value(comp: dict, metric: str) -> str:
    """Format a single overhead value with CI for a comparison dict."""
    overhead = comp.get("overhead", {})
    cis = comp.get("confidence_intervals", {})
    value = overhead.get(metric)
    if not isinstance(value, (int, float)):
        return "N/A"
    ci = cis.get(metric)
    if ci:
        return f"{value:+.2f}% [{ci['lower']:+.2f}%, {ci['upper']:+.2f}%]"
    return f"{value:+.2f}%"


def _overhead_table(summary: dict) -> list[str]:
    """Render the overhead table for a summary with comparisons."""
    comparisons = summary.get("comparisons", {})
    has_latest = "latest_release" in comparisons
    cb = comparisons.get("current_branch", {})
    lr = comparisons.get("latest_release", {})

    if has_latest:
        lines = [
            "| Metric | Latest Release | Current Branch | Diff | p-value |",
            "|--------|---------------|----------------|------|---------|",
        ]
    else:
        lines = [
            "| Metric | Overhead | 95% CI | p-value |",
            "|--------|----------|--------|---------|",
        ]

    for metric in ["p95", "p99"]:
        cb_overhead = cb.get("overhead", {}).get(metric)
        if not isinstance(cb_overhead, (int, float)):
            continue

        cb_p_val = cb.get("p_values", {}).get(metric)
        p_str = f"{cb_p_val:.4f}" if cb_p_val is not None else "N/A"

        if has_latest:
            lr_str = _format_overhead_value(lr, metric)
            cb_str = _format_overhead_value(cb, metric)
            lr_val = lr.get("overhead", {}).get(metric)
            cb_val = cb_overhead
            if isinstance(lr_val, (int, float)) and isinstance(cb_val, (int, float)):
                diff = cb_val - lr_val
                diff_str = f"{diff:+.2f}pp"
            else:
                diff_str = "N/A"
            lines.append(f"| {metric} | {lr_str} | {cb_str} | {diff_str} | {p_str} |")
        else:
            cb_ci = cb.get("confidence_intervals", {}).get(metric)
            ci_str = f"[{cb_ci['lower']:+.2f}%, {cb_ci['upper']:+.2f}%]" if cb_ci else "N/A"
            lines.append(f"| {metric} | {cb_overhead:+.2f}% | {ci_str} | {p_str} |")

    return lines


def format_comment(results: dict) -> str:
    """Format benchmark results as a Markdown PR comment."""
    summary = results.get("summary", {})
    app = results.get("app", "unknown")
    sdk_version = results.get("sdk_version", "unknown")
    latest_sdk_version = results.get("latest_sdk_version")

    status = _status_label(summary)

    lines = [
        COMMENT_MARKER,
        f"## SDK Benchmark Results — `{app}`",
        "",
    ]

    if latest_sdk_version:
        lines.append(f"Current branch: `{sdk_version}` | Latest release: `{latest_sdk_version}`")
    else:
        lines.append(f"SDK version: `{sdk_version}`")

    lines.extend([
        f"Status: {status}",
        "",
        "### Latency Overhead (vs baseline)",
        "",
    ])

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


def _get_summary_p95(summary: dict) -> str:
    """Extract p95 overhead string from the current_branch comparison."""
    comparisons = summary.get("comparisons", {})
    cb = comparisons.get("current_branch", {})
    p95 = cb.get("overhead", {}).get("p95")
    return f"{p95:+.2f}%" if isinstance(p95, (int, float)) else "N/A"


def _get_summary_p99(summary: dict) -> str:
    """Extract p99 overhead string from the current_branch comparison."""
    comparisons = summary.get("comparisons", {})
    cb = comparisons.get("current_branch", {})
    p99 = cb.get("overhead", {}).get("p99")
    return f"{p99:+.2f}%" if isinstance(p99, (int, float)) else "N/A"


def format_combined_comment(results_list: list[dict]) -> str:
    """Format results from multiple apps into a single combined PR comment."""
    lines = [
        COMMENT_MARKER,
        "## SDK Benchmark Results",
        "",
    ]

    # Summary table
    lines.extend([
        "| App | SDK Version | Status | p95 Overhead | p99 Overhead |",
        "|-----|-------------|--------|-------------|-------------|",
    ])

    for results in results_list:
        summary = results.get("summary", {})
        app = results.get("app", "unknown")
        sdk_version = results.get("sdk_version", "unknown")
        emoji = _status_emoji(summary)
        status = _status_label(summary)

        p95_str = _get_summary_p95(summary)
        p99_str = _get_summary_p99(summary)

        lines.append(f"| `{app}` | `{sdk_version}` | {emoji} {status} | {p95_str} | {p99_str} |")

    # Per-app details
    for results in results_list:
        summary = results.get("summary", {})
        app = results.get("app", "unknown")
        sdk_version = results.get("sdk_version", "unknown")
        latest_sdk_version = results.get("latest_sdk_version")

        status = _status_label(summary)
        iterations_used = summary.get("iterations_used")
        converged = summary.get("converged")

        lines.extend([
            "",
            f"### `{app}` — {status}",
            "",
        ])

        if latest_sdk_version:
            lines.append(f"Current branch: `{sdk_version}` | Latest release: `{latest_sdk_version}`")
        else:
            lines.append(f"SDK version: `{sdk_version}`")

        lines.append("")

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
