"""Tests for GitHub integration — PR comment formatting."""

from lib.github import COMMENT_MARKER, format_combined_comment, format_comment


def _make_results(app="python/django", sdk_version="2.0.0", overhead=None, regression=False,
                  converged=True, iterations_used=5, p_values=None, cis=None):
    """Helper to create a results dict with the new summary format."""
    return {
        "app": app,
        "sdk_version": sdk_version,
        "summary": {
            "overhead": overhead or {},
            "confidence_intervals": cis or {},
            "p_values": p_values or {},
            "regression": regression,
            "converged": converged,
            "iterations_used": iterations_used,
        },
        "load": {"rps": 100, "duration": "30s"},
    }


class TestFormatComment:
    def test_includes_marker(self):
        body = format_comment(_make_results())
        assert body.startswith(COMMENT_MARKER)

    def test_includes_app_name(self):
        body = format_comment(_make_results(app="go/gin"))
        assert "go/gin" in body

    def test_shows_overhead_with_ci(self):
        results = _make_results(
            overhead={"p50": 3.5, "p99": 7.2},
            cis={
                "p50": {"lower": 2.0, "upper": 5.0},
                "p99": {"lower": 4.0, "upper": 10.4},
            },
            p_values={"p50": 0.01, "p99": 0.03},
        )
        body = format_comment(results)
        assert "+3.50%" in body
        assert "+7.20%" in body
        assert "[+2.00%, +5.00%]" in body
        assert "0.0100" in body

    def test_shows_no_regression(self):
        body = format_comment(_make_results(regression=False, converged=True))
        assert "No regression" in body

    def test_shows_regression(self):
        body = format_comment(_make_results(regression=True))
        assert "Regression detected" in body

    def test_shows_inconclusive(self):
        body = format_comment(_make_results(converged=False, regression=False))
        assert "Inconclusive" in body

    def test_shows_iterations_used(self):
        body = format_comment(_make_results(iterations_used=7))
        assert "Iterations used: 7" in body

    def test_shows_convergence_status(self):
        body = format_comment(_make_results(converged=True))
        assert "Converged: yes" in body
        body2 = format_comment(_make_results(converged=False))
        assert "Converged: no" in body2


class TestFormatCombinedComment:
    def test_includes_marker(self):
        results_list = [_make_results(app="go/gin"), _make_results(app="go/echo")]
        body = format_combined_comment(results_list)
        assert body.startswith(COMMENT_MARKER)
        # Only one marker
        assert body.count(COMMENT_MARKER) == 1

    def test_includes_all_apps(self):
        results_list = [
            _make_results(app="go/gin", overhead={"p50": 1.0, "p99": 2.0}),
            _make_results(app="go/echo", overhead={"p50": 0.5, "p99": 1.5}),
            _make_results(app="go/net-http", overhead={"p50": 0.8, "p99": 1.2}),
        ]
        body = format_combined_comment(results_list)
        assert "go/gin" in body
        assert "go/echo" in body
        assert "go/net-http" in body

    def test_summary_table(self):
        results_list = [
            _make_results(app="go/gin", overhead={"p50": 1.5, "p99": 3.0}),
        ]
        body = format_combined_comment(results_list)
        assert "+1.50%" in body
        assert "+3.00%" in body

    def test_per_app_sections(self):
        results_list = [
            _make_results(app="go/gin", regression=False),
            _make_results(app="go/echo", regression=True),
        ]
        body = format_combined_comment(results_list)
        # Each app should have its own section header
        assert "### `go/gin`" in body
        assert "### `go/echo`" in body
        assert "Regression detected" in body
        assert "No regression" in body

    def test_status_emojis_in_summary(self):
        results_list = [
            _make_results(app="go/gin", regression=False, converged=True),
            _make_results(app="go/echo", regression=True),
            _make_results(app="go/net-http", regression=False, converged=False),
        ]
        body = format_combined_comment(results_list)
        assert ":white_check_mark:" in body
        assert ":warning:" in body
        assert ":grey_question:" in body
