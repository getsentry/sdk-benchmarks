"""Tests for the docker-compose Jinja2 template."""

import yaml
from jinja2 import Environment, FileSystemLoader


SAMPLE_CONFIG = {
    "language": "python",
    "framework": "django",
    "app_dir": "apps/python/django",
    "endpoints": [
        {"name": "json", "path": "/json"},
        {"name": "db-single", "path": "/db"},
        {"name": "db-multi", "path": "/queries?queries=10"},
        {"name": "fortunes", "path": "/fortunes"},
    ],
    "load": {
        "rps": 100,
        "duration": "30s",
        "warmup": "10s",
        "connections": 10,
    },
    "iterations": 10,
    "resources": {
        "app": {"cpus": "2", "memory": "512m"},
        "postgres": {"cpus": "1", "memory": "256m"},
    },
}

PROJECT_ROOT = "/opt/project"
RESULTS_DIR = "/tmp/results"


def render_template(variant):
    """Render the docker-compose template with the given variant."""
    env = Environment(
        loader=FileSystemLoader("templates"),
        keep_trailing_newline=True,
    )
    template = env.get_template("docker-compose.yml.j2")
    rendered = template.render(
        language=SAMPLE_CONFIG["language"],
        framework=SAMPLE_CONFIG["framework"],
        variant=variant,
        config=SAMPLE_CONFIG,
        project_root=PROJECT_ROOT,
        results_dir=RESULTS_DIR,
    )
    return yaml.safe_load(rendered)


class TestBaselineVariant:
    def setup_method(self):
        self.compose = render_template("baseline")

    def test_has_expected_services(self):
        services = set(self.compose["services"].keys())
        assert services == {"postgres", "app", "loadgen"}

    def test_app_uses_baseline_dockerfile(self):
        app = self.compose["services"]["app"]
        assert app["build"]["dockerfile"] == "Dockerfile.baseline"

    def test_app_has_no_sentry_dsn(self):
        env = self.compose["services"]["app"]["environment"]
        assert "SENTRY_DSN" not in env

    def test_app_has_database_env(self):
        env = self.compose["services"]["app"]["environment"]
        assert env["DB_HOST"] == "postgres"
        assert env["DB_NAME"] == "hello_world"
        assert env["DB_USER"] == "benchmarkdbuser"

    def test_loadgen_env_vars(self):
        env = self.compose["services"]["loadgen"]["environment"]
        assert env["TARGET_HOST"] == "app:8080"
        assert str(env["RPS"]) == "100"
        assert str(env["DURATION"]) == "30s"
        assert str(env["WARMUP"]) == "10s"
        assert str(env["CONNECTIONS"]) == "10"

    def test_loadgen_endpoints(self):
        env = self.compose["services"]["loadgen"]["environment"]
        endpoints = env["ENDPOINTS"]
        assert "/json" in endpoints
        assert "/db" in endpoints
        assert "/fortunes" in endpoints

    def test_app_resource_limits(self):
        app = self.compose["services"]["app"]
        assert str(app["cpus"]) == "2"
        assert app["mem_limit"] == "512m"

    def test_postgres_resource_limits(self):
        pg = self.compose["services"]["postgres"]
        assert str(pg["cpus"]) == "1"
        assert pg["mem_limit"] == "256m"

    def test_loadgen_mounts_results_volume(self):
        loadgen = self.compose["services"]["loadgen"]
        assert any("/results" in str(v) for v in loadgen["volumes"])

    def test_shared_network(self):
        assert "bench" in self.compose["networks"]


class TestInstrumentedVariant:
    def setup_method(self):
        self.compose = render_template("instrumented")

    def test_has_expected_services(self):
        services = set(self.compose["services"].keys())
        assert services == {"postgres", "app", "loadgen", "fakerelay"}

    def test_app_uses_instrumented_dockerfile(self):
        app = self.compose["services"]["app"]
        assert app["build"]["dockerfile"] == "Dockerfile.instrumented"

    def test_app_has_sentry_dsn(self):
        env = self.compose["services"]["app"]["environment"]
        assert env["SENTRY_DSN"] == "http://sentry@fakerelay:5000/1"

    def test_fakerelay_build_context(self):
        fakerelay = self.compose["services"]["fakerelay"]
        assert fakerelay["build"]["context"] == f"{PROJECT_ROOT}/tools/fakerelay"

    def test_fakerelay_on_bench_network(self):
        fakerelay = self.compose["services"]["fakerelay"]
        assert "bench" in fakerelay["networks"]
