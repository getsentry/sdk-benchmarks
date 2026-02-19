"""CLI entrypoint for sdk-benchmarks."""

import json
from pathlib import Path
from urllib.request import urlopen

import click
import yaml

__version__ = "0.1.0"

CONFIGS_DIR = Path(__file__).parent / "configs"

VERSION_RESOLVERS = {
    "go": {
        "url": "https://proxy.golang.org/github.com/getsentry/sentry-go/@latest",
        "parse": lambda data: json.loads(data)["Version"].lstrip("v"),
    },
    "python": {
        "url": "https://pypi.org/pypi/sentry-sdk/json",
        "parse": lambda data: json.loads(data)["info"]["version"],
    },
}


def _list_apps(language: str) -> list[str]:
    """Scan configs/*.yaml and return app names matching the given language."""
    apps = []
    for config_path in sorted(CONFIGS_DIR.glob("*.yaml")):
        with open(config_path) as f:
            config = yaml.safe_load(f)
        if config.get("language") == language:
            apps.append(f"{config['language']}/{config['framework']}")
    return apps


def _resolve_version(language: str) -> str:
    """Resolve the latest Sentry SDK version for a language."""
    resolver = VERSION_RESOLVERS.get(language)
    if not resolver:
        raise click.ClickException(f"No version resolver configured for language: {language}")

    with urlopen(resolver["url"]) as resp:
        data = resp.read().decode()
    return resolver["parse"](data)


@click.group()
@click.version_option(version=__version__)
def cli():
    """Benchmark suite for Sentry SDKs."""


@cli.command("list-apps")
@click.argument("language")
def list_apps(language):
    """List benchmark apps for a LANGUAGE (e.g. 'go', 'python')."""
    apps = _list_apps(language)
    click.echo(json.dumps(apps))


@cli.command("resolve-version")
@click.argument("language")
def resolve_version(language):
    """Resolve the latest Sentry SDK version for a LANGUAGE."""
    version = _resolve_version(language)
    click.echo(version)


@cli.command()
@click.argument("app")
@click.option("--sdk-version", required=True, help="SDK version to benchmark (current branch).")
@click.option("--latest-sdk-version", default=None, help="Latest stable SDK version for 3-way comparison.")
@click.option("--iterations", default=10, help="Number of iterations to run.")
@click.option("--output-dir", default="results/", help="Directory to write results to.")
def run(app, sdk_version, latest_sdk_version, iterations, output_dir):
    """Run benchmarks for an APP (e.g. 'python/django')."""
    import logging

    from lib.runner import run_benchmark

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
    results = run_benchmark(
        app,
        sdk_version,
        iterations=iterations,
        output_dir=output_dir,
        latest_sdk_version=latest_sdk_version,
    )
    click.echo(f"Benchmark complete. {len(results.get('iterations', []))} iterations recorded.")


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


@cli.command("post-summary")
@click.option("--repo", required=True, help="GitHub repo (owner/name).")
@click.option("--pr", required=True, type=int, help="PR number.")
@click.option("--results-dir", required=True, type=click.Path(exists=True), help="Directory containing result subdirs.")
def post_summary(repo, pr, results_dir):
    """Post combined benchmark results from multiple apps as a single PR comment."""
    from lib.github import format_combined_comment, post_comment as gh_post_comment

    results_path = Path(results_dir)
    results_list = []
    for results_file in sorted(results_path.glob("*/results.json")):
        with open(results_file) as f:
            results_list.append(json.load(f))

    if not results_list:
        raise click.ClickException(f"No results.json files found in {results_dir}/*/")

    body = format_combined_comment(results_list)
    gh_post_comment(repo, pr, body)
    apps = [r.get("app", "unknown") for r in results_list]
    click.echo(f"Posted combined results for {', '.join(apps)} to {repo}#{pr}")
