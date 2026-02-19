"""Tests for lib/runner.py — unit tests that don't require Docker."""

import tempfile
from pathlib import Path
from unittest.mock import patch

import yaml

from lib.runner import (
    _compute_pairwise_overhead,
    _compute_summary,
    _extract_per_iteration_latencies,
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

    def test_latest_release_has_fakerelay(self):
        rendered = render_compose(self.config, "latest_release", "/tmp/results")
        compose = yaml.safe_load(rendered)
        assert "fakerelay" in compose["services"]

    def test_current_branch_has_fakerelay(self):
        rendered = render_compose(self.config, "current_branch", "/tmp/results")
        compose = yaml.safe_load(rendered)
        assert "fakerelay" in compose["services"]

    def test_latest_release_uses_instrumented_dockerfile(self):
        rendered = render_compose(self.config, "latest_release", "/tmp/results")
        compose = yaml.safe_load(rendered)
        assert compose["services"]["app"]["build"]["dockerfile"] == "Dockerfile.instrumented"

    def test_current_branch_uses_instrumented_dockerfile(self):
        rendered = render_compose(self.config, "current_branch", "/tmp/results")
        compose = yaml.safe_load(rendered)
        assert compose["services"]["app"]["build"]["dockerfile"] == "Dockerfile.instrumented"

    def test_baseline_uses_baseline_dockerfile(self):
        rendered = render_compose(self.config, "baseline", "/tmp/results")
        compose = yaml.safe_load(rendered)
        assert compose["services"]["app"]["build"]["dockerfile"] == "Dockerfile.baseline"

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


def _make_iteration(variant, iteration, latencies):
    """Helper to create a mock iteration dict."""
    return {
        "variant": variant,
        "iteration": iteration,
        "vegeta_results": [{"latency": lat} for lat in latencies],
        "docker_stats": [],
    }


class TestExtractPerIterationLatencies:
    def test_groups_by_iteration(self):
        iterations = [
            _make_iteration("baseline", 1, [100, 200]),
            _make_iteration("baseline", 2, [150, 250]),
            _make_iteration("current_branch", 1, [110, 210]),
        ]
        result = _extract_per_iteration_latencies(iterations, "baseline")
        assert set(result.keys()) == {1, 2}
        assert result[1] == [100, 200]
        assert result[2] == [150, 250]

    def test_filters_by_variant(self):
        iterations = [
            _make_iteration("baseline", 1, [100]),
            _make_iteration("current_branch", 1, [110]),
        ]
        result = _extract_per_iteration_latencies(iterations, "current_branch")
        assert set(result.keys()) == {1}
        assert result[1] == [110]


class TestComputePairwiseOverhead:
    def test_basic_overhead(self):
        iterations = []
        for i in range(1, 4):
            iterations.append(_make_iteration("baseline", i, [1000] * 100))
            iterations.append(_make_iteration("current_branch", i, [1010] * 100))

        result = _compute_pairwise_overhead(iterations, "baseline", "current_branch")
        assert abs(result["overhead"]["p50"] - 1.0) < 0.5
        assert result["converged"] is True
        assert result["iterations_used"] == 3

    def test_no_data(self):
        result = _compute_pairwise_overhead([], "baseline", "current_branch")
        assert result["overhead"] == {}
        assert result["converged"] is False
        assert result["iterations_used"] == 0


class TestComputeSummary:
    def test_no_regression_with_similar_latencies(self):
        """When baseline and current_branch have similar latencies, no regression."""
        iterations = []
        for i in range(1, 6):
            iterations.append(_make_iteration("baseline", i, [1000] * 100))
            iterations.append(_make_iteration("current_branch", i, [1010] * 100))

        summary = _compute_summary(iterations)
        assert summary["regression"] is False
        assert summary["converged"] is True
        assert summary["iterations_used"] == 5
        cb = summary["comparisons"]["current_branch"]
        assert abs(cb["overhead"]["p50"] - 1.0) < 0.5

    def test_regression_with_large_overhead(self):
        """When current_branch is significantly slower, detect regression."""
        iterations = []
        for i in range(1, 6):
            iterations.append(_make_iteration("baseline", i, [1000] * 100))
            # 5% overhead — above the 2% regression threshold
            iterations.append(_make_iteration("current_branch", i, [1050] * 100))

        summary = _compute_summary(iterations)
        assert summary["regression"] is True
        assert summary["comparisons"]["current_branch"]["overhead"]["p50"] == 5.0

    def test_three_way_no_regression_when_same_as_latest(self):
        """No regression when current_branch overhead matches latest_release."""
        iterations = []
        for i in range(1, 6):
            iterations.append(_make_iteration("baseline", i, [1000] * 100))
            iterations.append(_make_iteration("latest_release", i, [1050] * 100))
            iterations.append(_make_iteration("current_branch", i, [1050] * 100))

        summary = _compute_summary(iterations, has_latest_release=True)
        # Both have 5% overhead, but current_branch is NOT worse than latest_release
        assert summary["regression"] is False
        assert "latest_release" in summary["comparisons"]
        assert "current_branch" in summary["comparisons"]

    def test_three_way_regression_when_worse_than_latest(self):
        """Regression when current_branch is worse than latest_release."""
        iterations = []
        for i in range(1, 6):
            iterations.append(_make_iteration("baseline", i, [1000] * 100))
            iterations.append(_make_iteration("latest_release", i, [1010] * 100))
            # Current branch has 5% overhead while latest has 1%
            iterations.append(_make_iteration("current_branch", i, [1050] * 100))

        summary = _compute_summary(iterations, has_latest_release=True)
        assert summary["regression"] is True

    def test_confidence_intervals_present(self):
        iterations = []
        for i in range(1, 4):
            iterations.append(_make_iteration("baseline", i, [1000] * 50))
            iterations.append(_make_iteration("current_branch", i, [1020] * 50))

        summary = _compute_summary(iterations)
        cb = summary["comparisons"]["current_branch"]
        assert "p50" in cb["confidence_intervals"]
        ci = cb["confidence_intervals"]["p50"]
        assert "lower" in ci
        assert "upper" in ci

    def test_p_values_present(self):
        iterations = []
        for i in range(1, 4):
            iterations.append(_make_iteration("baseline", i, [1000] * 50))
            iterations.append(_make_iteration("current_branch", i, [1020] * 50))

        summary = _compute_summary(iterations)
        cb = summary["comparisons"]["current_branch"]
        assert "p50" in cb["p_values"]

    def test_single_iteration_shows_overhead_without_ci(self):
        """With 1 paired iteration, overhead is computed but no CI or p-value."""
        iterations = [
            _make_iteration("baseline", 1, [1000] * 50),
            _make_iteration("current_branch", 1, [1020] * 50),
        ]
        summary = _compute_summary(iterations)
        cb = summary["comparisons"]["current_branch"]
        assert cb["overhead"]["p50"] == 2.0
        assert cb["confidence_intervals"] == {}
        assert cb["p_values"] == {}
        assert summary["regression"] is False
        assert summary["converged"] is False
        assert summary["iterations_used"] == 1

    def test_no_data(self):
        summary = _compute_summary([])
        assert summary["regression"] is False
        assert summary["converged"] is False

    def test_convergence_with_tight_data(self):
        """Identical overhead across iterations should converge quickly."""
        iterations = []
        for i in range(1, 4):
            iterations.append(_make_iteration("baseline", i, [1000] * 100))
            iterations.append(_make_iteration("current_branch", i, [1010] * 100))

        summary = _compute_summary(iterations)
        assert summary["converged"] is True

    def test_no_convergence_with_noisy_data(self):
        """Highly variable overhead should not converge with few iterations."""
        import random
        random.seed(42)
        iterations = []
        for i in range(1, 4):
            # Baseline stable, but current_branch wildly varies per iteration
            base = [1000] * 100
            if i == 1:
                inst = [1200] * 100  # +20%
            elif i == 2:
                inst = [900] * 100   # -10%
            else:
                inst = [1100] * 100  # +10%
            iterations.append(_make_iteration("baseline", i, base))
            iterations.append(_make_iteration("current_branch", i, inst))

        summary = _compute_summary(iterations)
        # CI is wide due to variance, so should not converge
        assert summary["converged"] is False
