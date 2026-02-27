from __future__ import annotations

import io
import json
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from runtime.cli import main
from runtime.review_engine import ReviewResult


class CliOutputFormatsTests(unittest.TestCase):
    def test_review_markdown_pr_format_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-review-format-1",
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
                        "category": "bug",
                        "title": "Possible nil dereference",
                        "recommendation": "Guard against None before access",
                        "confidence": 0.91,
                        "evidence": {"file": "runtime/x.py", "line": 42, "snippet": "x.y"},
                    }
                ],
            )
            output = io.StringIO()
            with patch("runtime.cli.run_review", return_value=result):
                with redirect_stdout(output):
                    exit_code = main(
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
                        ]
                    )
        report = output.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("## MCO Review Summary", report)
        self.assertIn("| Severity | Category | Title | Location | Confidence | Recommendation |", report)
        self.assertIn("Possible nil dereference", report)
        self.assertIn("runtime/x.py:42", report)

    def test_run_rejects_markdown_pr_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "run",
                        "--repo",
                        tmpdir,
                        "--prompt",
                        "run",
                        "--providers",
                        "codex",
                        "--format",
                        "markdown-pr",
                    ]
                )
        self.assertEqual(exit_code, 2)
        self.assertIn("supported only for review", stderr.getvalue())

    def test_review_sarif_format_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            result = ReviewResult(
                task_id="task-review-format-2",
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
                        "severity": "critical",
                        "category": "security",
                        "title": "Hardcoded credential",
                        "recommendation": "Read from env var",
                        "confidence": 0.95,
                        "evidence": {"file": "runtime/x.py", "line": 7, "snippet": "API_KEY='x'"},
                        "detected_by": ["claude", "qwen"],
                    }
                ],
            )
            output = io.StringIO()
            with patch("runtime.cli.run_review", return_value=result):
                with redirect_stdout(output):
                    exit_code = main(
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
                        ]
                    )
        payload = json.loads(output.getvalue())
        self.assertEqual(exit_code, 0)
        self.assertEqual(payload.get("version"), "2.1.0")
        runs = payload.get("runs", [])
        self.assertEqual(len(runs), 1)
        self.assertGreaterEqual(len(runs[0].get("results", [])), 1)

    def test_run_rejects_sarif_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            stderr = io.StringIO()
            with redirect_stderr(stderr):
                exit_code = main(
                    [
                        "run",
                        "--repo",
                        tmpdir,
                        "--prompt",
                        "run",
                        "--providers",
                        "codex",
                        "--format",
                        "sarif",
                    ]
                )
        self.assertEqual(exit_code, 2)
        self.assertIn("supported only for review", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()
