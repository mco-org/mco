from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from runtime.cli import main


class DryRunTests(unittest.TestCase):
    def test_run_dry_run_json_does_not_execute_agents(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with patch("runtime.cli.run_review") as mock_run_review:
                with contextlib.redirect_stdout(stdout_buf):
                    exit_code = main([
                        "run",
                        "--repo", tmp,
                        "--prompt", "Summarize this repo.",
                        "--providers", "codex,pi",
                        "--provider-models-json", '{"pi":{"provider":"seal","model":"deepseek-v4-pro"}}',
                        "--provider-context-json", '{"pi":{"skills":"disabled","context_files":false}}',
                        "--dry-run",
                        "--json",
                    ])

        self.assertEqual(exit_code, 0)
        mock_run_review.assert_not_called()
        payload = json.loads(stdout_buf.getvalue())
        self.assertTrue(payload["dry_run"])
        self.assertFalse(payload["would_execute"])
        self.assertEqual(payload["providers"], ["codex", "pi"])
        self.assertEqual(payload["providers_detail"]["codex"]["risk"]["level"], "workspace_write")
        self.assertEqual(payload["providers_detail"]["pi"]["risk"]["level"], "read_only")
        pi_policy = payload["providers_detail"]["pi"]["policy"]
        self.assertEqual(pi_policy["applied_model"], {"provider": "seal", "model": "deepseek-v4-pro"})
        self.assertEqual(pi_policy["applied_context"], {"skills": "disabled", "context_files": False})
        pi_command = payload["providers_detail"]["pi"]["command_template"]
        self.assertIn("--tools", pi_command)
        self.assertIn("read,grep,find,ls", pi_command)
        self.assertIn("--model", pi_command)
        self.assertIn("deepseek-v4-pro", pi_command)

    def test_dry_run_reports_strict_policy_failure_without_execution(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with patch("runtime.cli.run_review") as mock_run_review:
                with contextlib.redirect_stdout(stdout_buf):
                    exit_code = main([
                        "run",
                        "--repo", tmp,
                        "--prompt", "Check policy.",
                        "--providers", "hermes",
                        "--provider-context-json", '{"hermes":{"skills":["gh"],"context_files":false}}',
                        "--dry-run",
                        "--json",
                    ])

        self.assertEqual(exit_code, 0)
        mock_run_review.assert_not_called()
        payload = json.loads(stdout_buf.getvalue())
        policy = payload["providers_detail"]["hermes"]["policy"]
        self.assertTrue(policy["would_fail_strict"])
        self.assertEqual(policy["failure_reason"], "context_policy_enforcement_failed")
        self.assertEqual(policy["incompatible_context_keys"], ["context_files", "skills"])

    def test_dry_run_human_report(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with patch("runtime.cli.run_review") as mock_run_review:
                with contextlib.redirect_stdout(stdout_buf):
                    exit_code = main([
                        "review",
                        "--repo", tmp,
                        "--prompt", "Review for bugs.",
                        "--providers", "pi",
                        "--dry-run",
                    ])

        self.assertEqual(exit_code, 0)
        mock_run_review.assert_not_called()
        output = stdout_buf.getvalue()
        self.assertIn("Dry Run", output)
        self.assertIn("would_execute: False", output)
        self.assertIn("pi: risk=read_only", output)


if __name__ == "__main__":
    unittest.main()
