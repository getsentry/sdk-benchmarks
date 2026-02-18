"""Tests for the CLI entrypoint."""

import json
import os
import tempfile
from unittest.mock import patch

from click.testing import CliRunner

from bench import _list_apps, _resolve_version, cli


def test_cli_group_exists():
    """The CLI group should be a click Group."""
    assert hasattr(cli, "commands")


def test_cli_has_run_command():
    """The CLI should have a 'run' command."""
    assert "run" in cli.commands


def test_cli_has_compare_command():
    """The CLI should have a 'compare' command."""
    assert "compare" in cli.commands


def test_cli_version():
    """The --version flag should print the version."""
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output


def test_cli_has_list_apps_command():
    assert "list-apps" in cli.commands


def test_cli_has_resolve_version_command():
    assert "resolve-version" in cli.commands


def test_list_apps_go():
    apps = _list_apps("go")
    assert apps == ["go/echo", "go/gin", "go/net-http"]


def test_list_apps_python():
    apps = _list_apps("python")
    assert apps == ["python/django"]


def test_list_apps_unknown_language():
    apps = _list_apps("rust")
    assert apps == []


def test_list_apps_cli():
    runner = CliRunner()
    result = runner.invoke(cli, ["list-apps", "go"])
    assert result.exit_code == 0
    apps = json.loads(result.output)
    assert apps == ["go/echo", "go/gin", "go/net-http"]


def test_resolve_version_go():
    mock_response = json.dumps({"Version": "v0.42.0", "Time": "2024-01-01T00:00:00Z"})
    with patch("bench.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda s, *a: None
        mock_urlopen.return_value.read.return_value = mock_response.encode()
        version = _resolve_version("go")
    assert version == "0.42.0"


def test_resolve_version_python():
    mock_response = json.dumps({"info": {"version": "2.1.0"}})
    with patch("bench.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda s, *a: None
        mock_urlopen.return_value.read.return_value = mock_response.encode()
        version = _resolve_version("python")
    assert version == "2.1.0"


def test_resolve_version_unknown_language():
    runner = CliRunner()
    result = runner.invoke(cli, ["resolve-version", "rust"])
    assert result.exit_code != 0
    assert "No version resolver configured" in result.output


def test_resolve_version_cli():
    mock_response = json.dumps({"Version": "v0.42.0", "Time": "2024-01-01T00:00:00Z"})
    with patch("bench.urlopen") as mock_urlopen:
        mock_urlopen.return_value.__enter__ = lambda s: s
        mock_urlopen.return_value.__exit__ = lambda s, *a: None
        mock_urlopen.return_value.read.return_value = mock_response.encode()
        runner = CliRunner()
        result = runner.invoke(cli, ["resolve-version", "go"])
    assert result.exit_code == 0
    assert "0.42.0" in result.output


def test_cli_has_post_summary_command():
    assert "post-summary" in cli.commands


def test_post_summary_no_results():
    """post-summary should fail when no results.json files exist."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        result = runner.invoke(cli, ["post-summary", "--repo=test/repo", "--pr=1",
                                     f"--results-dir={tmpdir}"])
    assert result.exit_code != 0
    assert "No results.json files found" in result.output


def test_post_summary_finds_results():
    """post-summary should find and format results from subdirectories."""
    runner = CliRunner()
    with tempfile.TemporaryDirectory() as tmpdir:
        # Create fake results
        for app_dir in ["go-gin", "go-echo"]:
            os.makedirs(os.path.join(tmpdir, app_dir))
            results = {
                "app": app_dir.replace("-", "/"),
                "sdk_version": "0.42.0",
                "summary": {
                    "overhead": {"p50": 1.0},
                    "confidence_intervals": {},
                    "p_values": {},
                    "regression": False,
                    "converged": True,
                    "iterations_used": 5,
                },
                "load": {"rps": 100, "duration": "30s"},
            }
            with open(os.path.join(tmpdir, app_dir, "results.json"), "w") as f:
                json.dump(results, f)

        with patch("lib.github.post_comment") as mock_post:
            result = runner.invoke(cli, ["post-summary", "--repo=test/repo", "--pr=1",
                                         f"--results-dir={tmpdir}"])

    assert result.exit_code == 0
    assert "go/echo" in result.output
    assert "go/gin" in result.output
