"""Tests for data layer functions used by MCP server."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from runtime.bridge.evermemos_client import EverMemosClient
from runtime.memory_cli import get_status_data


class TestGetStatusData(unittest.TestCase):
    def test_returns_structured_dict(self) -> None:
        client = MagicMock()
        client.list_spaces.return_value = [
            "coding:my-repo--findings",
            "coding:my-repo--agents",
            "coding:my-repo--context",
        ]
        client.fetch_history.side_effect = [
            # findings space
            [
                {"content": EverMemosClient.serialize_finding({"finding_hash": "sha256:aaa", "status": "open", "title": "A"})},
                {"content": EverMemosClient.serialize_finding({"finding_hash": "sha256:bbb", "status": "fixed", "title": "B"})},
            ],
            # agents space
            [
                {"content": EverMemosClient.serialize_agent_score({"agent": "claude", "task_category": "security"})},
            ],
        ]
        client.briefing.return_value = "Project uses Python and FastAPI."

        result = get_status_data(client, "my-repo")

        self.assertEqual(result["space_slug"], "my-repo")
        self.assertEqual(result["findings_count"], 2)
        self.assertEqual(result["agent_scores_count"], 1)
        self.assertIn("Python", result["briefing_preview"])

    def test_empty_spaces(self) -> None:
        client = MagicMock()
        client.list_spaces.return_value = []
        client.briefing.return_value = None

        result = get_status_data(client, "empty-repo")

        self.assertEqual(result["findings_count"], 0)
        self.assertEqual(result["agent_scores_count"], 0)
        self.assertEqual(result["briefing_preview"], "")

    def test_briefing_truncated_to_200(self) -> None:
        client = MagicMock()
        client.list_spaces.return_value = ["coding:repo--context"]
        client.briefing.return_value = "A" * 500

        result = get_status_data(client, "repo")

        self.assertEqual(len(result["briefing_preview"]), 200)
