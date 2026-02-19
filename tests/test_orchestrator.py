"""Tests for lib/orchestrator.py — unit tests with mocked GitHub API calls."""

import json
import os
import tempfile
from unittest.mock import MagicMock, call, patch

import pytest

from lib.orchestrator import (
    _MIN_ITERATIONS,
    collect_iteration_results,
    dispatch_iteration,
    download_artifact,
    find_run_id,
    orchestrate,
    wait_for_runs,
)


class TestDispatchIteration:
    @patch("lib.orchestrator._gh_api")
    def test_dispatches_with_correct_inputs(self, mock_api):
        mock_api.return_value = None

        dispatch_iteration(
            app="go/net-http",
            sdk_version="0.30.0",
            latest_sdk_version="0.29.0",
            iteration=1,
            run_key="go-net-http-iter1-12345",
            benchmarks_ref="main",
            token="test-token",
        )

        mock_api.assert_called_once()
        args, kwargs = mock_api.call_args
        assert args[0].endswith("/dispatches")
        assert kwargs["method"] == "POST"
        assert kwargs["token"] == "test-token"
        inputs = kwargs["input_data"]["inputs"]
        assert inputs["app"] == "go/net-http"
        assert inputs["sdk-version"] == "0.30.0"
        assert inputs["latest-sdk-version"] == "0.29.0"
        assert inputs["iteration"] == "1"
        assert inputs["run-key"] == "go-net-http-iter1-12345"

    @patch("lib.orchestrator._gh_api")
    def test_dispatches_without_latest_sdk_version(self, mock_api):
        mock_api.return_value = None

        dispatch_iteration(
            app="go/net-http",
            sdk_version="0.30.0",
            latest_sdk_version=None,
            iteration=1,
            run_key="go-net-http-iter1-12345",
            benchmarks_ref="main",
            token="test-token",
        )

        inputs = mock_api.call_args[1]["input_data"]["inputs"]
        assert "latest-sdk-version" not in inputs


class TestFindRunId:
    @patch("lib.orchestrator.time.sleep")
    @patch("lib.orchestrator.time.time")
    @patch("lib.orchestrator._gh_api")
    def test_finds_run_on_first_poll(self, mock_api, mock_time, mock_sleep):
        mock_time.side_effect = [0, 1]  # within timeout
        mock_api.return_value = {
            "workflow_runs": [
                {"id": 999, "name": "bench-iteration go-net-http-iter1-12345"},
                {"id": 888, "name": "bench-iteration other-key"},
            ]
        }

        run_id = find_run_id("go-net-http-iter1-12345", "test-token")
        assert run_id == 999

    @patch("lib.orchestrator.time.sleep")
    @patch("lib.orchestrator.time.time")
    @patch("lib.orchestrator._gh_api")
    def test_returns_none_on_timeout(self, mock_api, mock_time, mock_sleep):
        mock_time.side_effect = [0, 200]  # past timeout
        mock_api.return_value = {"workflow_runs": []}

        run_id = find_run_id("go-net-http-iter1-12345", "test-token")
        assert run_id is None

    @patch("lib.orchestrator.time.sleep")
    @patch("lib.orchestrator.time.time")
    @patch("lib.orchestrator._gh_api")
    def test_finds_run_on_second_poll(self, mock_api, mock_time, mock_sleep):
        mock_time.side_effect = [0, 5, 10]  # within timeout
        mock_api.side_effect = [
            {"workflow_runs": []},
            {"workflow_runs": [{"id": 777, "name": "bench-iteration my-key"}]},
        ]

        run_id = find_run_id("my-key", "test-token")
        assert run_id == 777


class TestWaitForRuns:
    @patch("lib.orchestrator.time.sleep")
    @patch("lib.orchestrator.time.time")
    @patch("lib.orchestrator._gh_api")
    def test_all_runs_succeed(self, mock_api, mock_time, mock_sleep):
        mock_time.side_effect = [0, 10, 20]
        mock_api.side_effect = [
            {"status": "completed", "conclusion": "success"},
            {"status": "completed", "conclusion": "success"},
        ]

        conclusions = wait_for_runs({"key1": 100, "key2": 200}, "token", timeout=300)
        assert conclusions == {"key1": "success", "key2": "success"}

    @patch("lib.orchestrator.time.sleep")
    @patch("lib.orchestrator.time.time")
    @patch("lib.orchestrator._gh_api")
    def test_run_failure(self, mock_api, mock_time, mock_sleep):
        mock_time.side_effect = [0, 10]
        mock_api.side_effect = [
            {"status": "completed", "conclusion": "failure"},
        ]

        conclusions = wait_for_runs({"key1": 100}, "token", timeout=300)
        assert conclusions == {"key1": "failure"}

    @patch("lib.orchestrator.time.sleep")
    @patch("lib.orchestrator.time.time")
    @patch("lib.orchestrator._gh_api")
    def test_timeout_marks_pending_as_timed_out(self, mock_api, mock_time, mock_sleep):
        # First call: within timeout, run still in progress. Second call: past timeout.
        mock_time.side_effect = [0, 10, 500]
        mock_api.return_value = {"status": "in_progress"}

        conclusions = wait_for_runs({"key1": 100}, "token", timeout=300)
        assert conclusions == {"key1": "timed_out"}

    @patch("lib.orchestrator.time.sleep")
    @patch("lib.orchestrator.time.time")
    @patch("lib.orchestrator._gh_api")
    def test_mixed_success_and_timeout(self, mock_api, mock_time, mock_sleep):
        mock_time.side_effect = [0, 10, 20, 500]
        mock_api.side_effect = [
            {"status": "completed", "conclusion": "success"},
            {"status": "in_progress"},
            {"status": "in_progress"},
        ]

        conclusions = wait_for_runs(
            {"key1": 100, "key2": 200}, "token", timeout=300
        )
        assert conclusions["key1"] == "success"
        assert conclusions["key2"] == "timed_out"


class TestDownloadArtifact:
    @patch("subprocess.run")
    def test_successful_download(self, mock_run):
        mock_run.return_value = MagicMock(returncode=0)

        with tempfile.TemporaryDirectory() as tmpdir:
            result = download_artifact("my-key", tmpdir, "token")
            assert result is not None
            assert os.path.isdir(result)

        mock_run.assert_called_once()
        cmd = mock_run.call_args[0][0]
        assert "gh" in cmd
        assert "iteration-my-key" in cmd

    @patch("subprocess.run")
    def test_failed_download(self, mock_run):
        mock_run.return_value = MagicMock(returncode=1, stderr="not found")

        with tempfile.TemporaryDirectory() as tmpdir:
            result = download_artifact("my-key", tmpdir, "token")
            assert result is None


class TestCollectIterationResults:
    def test_collects_from_multiple_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            for i in range(1, 4):
                subdir = os.path.join(tmpdir, f"iteration-key-iter{i}")
                os.makedirs(subdir)
                data = {
                    "iteration": i,
                    "results": [
                        {"variant": "baseline", "iteration": i, "vegeta_results": []},
                        {"variant": "current_branch", "iteration": i, "vegeta_results": []},
                    ],
                }
                with open(os.path.join(subdir, f"iteration-{i}.json"), "w") as f:
                    json.dump(data, f)

            dirs = [os.path.join(tmpdir, f"iteration-key-iter{i}") for i in range(1, 4)]
            results = collect_iteration_results(dirs)
            assert len(results) == 3
            assert results[0]["iteration"] == 1

    def test_empty_dirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            subdir = os.path.join(tmpdir, "empty")
            os.makedirs(subdir)
            results = collect_iteration_results([subdir])
            assert results == []


class TestOrchestrate:
    @patch("lib.orchestrator.download_artifact")
    @patch("lib.orchestrator.wait_for_runs")
    @patch("lib.orchestrator.find_run_id")
    @patch("lib.orchestrator.dispatch_iteration")
    def test_full_orchestration(
        self, mock_dispatch, mock_find, mock_wait, mock_download
    ):
        mock_find.side_effect = [100, 200, 300]
        mock_wait.return_value = {
            "go-net-http-iter1-42": "success",
            "go-net-http-iter2-42": "success",
            "go-net-http-iter3-42": "success",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fake artifact dirs with iteration data
            for i in range(1, 4):
                artifact_dir = os.path.join(tmpdir, f"iteration-go-net-http-iter{i}-42")
                os.makedirs(artifact_dir)
                data = {
                    "iteration": i,
                    "results": [
                        {
                            "variant": "baseline",
                            "iteration": i,
                            "vegeta_results": [{"latency": 1000}] * 50,
                            "docker_stats": [],
                        },
                        {
                            "variant": "current_branch",
                            "iteration": i,
                            "vegeta_results": [{"latency": 1010}] * 50,
                            "docker_stats": [],
                        },
                    ],
                }
                with open(os.path.join(artifact_dir, f"iteration-{i}.json"), "w") as f:
                    json.dump(data, f)

            mock_download.side_effect = [
                os.path.join(tmpdir, f"iteration-go-net-http-iter{i}-42")
                for i in range(1, 4)
            ]

            results = orchestrate(
                app="go/net-http",
                sdk_version="0.30.0",
                latest_sdk_version=None,
                iterations=3,
                timeout=1800,
                output_dir=tmpdir,
                benchmarks_ref="main",
                token="test-token",
                caller_run_id="42",
            )

        assert results["app"] == "go/net-http"
        assert results["summary"] is not None
        assert results["orchestration"]["total_dispatched"] == 3
        assert results["orchestration"]["successful"] == 3
        assert mock_dispatch.call_count == 3

    @patch("lib.orchestrator.find_run_id")
    @patch("lib.orchestrator.dispatch_iteration")
    def test_fails_when_no_runs_found(self, mock_dispatch, mock_find):
        mock_find.return_value = None

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(RuntimeError, match="Failed to find any dispatched"):
                orchestrate(
                    app="go/net-http",
                    sdk_version="0.30.0",
                    latest_sdk_version=None,
                    iterations=3,
                    timeout=1800,
                    output_dir=tmpdir,
                    benchmarks_ref="main",
                    token="test-token",
                    caller_run_id="42",
                )

    @patch("lib.orchestrator.wait_for_runs")
    @patch("lib.orchestrator.find_run_id")
    @patch("lib.orchestrator.dispatch_iteration")
    def test_fails_when_too_few_succeed(self, mock_dispatch, mock_find, mock_wait):
        mock_find.side_effect = [100, 200, 300]
        mock_wait.return_value = {
            "go-net-http-iter1-42": "success",
            "go-net-http-iter2-42": "failure",
            "go-net-http-iter3-42": "timed_out",
        }

        with tempfile.TemporaryDirectory() as tmpdir:
            with pytest.raises(RuntimeError, match=f"Only 1 iterations succeeded"):
                orchestrate(
                    app="go/net-http",
                    sdk_version="0.30.0",
                    latest_sdk_version=None,
                    iterations=3,
                    timeout=1800,
                    output_dir=tmpdir,
                    benchmarks_ref="main",
                    token="test-token",
                    caller_run_id="42",
                )
