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
