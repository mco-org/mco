from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from runtime.cli import main
from runtime.review_engine import ReviewResult


EXPECTED_JSON_KEYS = (
    "command",
    "task_id",
    "artifact_root",
    "decision",
    "terminal_state",
    "provider_success_count",
    "provider_failure_count",
    "findings_count",
    "parse_success_count",
    "parse_failure_count",
    "schema_valid_count",
    "dropped_findings_count",
    "findings",
)
EXPECTED_DETAILED_JSON_KEYS = EXPECTED_JSON_KEYS + (
    "result_mode",
    "provider_results",
)


class CliJsonContractTests(unittest.TestCase):
    def test_missing_provider_selection_returns_clarification_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout_buf = io.StringIO()
            stderr_buf = io.StringIO()
            with patch("runtime.cli.run_review") as mock_run_review:
                with redirect_stdout(stdout_buf), redirect_stderr(stderr_buf):
                    exit_code = main([
                        "run", "--repo", tmpdir, "--prompt", "Summarize this repo.", "--json",
                    ])

        self.assertEqual(exit_code, 2)
        mock_run_review.assert_not_called()
        self.assertEqual(stderr_buf.getvalue(), "")
        error = json.loads(stdout_buf.getvalue())["error"]
        self.assertEqual(error["category"], "input")
        self.assertEqual(error["subtype"], "provider_selection_required")
        self.assertIn("Ask the user", error["message"])
        self.assertIn("grok", error["message"])
        self.assertIn("cursor", error["message"])

    def _invoke_json(self, argv: list[str], result: ReviewResult) -> tuple[int, dict]:
        output = io.StringIO()
        with patch("runtime.cli.run_review", return_value=result):
            with redirect_stdout(output):
                exit_code = main(argv)
        payload = json.loads(output.getvalue())
        return exit_code, payload

    def test_review_json_contract_is_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-review-1",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"codex": {"success": True}},
                findings_count=3,
                parse_success_count=1,
                parse_failure_count=0,
                schema_valid_count=3,
                dropped_findings_count=0,
            )
            exit_code, payload = self._invoke_json(
                ["review", "--repo", tmpdir, "--prompt", "review", "--providers", "codex", "--json"],
                result,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["command"], "review")
            self.assertEqual(tuple(payload.keys()), EXPECTED_DETAILED_JSON_KEYS)
            self.assertEqual(payload["result_mode"], "stdout")
            self.assertIsNone(payload["artifact_root"])
            self.assertEqual(payload["findings"], [])
            self.assertIsInstance(payload["provider_success_count"], int)
            self.assertIsInstance(payload["provider_failure_count"], int)

    def test_run_json_contract_is_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-run-1",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"codex": {"success": True}},
                findings_count=0,
                parse_success_count=0,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
            )
            exit_code, payload = self._invoke_json(
                ["run", "--repo", tmpdir, "--prompt", "run", "--providers", "codex", "--json"],
                result,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["command"], "run")
            self.assertEqual(tuple(payload.keys()), EXPECTED_DETAILED_JSON_KEYS)
            self.assertEqual(payload["result_mode"], "stdout")
            self.assertIsNone(payload["artifact_root"])
            self.assertEqual(payload["findings"], [])
            self.assertEqual(payload["parse_success_count"], 0)
            self.assertEqual(payload["parse_failure_count"], 0)

    def test_artifact_mode_json_contract_is_frozen(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-run-artifact-1",
                artifact_root=f"{tmpdir}/reports/review/task-run-artifact-1",
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"codex": {"success": True}},
                findings_count=0,
                parse_success_count=0,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
            )
            exit_code, payload = self._invoke_json(
                [
                    "run",
                    "--repo",
                    tmpdir,
                    "--prompt",
                    "run",
                    "--providers",
                    "codex",
                    "--result-mode",
                    "artifact",
                    "--json",
                ],
                result,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(tuple(payload.keys()), EXPECTED_JSON_KEYS)
            self.assertEqual(payload["findings"], [])

    def test_stdout_mode_json_includes_provider_results(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-run-stdout-1",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"codex": {"success": True, "output_text": "full output"}},
                findings_count=0,
                parse_success_count=0,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
            )
            exit_code, payload = self._invoke_json(
                [
                    "run",
                    "--repo",
                    tmpdir,
                    "--prompt",
                    "run",
                    "--providers",
                    "codex",
                    "--result-mode",
                    "stdout",
                    "--json",
                ],
                result,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["command"], "run")
            self.assertEqual(payload["result_mode"], "stdout")
            self.assertIsNone(payload["artifact_root"])
            self.assertIn("provider_results", payload)
            self.assertIn("codex", payload["provider_results"])
            self.assertEqual(payload["provider_results"]["codex"]["output_text"], "full output")

    def test_stdout_mode_calls_engine_without_artifact_writes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-run-stdout-2",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"codex": {"success": True}},
                findings_count=0,
                parse_success_count=0,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
            )
            with patch("runtime.cli.run_review", return_value=result) as mocked:
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = main(
                        [
                            "run",
                            "--repo",
                            tmpdir,
                            "--prompt",
                            "run",
                            "--providers",
                            "codex",
                            "--result-mode",
                            "stdout",
                            "--json",
                        ]
                    )
            self.assertEqual(exit_code, 0)
            self.assertEqual(mocked.call_args.kwargs.get("write_artifacts"), False)

    def test_save_artifacts_promotes_stdout_mode_to_both(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-run-stdout-3",
                artifact_root=f"{tmpdir}/reports/review/task-run-stdout-3",
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"codex": {"success": True}},
                findings_count=0,
                parse_success_count=0,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
            )
            with patch("runtime.cli.run_review", return_value=result) as mocked:
                output = io.StringIO()
                with redirect_stdout(output):
                    exit_code = main(
                        [
                            "run",
                            "--repo",
                            tmpdir,
                            "--prompt",
                            "run",
                            "--providers",
                            "codex",
                            "--save-artifacts",
                            "--json",
                        ]
                    )
            payload = json.loads(output.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertEqual(mocked.call_args.kwargs.get("write_artifacts"), True)
            self.assertEqual(payload.get("result_mode"), "both")

    def test_json_output_ignores_human_format_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-review-json-format-1",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"codex": {"success": True}},
                findings_count=0,
                parse_success_count=0,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
            )
            exit_code, payload = self._invoke_json(
                [
                    "review",
                    "--repo",
                    tmpdir,
                    "--prompt",
                    "review",
                    "--providers",
                    "codex",
                    "--format",
                    "markdown-pr",
                    "--json",
                ],
                result,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["command"], "review")
            self.assertEqual(tuple(payload.keys()), EXPECTED_DETAILED_JSON_KEYS)

    def test_json_output_ignores_sarif_format_flag(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-review-json-format-2",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"codex": {"success": True}},
                findings_count=0,
                parse_success_count=0,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
            )
            exit_code, payload = self._invoke_json(
                [
                    "review",
                    "--repo",
                    tmpdir,
                    "--prompt",
                    "review",
                    "--providers",
                    "codex",
                    "--format",
                    "sarif",
                    "--json",
                ],
                result,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["command"], "review")
            self.assertEqual(tuple(payload.keys()), EXPECTED_DETAILED_JSON_KEYS)

    def test_json_output_includes_token_usage_summary_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-review-json-usage-1",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={
                    "codex": {
                        "success": True,
                        "token_usage": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
                        "token_usage_completeness": "full",
                    }
                },
                findings_count=0,
                parse_success_count=0,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
                token_usage_summary={
                    "providers_with_usage": 1,
                    "provider_count": 1,
                    "completeness": "full",
                    "totals": {"prompt_tokens": 10, "completion_tokens": 4, "total_tokens": 14},
                },
            )
            exit_code, payload = self._invoke_json(
                [
                    "run",
                    "--repo",
                    tmpdir,
                    "--prompt",
                    "run",
                    "--providers",
                    "codex",
                    "--include-token-usage",
                    "--json",
                ],
                result,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["token_usage_summary"]["completeness"], "full")
            self.assertEqual(payload["token_usage_summary"]["totals"]["total_tokens"], 14)

    def test_json_output_includes_synthesis_when_enabled(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-run-synthesis-1",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"codex": {"success": True}},
                findings_count=0,
                parse_success_count=0,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
                synthesis={
                    "provider": "codex",
                    "success": True,
                    "reason": "ok",
                    "text": "## Consensus\nAligned.",
                },
            )
            exit_code, payload = self._invoke_json(
                [
                    "run",
                    "--repo",
                    tmpdir,
                    "--prompt",
                    "run",
                    "--providers",
                    "codex",
                    "--synthesize",
                    "--json",
                ],
                result,
            )
            self.assertEqual(exit_code, 0)
            self.assertIn("synthesis", payload)
            self.assertEqual(payload["synthesis"]["provider"], "codex")
            self.assertEqual(payload["synthesis"]["success"], True)

    def test_json_output_includes_division_strategy_and_provider_scopes(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-review-divide-1",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={
                    "codex": {
                        "success": True,
                        "assigned_scope": {"mode": "files", "paths": ["src/a.py"]},
                    }
                },
                findings_count=0,
                parse_success_count=0,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
                division_strategy="files",
            )
            exit_code, payload = self._invoke_json(
                [
                    "review",
                    "--repo",
                    tmpdir,
                    "--prompt",
                    "review",
                    "--providers",
                    "codex",
                    "--json",
                ],
                result,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["division_strategy"], "files")
            self.assertEqual(payload["provider_scopes"]["codex"]["paths"], ["src/a.py"])

    def test_json_output_includes_consensus_fields_and_debate_round(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-review-consensus-1",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"codex": {"success": True}},
                findings_count=1,
                parse_success_count=1,
                parse_failure_count=0,
                schema_valid_count=1,
                dropped_findings_count=0,
                findings=[
                    {
                        "severity": "high",
                        "category": "security",
                        "title": "SQL injection",
                        "recommendation": "Use parameters",
                        "confidence": 0.8,
                        "consensus_score": 0.8,
                        "consensus_level": "confirmed",
                        "detected_by": ["claude", "codex"],
                        "evidence": {"file": "db.py", "line": 42, "snippet": "query"},
                    }
                ],
                debate_round={
                    "enabled": True,
                    "provider_order": ["claude", "codex"],
                    "providers": {
                        "codex": {
                            "reviewed_count": 1,
                            "votes": [
                                {
                                    "finding_key": "fp-1",
                                    "title": "SQL injection",
                                    "location": "db.py:42",
                                    "reported_by": ["claude"],
                                    "verdict": "AGREE",
                                    "reason": "Confirmed",
                                }
                            ],
                            "success": True,
                            "final_error": None,
                        }
                    },
                    "findings": [
                        {
                            "finding_key": "fp-1",
                            "title": "SQL injection",
                            "location": "db.py:42",
                            "reported_by": ["claude"],
                            "consensus_score_before": 0.4,
                            "consensus_level_before": "needs-verification",
                            "consensus_score_after": 0.8,
                            "consensus_level_after": "confirmed",
                            "votes": [{"provider": "codex", "verdict": "AGREE", "reason": "Confirmed"}],
                            "vote_summary": {"agree": 1, "disagree": 0, "refine": 0},
                        }
                    ],
                },
                division_strategy="dimensions",
            )
            exit_code, payload = self._invoke_json(
                [
                    "review",
                    "--repo",
                    tmpdir,
                    "--prompt",
                    "review",
                    "--providers",
                    "codex",
                    "--json",
                ],
                result,
            )
            self.assertEqual(exit_code, 0)
            self.assertEqual(payload["division_strategy"], "dimensions")
            self.assertEqual(payload["findings"][0]["consensus_score"], 0.8)
            self.assertEqual(payload["findings"][0]["consensus_level"], "confirmed")
            self.assertEqual(payload["debate_round"]["findings"][0]["vote_summary"]["agree"], 1)

    def test_invalid_synth_provider_is_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main(
                    [
                        "run",
                        "--repo",
                        tmpdir,
                        "--prompt",
                        "run",
                        "--providers",
                        "codex",
                        "--synth-provider",
                        "claude",
                        "--json",
                    ]
                )
            self.assertEqual(exit_code, 2)
            self.assertEqual(stderr.getvalue(), "")
            payload = json.loads(stdout.getvalue())
            self.assertFalse(payload["ok"])
            self.assertEqual(
                tuple(payload["error"].keys()),
                ("category", "subtype", "message", "hint", "provider", "retryable", "exit_code"),
            )
            self.assertEqual(payload["error"]["category"], "configuration")
            self.assertEqual(payload["error"]["subtype"], "invalid_config")
            self.assertEqual(payload["error"]["exit_code"], 2)
            self.assertIn("--synth-provider must be one of selected providers", payload["error"]["message"])

    def test_argparse_failure_is_json_when_json_requested(self) -> None:
        stdout = io.StringIO()
        stderr = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            exit_code = main(["run", "--json", "--transport", "invalid"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertFalse(payload["ok"])
        self.assertEqual(payload["error"]["category"], "input")
        self.assertEqual(payload["error"]["subtype"], "parse_error")
        self.assertFalse(payload["error"]["retryable"])
        self.assertTrue(payload["error"]["hint"])

    def test_mixed_known_and_unknown_providers_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with redirect_stdout(stdout), redirect_stderr(stderr):
                exit_code = main([
                    "run",
                    "--repo", tmpdir,
                    "--prompt", "run",
                    "--providers", "codex,unknown-provider",
                    "--json",
                ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(stderr.getvalue(), "")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["error"]["subtype"], "invalid_providers")
        self.assertIn("unknown-provider", payload["error"]["message"])

    def test_provider_failure_categories_remain_machine_readable(self) -> None:
        failures = (
            {"reason": "provider_unavailable", "presence_reason": "auth_check_failed"},
            {"final_error": "retryable_timeout", "cancel_reason": "stall_timeout"},
            {"final_error": "normalization_error", "parse_reason": "invalid_json"},
            {"reason": "permission_enforcement_failed", "unknown_permission_keys": ["sandbox"]},
        )
        with tempfile.TemporaryDirectory() as tmpdir:
            for provider_result in failures:
                with self.subTest(provider_result=provider_result):
                    result = ReviewResult(
                        task_id="task-failed",
                        artifact_root=None,
                        decision="FAIL",
                        terminal_state="FAILED",
                        provider_results={"codex": {"success": False, **provider_result}},
                        findings_count=0,
                        parse_success_count=0,
                        parse_failure_count=1,
                        schema_valid_count=0,
                        dropped_findings_count=0,
                    )
                    exit_code, payload = self._invoke_json(
                        ["run", "--repo", tmpdir, "--prompt", "run", "--providers", "codex", "--json"],
                        result,
                    )
                    self.assertEqual(exit_code, 2)
                    self.assertEqual(payload["provider_results"]["codex"], {"success": False, **provider_result})


if __name__ == "__main__":
    unittest.main()
