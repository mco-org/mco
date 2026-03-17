# tests/test_consensus_display.py
"""Tests for consensus badge display in findings output."""
from __future__ import annotations

import unittest

from runtime.formatters import _consensus_badge, format_markdown_pr


class TestConsensusBadge(unittest.TestCase):
    def test_all_agree(self) -> None:
        badge = _consensus_badge(["claude", "codex", "gemini"], 3)
        self.assertEqual(badge, "[3/3 agree]")

    def test_two_of_three(self) -> None:
        badge = _consensus_badge(["claude", "codex"], 3)
        self.assertEqual(badge, "[2/3 agree]")

    def test_one_agent_only(self) -> None:
        badge = _consensus_badge(["claude"], 3)
        self.assertEqual(badge, "[1 agent only]")

    def test_single_provider_no_badge(self) -> None:
        badge = _consensus_badge(["claude"], 1)
        self.assertEqual(badge, "")

    def test_empty_detected_by(self) -> None:
        badge = _consensus_badge([], 3)
        self.assertEqual(badge, "")

    def test_not_a_list(self) -> None:
        badge = _consensus_badge("claude", 3)  # type: ignore
        self.assertEqual(badge, "")


class TestMarkdownPrConsensus(unittest.TestCase):
    def test_consensus_column_shown_with_multiple_providers(self) -> None:
        payload = {
            "decision": "FAIL",
            "terminal_state": "COMPLETED",
            "provider_success_count": 3,
            "provider_failure_count": 0,
            "findings_count": 2,
        }
        findings = [
            {
                "severity": "high",
                "category": "security",
                "title": "SQL injection",
                "recommendation": "Use parameterized queries",
                "confidence": 0.9,
                "detected_by": ["claude", "codex"],
                "evidence": {"file": "db.py", "line": 42},
            },
            {
                "severity": "medium",
                "category": "performance",
                "title": "N+1 query",
                "recommendation": "Use batch fetch",
                "confidence": 0.5,
                "detected_by": ["gemini"],
                "evidence": {"file": "api.py", "line": 10},
            },
        ]
        text = format_markdown_pr(payload, findings, total_providers=3)
        self.assertIn("Consensus", text)
        self.assertIn("[2/3 agree]", text)
        self.assertIn("[1 agent only]", text)

    def test_no_consensus_column_with_single_provider(self) -> None:
        payload = {
            "decision": "PASS",
            "terminal_state": "COMPLETED",
            "provider_success_count": 1,
            "provider_failure_count": 0,
            "findings_count": 1,
        }
        findings = [
            {
                "severity": "low",
                "category": "style",
                "title": "Long line",
                "recommendation": "Break line",
                "confidence": 0.6,
                "detected_by": ["claude"],
                "evidence": {"file": "x.py", "line": 1},
            },
        ]
        text = format_markdown_pr(payload, findings, total_providers=1)
        self.assertNotIn("Consensus", text)
        self.assertNotIn("[1 agent only]", text)

    def test_backward_compatible_without_total_providers(self) -> None:
        """Calling without total_providers should still work."""
        payload = {
            "decision": "PASS",
            "terminal_state": "COMPLETED",
            "provider_success_count": 1,
            "provider_failure_count": 0,
            "findings_count": 0,
        }
        text = format_markdown_pr(payload, [])
        self.assertIn("_No findings reported._", text)


class TestChainModeConsensusBadge(unittest.TestCase):
    def test_chain_mode_uses_confirmed_language(self) -> None:
        badge = _consensus_badge(["claude", "codex"], 3, chain_mode=True)
        self.assertEqual(badge, "[confirmed by 2/3]")

    def test_chain_mode_unconfirmed(self) -> None:
        badge = _consensus_badge(["claude"], 3, chain_mode=True)
        self.assertEqual(badge, "[unconfirmed]")

    def test_parallel_mode_uses_agree_language(self) -> None:
        badge = _consensus_badge(["claude", "codex"], 3, chain_mode=False)
        self.assertEqual(badge, "[2/3 agree]")

    def test_chain_mode_in_markdown_pr(self) -> None:
        payload = {
            "decision": "FAIL",
            "terminal_state": "COMPLETED",
            "provider_success_count": 2,
            "provider_failure_count": 0,
            "findings_count": 1,
        }
        findings = [
            {
                "severity": "high",
                "category": "security",
                "title": "SQL injection",
                "recommendation": "Fix",
                "confidence": 0.9,
                "detected_by": ["claude", "codex"],
                "evidence": {"file": "db.py", "line": 42},
            },
        ]
        text = format_markdown_pr(payload, findings, total_providers=2, chain_mode=True)
        self.assertIn("[confirmed by 2/2]", text)
        self.assertNotIn("[2/2 agree]", text)
