"""Tests for lib/runner.py — unit tests that don't require Docker."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from lib.runner import (
    _parse_mem_usage,
    _prepare_sdk_version,
    load_config,
    render_compose,
)


class TestLoadConfig:
    def test_loads_python_django(self):
        config = load_config("python/django")
        assert config["language"] == "python"
        assert config["framework"] == "django"
        assert len(config["endpoints"]) == 4

    def test_has_load_settings(self):
        config = load_config("python/django")
        assert config["load"]["rps"] == 100
        assert config["load"]["duration"] == "30s"

    def test_has_resource_limits(self):
        config = load_config("python/django")
        assert config["resources"]["app"]["memory"] == "512m"


class TestRenderCompose:
    def setup_method(self):
        self.config = load_config("python/django")

    def test_baseline_has_no_fakerelay(self):
        rendered = render_compose(self.config, "baseline", "/tmp/results")
        compose = yaml.safe_load(rendered)
        assert "fakerelay" not in compose["services"]

    def test_instrumented_has_fakerelay(self):
        rendered = render_compose(self.config, "instrumented", "/tmp/results")
        compose = yaml.safe_load(rendered)
        assert "fakerelay" in compose["services"]

    def test_uses_absolute_project_root(self):
        rendered = render_compose(self.config, "baseline", "/tmp/results")
        compose = yaml.safe_load(rendered)
        context = compose["services"]["postgres"]["build"]["context"]
        assert context.startswith("/")
        assert "apps/python/common/postgres" in context

    def test_results_dir_mounted(self):
        rendered = render_compose(self.config, "baseline", "/tmp/my-results")
        compose = yaml.safe_load(rendered)
        volumes = compose["services"]["loadgen"]["volumes"]
        assert any("/tmp/my-results" in str(v) for v in volumes)


class TestParseMemUsage:
    def test_mib(self):
        assert _parse_mem_usage("45.2MiB / 512MiB") == 45.2

    def test_gib(self):
        assert _parse_mem_usage("1.5GiB / 2GiB") == 1.5 * 1024

    def test_kib(self):
        assert _parse_mem_usage("512KiB / 1GiB") == 0.5


class TestPrepareSdkVersion:
    def test_renders_python_requirements(self):
        config = load_config("python/django")
        with tempfile.TemporaryDirectory() as tmpdir:
            # Set up a fake app dir with template
            app_dir = Path(tmpdir) / "apps" / "python" / "django"
            app_dir.mkdir(parents=True)
            tmpl = app_dir / "requirements-sentry.txt.tmpl"
            tmpl.write_text("sentry-sdk[django]=={{ sdk_version }}\n")

            config_copy = dict(config)
            config_copy["app_dir"] = "apps/python/django"

            with patch("lib.runner.PROJECT_ROOT", Path(tmpdir)):
                _prepare_sdk_version(config_copy, "2.1.0")

            output = (app_dir / "requirements-sentry.txt").read_text()
            assert "sentry-sdk[django]==2.1.0" in output
