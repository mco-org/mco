"""Tests for update_stack_aggregate() — tech-stack-level score aggregation."""
from __future__ import annotations

import json
import unittest
from unittest.mock import MagicMock

from runtime.bridge.evermemos_client import EverMemosClient
from runtime.bridge.scoring import AgentScore, merge_agent_score, update_stack_aggregate


def _make_score_entry(score: AgentScore) -> dict:
    """Build a fake fetch_history item wrapping a serialized AgentScore."""
    return {"content": EverMemosClient.serialize_agent_score(score.to_dict())}


class TestUpdateStackAggregate(unittest.TestCase):
    """Tests for update_stack_aggregate()."""

    def test_first_write_to_empty_stack(self):
        """First run for a stack: scores written directly."""
        client = MagicMock()
        client.fetch_history.return_value = []  # no existing scores

        score_a = AgentScore(
            agent="claude",
            repo="repo1",
            task_category="security",
            cross_validated_count=2,
            finding_eval_count=3,
            cross_validated_rate=2 / 3,
            unique_passive_confirmed=1,
        )
        new_scores = {("claude", "security"): score_a}

        update_stack_aggregate(client, "coding:stacks--python", new_scores)

        # Should have called fetch_history once and remember once
        client.fetch_history.assert_called_once_with(
            space="coding:stacks--python",
            memory_type="episodic_memory",
            limit=100,
        )
        client.remember.assert_called_once()

        # Verify remembered content deserializes to the same score
        call_args = client.remember.call_args
        self.assertEqual(call_args.kwargs.get("space") or call_args[1].get("space", call_args[0][0] if call_args[0] else None),
                         "coding:stacks--python")
        remembered_content = call_args.kwargs.get("content") or call_args[1].get("content", call_args[0][1] if len(call_args[0]) > 1 else None)
        self.assertTrue(EverMemosClient.is_agent_score_entry(remembered_content))
        restored = AgentScore.from_dict(
            EverMemosClient.deserialize_agent_score(remembered_content)
        )
        self.assertEqual(restored.agent, "claude")
        self.assertEqual(restored.task_category, "security")
        self.assertEqual(restored.cross_validated_count, 2)
        self.assertEqual(restored.finding_eval_count, 3)
        self.assertEqual(restored.unique_passive_confirmed, 1)

    def test_merge_with_existing(self):
        """Existing stack scores are merged, not overwritten."""
        existing = AgentScore(
            agent="claude",
            repo="repo1",
            task_category="security",
            cross_validated_count=3,
            finding_eval_count=5,
            cross_validated_rate=3 / 5,
            unique_passive_confirmed=1,
            unique_passive_pending=1,
            unique_rejected=0,
        )

        client = MagicMock()
        client.fetch_history.return_value = [_make_score_entry(existing)]

        new_score = AgentScore(
            agent="claude",
            repo="repo2",
            task_category="security",
            cross_validated_count=2,
            finding_eval_count=4,
            cross_validated_rate=2 / 4,
            unique_passive_confirmed=0,
            unique_passive_pending=2,
            unique_rejected=1,
        )
        new_scores = {("claude", "security"): new_score}

        update_stack_aggregate(client, "coding:stacks--python", new_scores)

        # Verify the written score is merged, not replaced
        client.remember.assert_called_once()
        remembered_content = client.remember.call_args.kwargs.get("content")
        if remembered_content is None:
            args, kwargs = client.remember.call_args
            remembered_content = kwargs.get("content", args[1] if len(args) > 1 else None)

        restored = AgentScore.from_dict(
            EverMemosClient.deserialize_agent_score(remembered_content)
        )
        # Merged counts: 3+2=5 cv, 5+4=9 eval
        self.assertEqual(restored.cross_validated_count, 5)
        self.assertEqual(restored.finding_eval_count, 9)
        self.assertAlmostEqual(restored.cross_validated_rate, 5 / 9)
        self.assertEqual(restored.unique_passive_confirmed, 1)
        self.assertEqual(restored.unique_passive_pending, 3)
        self.assertEqual(restored.unique_rejected, 1)

    def test_multiple_agents_tracked(self):
        """Multiple agents' scores stored independently."""
        client = MagicMock()
        client.fetch_history.return_value = []

        score_claude = AgentScore(
            agent="claude",
            repo="repo1",
            task_category="security",
            cross_validated_count=2,
            finding_eval_count=3,
            cross_validated_rate=2 / 3,
        )
        score_gemini = AgentScore(
            agent="gemini",
            repo="repo1",
            task_category="security",
            cross_validated_count=1,
            finding_eval_count=2,
            cross_validated_rate=1 / 2,
        )
        new_scores = {
            ("claude", "security"): score_claude,
            ("gemini", "security"): score_gemini,
        }

        update_stack_aggregate(client, "coding:stacks--python", new_scores)

        # Should write two separate scores
        self.assertEqual(client.remember.call_count, 2)

        # Collect the remembered scores
        remembered_agents = set()
        for call in client.remember.call_args_list:
            content = call.kwargs.get("content")
            if content is None:
                args, kwargs = call
                content = kwargs.get("content", args[1] if len(args) > 1 else None)
            score_dict = EverMemosClient.deserialize_agent_score(content)
            remembered_agents.add(score_dict["agent"])

        self.assertEqual(remembered_agents, {"claude", "gemini"})

    def test_fetch_history_failure_treated_as_empty(self):
        """If fetch_history raises, treat as empty (cold start)."""
        client = MagicMock()
        client.fetch_history.side_effect = Exception("connection refused")

        score = AgentScore(
            agent="claude",
            repo="repo1",
            task_category="security",
            cross_validated_count=1,
            finding_eval_count=1,
            cross_validated_rate=1.0,
        )
        new_scores = {("claude", "security"): score}

        # Should not raise
        update_stack_aggregate(client, "coding:stacks--python", new_scores)

        # Score should still be written
        client.remember.assert_called_once()

    def test_non_score_entries_ignored(self):
        """Non-score entries in history are ignored during merge."""
        client = MagicMock()
        client.fetch_history.return_value = [
            {"content": "[MCO-FINDING] {\"some\": \"finding\"}"},
            {"content": "plain text note"},
        ]

        score = AgentScore(
            agent="claude",
            repo="repo1",
            task_category="security",
            cross_validated_count=1,
            finding_eval_count=2,
            cross_validated_rate=0.5,
        )
        new_scores = {("claude", "security"): score}

        update_stack_aggregate(client, "coding:stacks--python", new_scores)

        # No existing score matched, so new score written directly
        client.remember.assert_called_once()
        remembered_content = client.remember.call_args.kwargs.get("content")
        if remembered_content is None:
            args, kwargs = client.remember.call_args
            remembered_content = kwargs.get("content", args[1] if len(args) > 1 else None)
        restored = AgentScore.from_dict(
            EverMemosClient.deserialize_agent_score(remembered_content)
        )
        self.assertEqual(restored.cross_validated_count, 1)
        self.assertEqual(restored.finding_eval_count, 2)


if __name__ == "__main__":
    unittest.main()
