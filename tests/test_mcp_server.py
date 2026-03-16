"""Tests for MCP server tool handlers."""
from __future__ import annotations

import os
import unittest
from unittest.mock import patch, MagicMock

from runtime.mcp_server import (
    _ok, _err, _is_git_repo, _validate_repo,
    _sync_doctor, _sync_review, _sync_run,
    _sync_findings_list, _sync_memory_status,
)


class TestEnvelope(unittest.TestCase):
    def test_ok_envelope(self) -> None:
        result = _ok({"key": "value"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["key"], "value")

    def test_ok_with_list(self) -> None:
        result = _ok([1, 2, 3])
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], [1, 2, 3])

    def test_err_envelope(self) -> None:
        result = _err("bad_input", "Something went wrong")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "bad_input")
        self.assertEqual(result["error"]["message"], "Something went wrong")


class TestValidation(unittest.TestCase):
    def test_is_git_repo_on_real_repo(self) -> None:
        # Current working directory is the mco repo
        import os
        self.assertTrue(_is_git_repo(os.getcwd()))

    def test_is_git_repo_on_tmp(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            self.assertFalse(_is_git_repo(tmp))

    def test_validate_repo_nonexistent(self) -> None:
        result = _validate_repo("/nonexistent/xyz")
        self.assertIsNotNone(result)
        self.assertEqual(result["error"]["code"], "invalid_repo")

    def test_validate_repo_not_git(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            result = _validate_repo(tmp, require_git=True)
            self.assertIsNotNone(result)
            self.assertIn("Not a git repository", result["error"]["message"])

    def test_validate_repo_ok(self) -> None:
        result = _validate_repo(".", require_git=False)
        self.assertIsNone(result)


class TestSyncDoctor(unittest.TestCase):
    @patch("runtime.cli._doctor_provider_presence")
    def test_returns_provider_status(self, mock_presence) -> None:
        mock_presence.return_value = {
            "claude": MagicMock(
                provider="claude", detected=True, auth_ok=True,
                version="1.0", binary_path="/usr/bin/claude",
            ),
        }
        result = _sync_doctor("claude")
        self.assertTrue(result["ok"])
        providers = result["data"]["providers"]
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["name"], "claude")
        self.assertTrue(providers[0]["detected"])

    def test_invalid_provider_returns_error(self) -> None:
        result = _sync_doctor("nonexistent")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_providers")

    @patch("runtime.cli._doctor_provider_presence")
    def test_empty_providers_checks_all(self, mock_presence) -> None:
        mock_presence.return_value = {}
        result = _sync_doctor(None)
        self.assertTrue(result["ok"])
        called_providers = mock_presence.call_args[0][0]
        self.assertTrue(len(called_providers) >= 5)


class TestSyncReview(unittest.TestCase):
    @patch("runtime.review_engine.run_review")
    def test_returns_findings_envelope(self, mock_run) -> None:
        mock_result = MagicMock()
        mock_result.task_id = "test-123"
        mock_result.decision = "PASS"
        mock_result.terminal_state = "completed"
        mock_result.findings_count = 1
        mock_result.findings = [{"title": "Bug", "severity": "high"}]
        mock_run.return_value = mock_result

        result = _sync_review(
            repo=".",
            prompt="Review for bugs",
            providers="claude,codex",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["decision"], "PASS")
        self.assertEqual(result["data"]["findings_count"], 1)
        self.assertEqual(len(result["data"]["findings"]), 1)

    def test_invalid_repo(self) -> None:
        result = _sync_review(
            repo="/nonexistent/path/xyz_does_not_exist",
            prompt="Review",
            providers="claude",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_repo")

    def test_invalid_providers(self) -> None:
        result = _sync_review(
            repo=".",
            prompt="Review",
            providers="fake_provider_xyz",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_providers")

    def test_diff_mode_on_non_git_dir(self) -> None:
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            result = _sync_review(
                repo=tmp,
                prompt="Review",
                providers="claude",
                diff_mode="staged",
            )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_repo")
        self.assertIn("Not a git repository", result["error"]["message"])


class TestSyncRun(unittest.TestCase):
    @patch("runtime.review_engine.run_review")
    def test_returns_final_text_only(self, mock_run) -> None:
        mock_result = MagicMock()
        mock_result.task_id = "run-123"
        mock_result.decision = "PASS"
        mock_result.terminal_state = "completed"
        mock_result.provider_results = {
            "claude": {"success": True, "final_text": "Summary...", "output_text": "Very long..."},
        }
        mock_run.return_value = mock_result

        result = _sync_run(repo=".", prompt="Summarize", providers="claude")
        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual(data["task_id"], "run-123")
        self.assertIn("final_text", data["provider_results"]["claude"])
        self.assertNotIn("output_text", data["provider_results"]["claude"])


class TestSyncFindingsList(unittest.TestCase):
    @patch("runtime.bridge.evermemos_client.EverMemosClient")
    @patch("runtime.bridge.space.infer_space_slug", return_value="my-repo")
    def test_returns_findings(self, mock_slug, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.fetch_history.return_value = []
        with patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):
            result = _sync_findings_list(repo=".")
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["data"], list)

    def test_missing_api_key(self) -> None:
        env = dict(os.environ)
        env.pop("EVERMEMOS_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = _sync_findings_list(repo=".")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "missing_api_key")


class TestSyncMemoryStatus(unittest.TestCase):
    @patch("runtime.memory_cli.get_status_data")
    @patch("runtime.bridge.evermemos_client.EverMemosClient")
    @patch("runtime.bridge.space.infer_space_slug", return_value="my-repo")
    def test_returns_status(self, mock_slug, mock_client_cls, mock_status) -> None:
        mock_status.return_value = {
            "space_slug": "my-repo",
            "findings_count": 5,
            "agent_scores_count": 3,
            "briefing_preview": "Hello",
        }
        with patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):
            result = _sync_memory_status(repo=".")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["findings_count"], 5)

    def test_missing_api_key(self) -> None:
        env = dict(os.environ)
        env.pop("EVERMEMOS_API_KEY", None)
        with patch.dict(os.environ, env, clear=True):
            result = _sync_memory_status(repo=".")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "missing_api_key")
