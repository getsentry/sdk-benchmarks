"""Tests for GitHub integration — PR comment formatting."""

from lib.github import COMMENT_MARKER, format_comment


def test_format_comment_includes_marker():
    """The comment should start with the marker for sticky updates."""
    results = {"app": "python/django", "sdk_version": "2.0.0", "summary": {"overhead": {}}}
    body = format_comment(results)
    assert body.startswith(COMMENT_MARKER)


def test_format_comment_includes_app_name():
    results = {"app": "python/django", "sdk_version": "2.0.0", "summary": {"overhead": {}}}
    body = format_comment(results)
    assert "python/django" in body


def test_format_comment_shows_overhead():
    results = {
        "app": "python/django",
        "sdk_version": "2.0.0",
        "summary": {
            "overhead": {"p50": 3.5, "p99": 7.2},
            "regression": False,
        },
    }
    body = format_comment(results)
    assert "+3.50%" in body
    assert "+7.20%" in body
    assert "No regression" in body


def test_format_comment_shows_regression():
    results = {
        "app": "python/django",
        "sdk_version": "2.0.0",
        "summary": {
            "overhead": {"p50": 12.0},
            "regression": True,
        },
    }
    body = format_comment(results)
    assert "Regression detected" in body


def test_format_comment_per_endpoint():
    results = {
        "app": "go/net-http",
        "sdk_version": "0.31.0",
        "summary": {"overhead": {}},
        "endpoints": {
            "json": {
                "overhead": {"p50": 1.2, "p99": 2.5, "cpu": 0.8, "memory": 1.0},
            },
        },
    }
    body = format_comment(results)
    assert "json" in body
    assert "+1.20%" in body


def test_format_comment_per_endpoint_missing_metrics():
    """Per-endpoint formatting should not crash when metrics are missing."""
    results = {
        "app": "go/gin",
        "sdk_version": "0.31.0",
        "summary": {"overhead": {}},
        "endpoints": {
            "db": {
                "overhead": {"p50": 2.0},
            },
        },
    }
    body = format_comment(results)
    assert "db" in body
    assert "+2.00%" in body
    assert "N/A" in body


def test_format_comment_iterations_as_list():
    """Iterations stored as a list should render as a count, not raw list."""
    results = {
        "app": "python/django",
        "sdk_version": "2.0.0",
        "summary": {"overhead": {}},
        "iterations": [{"variant": "baseline"}, {"variant": "instrumented"}],
    }
    body = format_comment(results)
    assert "Iterations: 2" in body
