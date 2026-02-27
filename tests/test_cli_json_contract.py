from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stdout
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
)
EXPECTED_DETAILED_JSON_KEYS = EXPECTED_JSON_KEYS + (
    "result_mode",
    "provider_results",
)


class CliJsonContractTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
