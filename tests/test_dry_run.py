from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from unittest.mock import patch

from runtime.cli import main
from runtime.review_engine import REVIEW_FINDINGS_SCHEMA_PATH


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

    def test_dry_run_codex_review_includes_output_schema_when_exists(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with patch("runtime.cli.run_review") as mock_run_review:
                with contextlib.redirect_stdout(stdout_buf):
                    exit_code = main([
                        "review",
                        "--repo", tmp,
                        "--prompt", "Review for bugs.",
                        "--providers", "codex",
                        "--dry-run",
                        "--json",
                    ])

        self.assertEqual(exit_code, 0)
        mock_run_review.assert_not_called()
        payload = json.loads(stdout_buf.getvalue())
        codex_command = payload["providers_detail"]["codex"]["command_template"]
        self.assertIn("--output-schema", codex_command)
        schema_index = codex_command.index("--output-schema") + 1
        self.assertEqual(codex_command[schema_index], str(REVIEW_FINDINGS_SCHEMA_PATH))

    def test_dry_run_empty_provider_context_reaches_command_template(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with patch("runtime.cli.run_review") as mock_run_review:
                with contextlib.redirect_stdout(stdout_buf):
                    exit_code = main([
                        "run",
                        "--repo", tmp,
                        "--prompt", "Summarize this repo.",
                        "--providers", "claude,codex",
                        "--provider-context-json", '{"claude":{},"codex":{}}',
                        "--dry-run",
                        "--json",
                    ])

        self.assertEqual(exit_code, 0)
        mock_run_review.assert_not_called()
        payload = json.loads(stdout_buf.getvalue())
        claude_command = payload["providers_detail"]["claude"]["command_template"]
        codex_command = payload["providers_detail"]["codex"]["command_template"]
        self.assertIn("--safe-mode", claude_command)
        self.assertIn("--ignore-user-config", codex_command)
        self.assertIn("--ignore-rules", codex_command)

    def test_copilot_dry_run_exposes_approval_bypass_command(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with patch("runtime.cli.run_review") as mock_run_review:
                with contextlib.redirect_stdout(stdout_buf):
                    exit_code = main([
                        "run",
                        "--repo", tmp,
                        "--prompt", "Summarize this repo.",
                        "--providers", "copilot",
                        "--dry-run",
                        "--json",
                    ])

        self.assertEqual(exit_code, 0)
        mock_run_review.assert_not_called()
        detail = json.loads(stdout_buf.getvalue())["providers_detail"]["copilot"]
        self.assertEqual(detail["default_risk"]["level"], "approval_bypass")
        self.assertEqual(detail["risk"]["level"], "approval_bypass")
        self.assertIn("--allow-all-tools", detail["command_template"])
        self.assertIn("--no-ask-user", detail["command_template"])

    def test_dry_run_reports_effective_risk_after_permission_override(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with contextlib.redirect_stdout(stdout_buf):
                exit_code = main([
                    "run",
                    "--repo", tmp,
                    "--prompt", "Summarize this repo.",
                    "--providers", "claude,codex",
                    "--provider-permissions-json",
                    '{"claude":{"permission_mode":"acceptEdits"},"codex":{"sandbox":"read-only"}}',
                    "--dry-run",
                    "--json",
                ])

        self.assertEqual(exit_code, 0)
        details = json.loads(stdout_buf.getvalue())["providers_detail"]
        self.assertEqual(details["claude"]["default_risk"]["level"], "read_only")
        self.assertEqual(details["claude"]["risk"]["level"], "workspace_write")
        self.assertEqual(details["codex"]["default_risk"]["level"], "workspace_write")
        self.assertEqual(details["codex"]["risk"]["level"], "read_only")

    def test_acp_dry_run_marks_implicit_permissions_unknown(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with contextlib.redirect_stdout(stdout_buf):
                exit_code = main([
                    "run",
                    "--repo", tmp,
                    "--prompt", "Summarize this repo.",
                    "--providers", "claude",
                    "--transport", "acp",
                    "--dry-run",
                    "--json",
                ])

        self.assertEqual(exit_code, 0)
        detail = json.loads(stdout_buf.getvalue())["providers_detail"]["claude"]
        self.assertEqual(detail["risk"]["level"], "unknown")
        self.assertTrue(detail["policy"]["would_fail_strict"])
        self.assertEqual(detail["policy"]["failure_reason"], "risk_classification_unknown")
        self.assertEqual(detail["command_template"], ["claude", "code", "--transport", "stdio"])

    def test_acp_dry_run_applies_explicit_read_only_permission(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with contextlib.redirect_stdout(stdout_buf):
                exit_code = main([
                    "run",
                    "--repo", tmp,
                    "--prompt", "Summarize this repo.",
                    "--providers", "claude",
                    "--transport", "acp",
                    "--provider-permissions-json", '{"claude":{"permission_mode":"plan"}}',
                    "--dry-run",
                    "--json",
                ])

        self.assertEqual(exit_code, 0)
        detail = json.loads(stdout_buf.getvalue())["providers_detail"]["claude"]
        self.assertEqual(detail["risk"]["level"], "read_only")
        self.assertFalse(detail["policy"]["would_fail_strict"])
        self.assertEqual(
            detail["command_template"],
            ["claude", "code", "--transport", "stdio", "--permission-mode", "plan"],
        )

    def test_acp_strict_execution_rejects_unknown_risk_before_dispatch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            with patch("runtime.cli.run_review") as mock_run_review:
                with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                    exit_code = main([
                        "run",
                        "--repo", tmp,
                        "--prompt", "Summarize this repo.",
                        "--providers", "claude",
                        "--transport", "acp",
                        "--json",
                    ])

        self.assertEqual(exit_code, 2)
        mock_run_review.assert_not_called()
        self.assertEqual(stderr_buf.getvalue(), "")
        error = json.loads(stdout_buf.getvalue())["error"]
        self.assertEqual(error["subtype"], "invalid_config")
        self.assertIn("risk_classification_unknown", error["message"])

    def test_dry_run_command_build_failure_is_explicit(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            with patch(
                "runtime.adapters.copilot.CopilotAdapter._build_command",
                side_effect=ValueError("unsupported preview configuration"),
            ), patch("runtime.cli.run_review") as mock_run_review:
                with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
                    exit_code = main([
                        "run",
                        "--repo", tmp,
                        "--prompt", "Summarize this repo.",
                        "--providers", "copilot",
                        "--dry-run",
                        "--json",
                    ])

        self.assertEqual(exit_code, 2)
        mock_run_review.assert_not_called()
        self.assertEqual(stderr_buf.getvalue(), "")
        error = json.loads(stdout_buf.getvalue())["error"]
        self.assertEqual(error["subtype"], "runtime_error")
        self.assertIn("unsupported preview configuration", error["message"])


if __name__ == "__main__":
    unittest.main()
