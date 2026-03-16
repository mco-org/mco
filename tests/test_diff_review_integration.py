"""Integration tests for diff-only review in the engine layer."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from runtime.config import ReviewPolicy
from runtime.review_engine import ReviewRequest, ReviewResult, run_review, _tag_diff_scope

_DEFAULT_POLICY = ReviewPolicy()


class TestEmptyDiffReturnsNoOp(unittest.TestCase):
    @patch("runtime.diff_utils.diff_files", return_value=[])
    @patch("runtime.diff_utils.detect_main_branch", return_value="main")
    def test_empty_diff_no_providers_invoked(self, mock_detect, mock_files) -> None:
        req = ReviewRequest(
            repo_root="/tmp/fake",
            prompt="Review",
            providers=["claude"],
            artifact_base="/tmp/artifacts",
            policy=_DEFAULT_POLICY,
            diff_mode="branch",
        )
        with patch("runtime.review_engine._run_provider") as mock_run:
            result = run_review(req, review_mode=True, write_artifacts=False)
            mock_run.assert_not_called()
        self.assertEqual(result.decision, "PASS")
        self.assertEqual(result.terminal_state, "completed")
        self.assertEqual(result.findings_count, 0)
        self.assertEqual(result.provider_results, {})


class TestDiffScopeInteraction(unittest.TestCase):
    @patch("runtime.diff_utils.diff_content", return_value="fake diff")
    @patch("runtime.diff_utils.diff_files", return_value=["src/a.py", "src/b.py", "docs/readme.md"])
    @patch("runtime.diff_utils.detect_main_branch", return_value="main")
    def test_target_paths_intersects_with_diff(self, mock_detect, mock_files, mock_content) -> None:
        """When user passes --target-paths src, only src/* diff files are kept."""
        req = ReviewRequest(
            repo_root="/tmp/fake",
            prompt="Review",
            providers=["claude"],
            artifact_base="/tmp/artifacts",
            policy=_DEFAULT_POLICY,
            target_paths=["src"],
            diff_mode="branch",
        )
        with patch("runtime.review_engine._run_provider") as mock_run:
            mock_run.return_value = MagicMock(
                provider="claude", success=True, parse_ok=True,
                schema_valid_count=0, dropped_count=0,
                findings=[], provider_result={"success": True},
            )
            result = run_review(req, review_mode=True, write_artifacts=False)
        mock_run.assert_called_once()

    @patch("runtime.diff_utils.diff_files", return_value=["docs/readme.md"])
    @patch("runtime.diff_utils.detect_main_branch", return_value="main")
    def test_empty_intersection_returns_no_op(self, mock_detect, mock_files) -> None:
        """target-paths=src but only docs changed -> empty intersection -> no-op."""
        req = ReviewRequest(
            repo_root="/tmp/fake",
            prompt="Review",
            providers=["claude"],
            artifact_base="/tmp/artifacts",
            policy=_DEFAULT_POLICY,
            target_paths=["src"],
            diff_mode="branch",
        )
        with patch("runtime.review_engine._run_provider") as mock_run:
            result = run_review(req, review_mode=True, write_artifacts=False)
            mock_run.assert_not_called()
        self.assertEqual(result.decision, "PASS")


class TestDiffScopeTagging(unittest.TestCase):
    def test_in_diff_tagged(self) -> None:
        findings = [
            {"title": "Bug", "evidence": {"file": "src/a.py", "line": 10}},
            {"title": "Perf", "evidence": {"file": "lib/b.py", "line": 5}},
            {"title": "Style", "evidence": {}},
        ]
        diff_file_set = {"src/a.py"}
        result = _tag_diff_scope(findings, diff_file_set)
        self.assertEqual(result[0]["diff_scope"], "in_diff")
        self.assertEqual(result[1]["diff_scope"], "related")
        self.assertEqual(result[2]["diff_scope"], "unknown")

    def test_no_diff_set_returns_untagged(self) -> None:
        findings = [{"title": "Bug", "evidence": {"file": "a.py"}}]
        result = _tag_diff_scope(findings, None)
        self.assertNotIn("diff_scope", result[0])

    def test_no_evidence_tagged_unknown(self) -> None:
        findings = [{"title": "Bug"}]
        result = _tag_diff_scope(findings, {"a.py"})
        self.assertEqual(result[0]["diff_scope"], "unknown")


# ── SARIF diff_scope ──

from runtime.formatters import format_sarif


class TestSarifDiffScope(unittest.TestCase):
    def test_diff_scope_in_sarif_properties(self) -> None:
        payload = {"decision": "PASS", "terminal_state": "completed", "findings_count": 1}
        findings = [{
            "title": "Bug",
            "severity": "high",
            "category": "security",
            "evidence": {"file": "a.py", "line": 1, "snippet": "x"},
            "confidence": 0.8,
            "recommendation": "fix it",
            "diff_scope": "in_diff",
        }]
        sarif = format_sarif(payload, findings)
        result_props = sarif["runs"][0]["results"][0]["properties"]
        self.assertEqual(result_props["diff_scope"], "in_diff")

    def test_no_diff_scope_omitted(self) -> None:
        payload = {"decision": "PASS", "terminal_state": "completed", "findings_count": 1}
        findings = [{
            "title": "Bug",
            "severity": "high",
            "category": "security",
            "evidence": {"file": "a.py", "line": 1, "snippet": "x"},
            "confidence": 0.8,
            "recommendation": "fix it",
        }]
        sarif = format_sarif(payload, findings)
        result_props = sarif["runs"][0]["results"][0]["properties"]
        self.assertNotIn("diff_scope", result_props)


# ── Report diff_scope grouping ──

from runtime.cli import _render_user_readable_report


class TestReportDiffScope(unittest.TestCase):
    def test_report_groups_by_diff_scope(self) -> None:
        payload = {
            "task_id": "test",
            "decision": "PASS",
            "terminal_state": "completed",
            "provider_success_count": 1,
            "provider_failure_count": 0,
            "findings_count": 2,
            "parse_success_count": 1,
            "parse_failure_count": 0,
            "schema_valid_count": 2,
            "artifact_root": None,
        }
        findings = [
            {"title": "In diff bug", "severity": "high", "diff_scope": "in_diff",
             "category": "security", "evidence": {"file": "a.py", "line": 1}},
            {"title": "Related issue", "severity": "medium", "diff_scope": "related",
             "category": "performance", "evidence": {"file": "b.py", "line": 5}},
        ]
        report = _render_user_readable_report("review", "stdout", ["claude"], payload, {}, findings)
        self.assertIn("In Diff", report)
        self.assertIn("Related", report)
        self.assertIn("In diff bug", report)

    def test_report_no_diff_scope_skips_section(self) -> None:
        payload = {
            "task_id": "test",
            "decision": "PASS",
            "terminal_state": "completed",
            "provider_success_count": 1,
            "provider_failure_count": 0,
            "findings_count": 0,
            "parse_success_count": 1,
            "parse_failure_count": 0,
            "schema_valid_count": 0,
            "artifact_root": None,
        }
        report = _render_user_readable_report("review", "stdout", ["claude"], payload, {}, [])
        self.assertNotIn("In Diff", report)
