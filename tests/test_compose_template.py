"""Tests for the docker-compose Jinja2 template."""

import pathlib

import yaml
from jinja2 import Environment, FileSystemLoader

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
TEMPLATE_DIR = REPO_ROOT / "templates"


def _render(variant: str) -> str:
    """Render the docker-compose template with sample config values."""
    env = Environment(loader=FileSystemLoader(str(TEMPLATE_DIR)))
    template = env.get_template("docker-compose.yml.j2")
    return template.render(
        variant=variant,
        app_dir="apps/python/django",
        endpoints=["/json", "/db", "/queries?queries=10"],
        load={
            "rps": 100,
            "duration": "30s",
            "warmup": "10s",
            "connections": 10,
        },
        resources={
            "app": {"cpus": "2", "memory": "512m"},
            "postgres": {"cpus": "1", "memory": "256m"},
        },
    )


def _parse(rendered: str) -> dict:
    """Parse rendered YAML into a dict."""
    return yaml.safe_load(rendered)


class TestBaselineVariant:
    def test_renders_valid_yaml(self):
        parsed = _parse(_render("baseline"))
        assert "services" in parsed

    def test_no_fakerelay_service(self):
        parsed = _parse(_render("baseline"))
        assert "fakerelay" not in parsed["services"]

    def test_no_sentry_dsn(self):
        parsed = _parse(_render("baseline"))
        app_env = parsed["services"]["app"]["environment"]
        assert "SENTRY_DSN" not in app_env

    def test_app_depends_on_postgres_only(self):
        parsed = _parse(_render("baseline"))
        deps = parsed["services"]["app"]["depends_on"]
        assert "postgres" in deps
        assert "fakerelay" not in deps


class TestInstrumentedVariant:
    def test_renders_valid_yaml(self):
        parsed = _parse(_render("instrumented"))
        assert "services" in parsed

    def test_has_fakerelay_service(self):
        parsed = _parse(_render("instrumented"))
        assert "fakerelay" in parsed["services"]

    def test_fakerelay_exposes_port_5000(self):
        parsed = _parse(_render("instrumented"))
        ports = parsed["services"]["fakerelay"]["ports"]
        assert "5000:5000" in ports

    def test_app_has_sentry_dsn(self):
        parsed = _parse(_render("instrumented"))
        app_env = parsed["services"]["app"]["environment"]
        assert app_env["SENTRY_DSN"] == "http://sentry@fakerelay:5000/1"

    def test_app_depends_on_fakerelay(self):
        parsed = _parse(_render("instrumented"))
        deps = parsed["services"]["app"]["depends_on"]
        assert "fakerelay" in deps


class TestLoadgenService:
    def test_target_host(self):
        parsed = _parse(_render("baseline"))
        env = parsed["services"]["loadgen"]["environment"]
        assert env["TARGET_HOST"] == "app:8080"

    def test_rps(self):
        parsed = _parse(_render("baseline"))
        env = parsed["services"]["loadgen"]["environment"]
        assert env["RPS"] == "100"

    def test_duration(self):
        parsed = _parse(_render("baseline"))
        env = parsed["services"]["loadgen"]["environment"]
        assert env["DURATION"] == "30s"

    def test_warmup(self):
        parsed = _parse(_render("baseline"))
        env = parsed["services"]["loadgen"]["environment"]
        assert env["WARMUP"] == "10s"

    def test_endpoints(self):
        parsed = _parse(_render("baseline"))
        env = parsed["services"]["loadgen"]["environment"]
        assert env["ENDPOINTS"] == "/json,/db,/queries?queries=10"

    def test_connections(self):
        parsed = _parse(_render("baseline"))
        env = parsed["services"]["loadgen"]["environment"]
        assert env["CONNECTIONS"] == "10"

    def test_no_restart(self):
        parsed = _parse(_render("baseline"))
        assert parsed["services"]["loadgen"]["restart"] == "no"

    def test_results_volume(self):
        parsed = _parse(_render("baseline"))
        volumes = parsed["services"]["loadgen"]["volumes"]
        assert "./results:/results" in volumes


class TestCommonServices:
    def test_postgres_healthcheck(self):
        parsed = _parse(_render("baseline"))
        hc = parsed["services"]["postgres"]["healthcheck"]
        assert "pg_isready" in hc["test"][-1]

    def test_postgres_env(self):
        parsed = _parse(_render("baseline"))
        env = parsed["services"]["postgres"]["environment"]
        assert env["POSTGRES_DB"] == "hello_world"
        assert env["POSTGRES_USER"] == "benchmarkdbuser"
        assert env["POSTGRES_PASSWORD"] == "benchmarkdbpass"

    def test_app_db_env(self):
        parsed = _parse(_render("baseline"))
        env = parsed["services"]["app"]["environment"]
        assert env["DB_HOST"] == "postgres"
        assert env["DB_PORT"] == "5432"
        assert env["DB_NAME"] == "hello_world"

    def test_shared_network(self):
        parsed = _parse(_render("baseline"))
        assert "bench" in parsed["networks"]
        for svc_name, svc in parsed["services"].items():
            assert "bench" in svc["networks"], f"{svc_name} missing bench network"

    def test_resource_limits(self):
        parsed = _parse(_render("baseline"))
        app_limits = parsed["services"]["app"]["deploy"]["resources"]["limits"]
        assert app_limits["cpus"] == "2"
        assert app_limits["memory"] == "512m"
        pg_limits = parsed["services"]["postgres"]["deploy"]["resources"]["limits"]
        assert pg_limits["cpus"] == "1"
        assert pg_limits["memory"] == "256m"
