"""Tests for the CLI entrypoint."""

import json
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
