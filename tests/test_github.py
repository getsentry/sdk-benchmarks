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
