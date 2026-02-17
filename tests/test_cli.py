"""Tests for the CLI entrypoint."""

from click.testing import CliRunner

from bench import cli


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
