"""CLI entrypoint for sdk-benchmarks."""

import click

__version__ = "0.1.0"


@click.group()
@click.version_option(version=__version__)
def cli():
    """Benchmark suite for Sentry SDKs."""


@cli.command()
@click.argument("app")
@click.option("--sdk-version", required=True, help="SDK version to benchmark.")
@click.option("--iterations", default=10, help="Number of iterations to run.")
@click.option("--output-dir", default="results/", help="Directory to write results to.")
def run(app, sdk_version, iterations, output_dir):
    """Run benchmarks for an APP (e.g. 'python/django')."""
    click.echo("Not implemented yet")


@cli.command()
@click.argument("baseline", type=click.Path(exists=True))
@click.argument("candidate", type=click.Path(exists=True))
def compare(baseline, candidate):
    """Compare two result JSON files (BASELINE vs CANDIDATE)."""
    click.echo("Not implemented yet")


@cli.command("post-comment")
@click.option("--repo", required=True, help="GitHub repo (owner/name).")
@click.option("--pr", required=True, type=int, help="PR number.")
@click.option("--results-file", required=True, type=click.Path(exists=True), help="Results JSON.")
def post_comment(repo, pr, results_file):
    """Post benchmark results as a PR comment."""
    from lib.github import post_results

    post_results(repo, pr, results_file)
    click.echo(f"Posted benchmark results to {repo}#{pr}")
