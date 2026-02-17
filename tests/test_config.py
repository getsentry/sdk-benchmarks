"""Tests for the python-django benchmark configuration."""

import pathlib

import yaml

REPO_ROOT = pathlib.Path(__file__).resolve().parent.parent
CONFIG_PATH = REPO_ROOT / "configs" / "python-django.yaml"


def _load_config() -> dict:
    """Load and parse the config file."""
    with open(CONFIG_PATH) as f:
        return yaml.safe_load(f)


class TestRequiredFields:
    def test_has_language(self):
        assert "language" in _load_config()

    def test_has_framework(self):
        assert "framework" in _load_config()

    def test_has_app_dir(self):
        assert "app_dir" in _load_config()

    def test_has_endpoints(self):
        assert "endpoints" in _load_config()

    def test_has_load(self):
        assert "load" in _load_config()

    def test_has_iterations(self):
        assert "iterations" in _load_config()

    def test_has_resources(self):
        assert "resources" in _load_config()


class TestFieldTypes:
    def test_language_is_str(self):
        assert isinstance(_load_config()["language"], str)

    def test_framework_is_str(self):
        assert isinstance(_load_config()["framework"], str)

    def test_app_dir_is_str(self):
        assert isinstance(_load_config()["app_dir"], str)

    def test_endpoints_is_list(self):
        assert isinstance(_load_config()["endpoints"], list)

    def test_endpoints_have_name_and_path(self):
        for ep in _load_config()["endpoints"]:
            assert "name" in ep, f"Endpoint missing 'name': {ep}"
            assert "path" in ep, f"Endpoint missing 'path': {ep}"

    def test_rps_is_int(self):
        assert isinstance(_load_config()["load"]["rps"], int)

    def test_duration_is_str(self):
        assert isinstance(_load_config()["load"]["duration"], str)

    def test_warmup_is_str(self):
        assert isinstance(_load_config()["load"]["warmup"], str)

    def test_connections_is_int(self):
        assert isinstance(_load_config()["load"]["connections"], int)

    def test_iterations_is_int(self):
        assert isinstance(_load_config()["iterations"], int)

    def test_resources_has_app_and_postgres(self):
        resources = _load_config()["resources"]
        assert "app" in resources
        assert "postgres" in resources

    def test_resource_limits_are_strings(self):
        for svc in ("app", "postgres"):
            res = _load_config()["resources"][svc]
            assert isinstance(res["cpus"], str), f"{svc} cpus should be string"
            assert isinstance(res["memory"], str), f"{svc} memory should be string"


class TestFieldValues:
    def test_language_is_python(self):
        assert _load_config()["language"] == "python"

    def test_framework_is_django(self):
        assert _load_config()["framework"] == "django"

    def test_at_least_one_endpoint(self):
        assert len(_load_config()["endpoints"]) > 0

    def test_rps_positive(self):
        assert _load_config()["load"]["rps"] > 0

    def test_iterations_positive(self):
        assert _load_config()["iterations"] > 0
