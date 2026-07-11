from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from runtime.mcp_server import _sync_review, _sync_run


class McpInvocationTests(unittest.TestCase):
    def test_run_returns_operational_raw_output(self) -> None:
        expected = {
            "stage": "run",
            "task_id": "run-1",
            "status": "complete",
            "outputs": [{"status": "success", "output": "raw answer"}],
            "exit_code": 0,
            "artifact_root": None,
        }
        with tempfile.TemporaryDirectory() as repo, patch("runtime.invocation_runtime.run_invocation_workflow", return_value=expected):
            result = _sync_run(repo, "task", "pi")

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], expected)

    def test_review_uses_read_only_execution_and_raw_output(self) -> None:
        expected = {
            "stage": "run",
            "task_id": "run-1",
            "status": "complete",
            "outputs": [{"status": "success", "output": "review answer"}],
            "exit_code": 0,
            "artifact_root": None,
        }
        with tempfile.TemporaryDirectory() as repo, patch("runtime.invocation_runtime.run_invocation_workflow", return_value=expected):
            result = _sync_review(repo, "review", "pi")

        self.assertTrue(result["ok"])
        self.assertNotIn("findings", result["data"])


if __name__ == "__main__":
    unittest.main()
