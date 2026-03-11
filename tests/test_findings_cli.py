# tests/test_findings_cli.py
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from runtime.bridge.evermemos_client import EverMemosClient
from runtime.findings_cli import confirm_finding, list_findings, render_findings_table


def _make_finding(
    title: str = "SQL Injection",
    severity: str = "high",
    status: str = "open",
    file_path: str = "app/db.py",
    category: str = "security",
    finding_hash: str = "sha256:aabbccdd11223344",
) -> dict:
    return {
        "finding_hash": finding_hash,
        "category": category,
        "severity": severity,
        "title": title,
        "description": "Use parameterized queries.",
        "file": file_path,
        "line": 42,
        "detected_by": ["claude"],
        "occurrence_count": 1,
        "status": status,
    }


def _serialize(finding: dict) -> str:
    return EverMemosClient.serialize_finding(finding)


def _history_from_findings(findings: list) -> list:
    return [{"content": _serialize(f)} for f in findings]


class TestListFindings(unittest.TestCase):
    def test_list_open_findings(self):
        """list_findings filters by status."""
        open_f = _make_finding(title="Open Bug", status="open", finding_hash="sha256:1111")
        accepted_f = _make_finding(title="Accepted Risk", status="accepted", finding_hash="sha256:2222")

        client = MagicMock()
        client.fetch_history.return_value = _history_from_findings([open_f, accepted_f])

        result = list_findings(client, "coding:test--findings", status_filter="open")
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["title"], "Open Bug")
        self.assertEqual(result[0]["status"], "open")

    def test_list_all_findings(self):
        """status_filter=None returns all findings."""
        open_f = _make_finding(title="Bug A", status="open", finding_hash="sha256:1111")
        accepted_f = _make_finding(title="Bug B", status="accepted", finding_hash="sha256:2222")
        rejected_f = _make_finding(title="Bug C", status="rejected", finding_hash="sha256:3333")

        client = MagicMock()
        client.fetch_history.return_value = _history_from_findings([open_f, accepted_f, rejected_f])

        result = list_findings(client, "coding:test--findings", status_filter=None)
        self.assertEqual(len(result), 3)

    def test_list_skips_non_finding_entries(self):
        """Non-finding entries in history are ignored."""
        finding = _make_finding()
        client = MagicMock()
        client.fetch_history.return_value = [
            {"content": _serialize(finding)},
            {"content": "plain text note"},
            {"content": "[MCO-AGENT-SCORE] {}"},
        ]

        result = list_findings(client, "coding:test--findings")
        self.assertEqual(len(result), 1)


class TestConfirmFinding(unittest.TestCase):
    def test_confirm_accepted(self):
        """confirm_finding updates status to accepted."""
        finding = _make_finding(finding_hash="sha256:target123")

        client = MagicMock()
        client.fetch_history.return_value = _history_from_findings([finding])
        client.remember.return_value = {"request_id": "r1"}

        ok = confirm_finding(client, "coding:test--findings", "sha256:target123", "accepted")
        self.assertTrue(ok)

        # Verify remember was called with updated status
        call_args = client.remember.call_args
        self.assertIn("accepted", call_args.kwargs.get("content", call_args[1].get("content", "")))

    def test_confirm_hash_not_found(self):
        """confirm_finding returns False if hash not in history."""
        finding = _make_finding(finding_hash="sha256:other")

        client = MagicMock()
        client.fetch_history.return_value = _history_from_findings([finding])

        ok = confirm_finding(client, "coding:test--findings", "sha256:nonexistent", "rejected")
        self.assertFalse(ok)
        client.remember.assert_not_called()

    def test_confirm_wontfix(self):
        """confirm_finding supports wontfix status."""
        finding = _make_finding(finding_hash="sha256:wf1")

        client = MagicMock()
        client.fetch_history.return_value = _history_from_findings([finding])
        client.remember.return_value = {"request_id": "r2"}

        ok = confirm_finding(client, "coding:test--findings", "sha256:wf1", "wontfix")
        self.assertTrue(ok)
        client.remember.assert_called_once()


class TestRenderTable(unittest.TestCase):
    def test_render_table_format(self):
        """render_findings_table produces readable output."""
        findings = [
            _make_finding(
                title="SQL Injection",
                severity="high",
                status="open",
                file_path="app/db.py",
                finding_hash="sha256:aabbccdd11223344",
            ),
            _make_finding(
                title="XSS in template",
                severity="medium",
                status="accepted",
                file_path="templates/index.html",
                finding_hash="sha256:eeff0011223344",
            ),
        ]

        table = render_findings_table(findings)
        lines = table.split("\n")

        # Header + separator + 2 data rows
        self.assertEqual(len(lines), 4)

        # Header contains column names
        self.assertIn("Hash", lines[0])
        self.assertIn("Status", lines[0])
        self.assertIn("Severity", lines[0])
        self.assertIn("Title", lines[0])
        self.assertIn("File", lines[0])

        # Data rows contain expected values
        self.assertIn("aabbccdd1122", lines[2])
        self.assertIn("open", lines[2])
        self.assertIn("SQL Injection", lines[2])

        self.assertIn("accepted", lines[3])
        self.assertIn("XSS in template", lines[3])

    def test_render_empty_table(self):
        """render_findings_table handles empty list."""
        table = render_findings_table([])
        lines = table.split("\n")
        # Header + separator only
        self.assertEqual(len(lines), 2)

    def test_render_long_title_truncated(self):
        """Titles longer than 38 chars are truncated."""
        finding = _make_finding(title="A" * 50)
        table = render_findings_table([finding])
        # Truncated title should appear with "..."
        self.assertIn("...", table)


class TestFindingsCLIParsing(unittest.TestCase):
    def test_findings_list_subcommand_accepted(self):
        """mco findings list --repo . is valid."""
        from runtime.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["findings", "list", "--repo", "."])
        self.assertEqual(args.command, "findings")
        self.assertEqual(args.findings_action, "list")
        self.assertEqual(args.repo, ".")

    def test_findings_list_with_status(self):
        """mco findings list --repo . --status open is valid."""
        from runtime.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["findings", "list", "--repo", ".", "--status", "open"])
        self.assertEqual(args.status, "open")

    def test_findings_list_with_json(self):
        """mco findings list --repo . --json is valid."""
        from runtime.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["findings", "list", "--repo", ".", "--json"])
        self.assertTrue(args.json)

    def test_findings_list_with_space(self):
        """mco findings list --repo . --space my-slug is valid."""
        from runtime.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["findings", "list", "--repo", ".", "--space", "my-slug"])
        self.assertEqual(args.space, "my-slug")

    def test_findings_confirm_subcommand_accepted(self):
        """mco findings confirm HASH --status accepted is valid."""
        from runtime.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["findings", "confirm", "sha256:abc123", "--status", "accepted"])
        self.assertEqual(args.command, "findings")
        self.assertEqual(args.findings_action, "confirm")
        self.assertEqual(args.hash, "sha256:abc123")
        self.assertEqual(args.status, "accepted")

    def test_findings_confirm_rejected(self):
        """mco findings confirm HASH --status rejected is valid."""
        from runtime.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["findings", "confirm", "sha256:abc123", "--status", "rejected"])
        self.assertEqual(args.status, "rejected")

    def test_findings_confirm_wontfix(self):
        """mco findings confirm HASH --status wontfix is valid."""
        from runtime.cli import build_parser

        parser = build_parser()
        args = parser.parse_args(["findings", "confirm", "sha256:abc123", "--status", "wontfix"])
        self.assertEqual(args.status, "wontfix")


if __name__ == "__main__":
    unittest.main()
