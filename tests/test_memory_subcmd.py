# tests/test_memory_subcmd.py
"""Tests for ``mco memory`` subcommand (agent-stats, priors, status)."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock, patch

from runtime.bridge.evermemos_client import EverMemosClient
from runtime.cli import build_parser, main
from runtime.memory_cli import show_agent_stats, show_priors, show_status


class TestShowAgentStats(unittest.TestCase):
    """Tests for show_agent_stats()."""

    def test_renders_agent_scores(self):
        """show_agent_stats formats scores as readable table."""
        score1 = {
            "agent": "claude",
            "repo": "my-repo",
            "task_category": "security",
            "cross_validated_count": 5,
            "cross_validated_rate": 0.75,
            "finding_eval_count": 10,
            "last_updated": "2026-03-01T00:00:00+00:00",
        }
        score2 = {
            "agent": "codex",
            "repo": "my-repo",
            "task_category": "bugs",
            "cross_validated_count": 3,
            "cross_validated_rate": 0.60,
            "finding_eval_count": 5,
            "last_updated": "2026-03-02T00:00:00+00:00",
        }

        entries = [
            {"content": EverMemosClient.serialize_agent_score(score1)},
            {"content": EverMemosClient.serialize_agent_score(score2)},
            {"content": "some other memory"},
        ]

        client = MagicMock()
        client.fetch_history.return_value = entries

        result = show_agent_stats(client, "coding:my-repo--agents")

        self.assertIn("claude", result)
        self.assertIn("codex", result)
        self.assertIn("security", result)
        self.assertIn("bugs", result)
        self.assertIn("0.75", result)
        self.assertIn("0.60", result)
        self.assertIn("Agent", result)
        self.assertIn("Cross-Validated Rate", result)

    def test_empty_scores(self):
        """No scores -> informative message."""
        client = MagicMock()
        client.fetch_history.return_value = []

        result = show_agent_stats(client, "coding:empty--agents")

        self.assertIn("No agent scores found", result)
        self.assertIn("coding:empty--agents", result)


class TestShowStatus(unittest.TestCase):
    """Tests for show_status()."""

    def test_shows_space_info(self):
        """show_status lists space existence and counts."""
        findings_entry = {"content": EverMemosClient.serialize_finding({"title": "test"})}
        agent_entry = {"content": EverMemosClient.serialize_agent_score({
            "agent": "claude", "repo": "r", "task_category": "c",
        })}

        client = MagicMock()
        client.list_spaces.return_value = [
            "coding:my-repo--findings",
            "coding:my-repo--agents",
        ]

        def _fetch_history(space, memory_type="episodic_memory", limit=100):
            if space == "coding:my-repo--findings":
                return [findings_entry]
            if space == "coding:my-repo--agents":
                return [agent_entry]
            return []

        client.fetch_history.side_effect = _fetch_history
        client.briefing.return_value = None

        result = show_status(client, "my-repo")

        self.assertIn("my-repo", result)
        self.assertIn("Findings: 1", result)
        self.assertIn("Agent Scores: 1", result)
        self.assertIn("exists", result)
        self.assertIn("not found", result)  # context space not in list

    def test_no_spaces_exist(self):
        """show_status handles missing spaces gracefully."""
        client = MagicMock()
        client.list_spaces.return_value = []

        result = show_status(client, "empty-repo")

        self.assertIn("Findings: 0", result)
        self.assertIn("Agent Scores: 0", result)
        self.assertIn("not found", result)


class TestShowPriors(unittest.TestCase):
    """Tests for show_priors()."""

    @patch("runtime.bridge.stack_detector.detect_stack", return_value="python")
    @patch("runtime.bridge.core._load_agent_rates")
    def test_renders_priors_table(self, mock_load_rates, mock_detect):
        """show_priors computes blended weights and displays table."""
        def _load_rates(client, space):
            if "agents" in space:
                return {"claude": 0.8, "codex": 0.6}
            if "stacks" in space:
                return {"claude": 0.7, "codex": 0.5}
            if "global" in space:
                return {"claude": 0.6, "codex": 0.4}
            return {}

        mock_load_rates.side_effect = _load_rates

        client = MagicMock()
        # For run_count: return 5 agent score entries
        client.fetch_history.return_value = [
            {"content": EverMemosClient.serialize_agent_score({"agent": "a", "repo": "r", "task_category": "c"})}
            for _ in range(5)
        ]

        result = show_priors(client, "/tmp/repo", "my-repo", "security")

        self.assertIn("claude", result)
        self.assertIn("codex", result)
        self.assertIn("Stack: python", result)
        self.assertIn("Category: security", result)
        self.assertIn("Blended Weight", result)


class TestMemoryCLIParsing(unittest.TestCase):
    """Tests for memory subcommand CLI parsing."""

    def test_memory_agent_stats_accepted(self):
        """mco memory agent-stats --repo . parses correctly."""
        parser = build_parser()
        args = parser.parse_args(["memory", "agent-stats", "--repo", "."])
        self.assertEqual(args.command, "memory")
        self.assertEqual(args.memory_action, "agent-stats")
        self.assertEqual(args.repo, ".")

    def test_memory_agent_stats_with_space(self):
        """mco memory agent-stats --repo . --space my-repo parses correctly."""
        parser = build_parser()
        args = parser.parse_args(["memory", "agent-stats", "--repo", ".", "--space", "my-repo"])
        self.assertEqual(args.space, "my-repo")

    def test_memory_agent_stats_with_json(self):
        """mco memory agent-stats --repo . --json parses correctly."""
        parser = build_parser()
        args = parser.parse_args(["memory", "agent-stats", "--repo", ".", "--json"])
        self.assertTrue(args.json)

    def test_memory_priors_accepted(self):
        """mco memory priors --repo . --category security parses correctly."""
        parser = build_parser()
        args = parser.parse_args(["memory", "priors", "--repo", ".", "--category", "security"])
        self.assertEqual(args.command, "memory")
        self.assertEqual(args.memory_action, "priors")
        self.assertEqual(args.category, "security")

    def test_memory_status_accepted(self):
        """mco memory status --repo . parses correctly."""
        parser = build_parser()
        args = parser.parse_args(["memory", "status", "--repo", "."])
        self.assertEqual(args.command, "memory")
        self.assertEqual(args.memory_action, "status")

    def test_memory_requires_action(self):
        """mco memory without a sub-action raises SystemExit."""
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["memory"])

    @patch.dict("os.environ", {"EVERMEMOS_API_KEY": ""}, clear=False)
    def test_memory_missing_api_key_returns_2(self):
        """mco memory agent-stats without EVERMEMOS_API_KEY returns exit code 2."""
        exit_code = main(["memory", "agent-stats", "--repo", "."])
        self.assertEqual(exit_code, 2)


if __name__ == "__main__":
    unittest.main()
