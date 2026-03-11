from __future__ import annotations

import unittest

from runtime.bridge.scoring import AgentScore, merge_agent_score, update_scores_from_findings


class TestScoring(unittest.TestCase):
    """Tests for agent reliability scoring with cross-validation tracking."""

    def test_default_score(self):
        """New AgentScore has zeroed counts."""
        score = AgentScore(agent="claude", repo="myrepo", task_category="security")
        self.assertEqual(score.cross_validated_count, 0)
        self.assertEqual(score.cross_validated_rate, 0.0)
        self.assertEqual(score.unique_passive_confirmed, 0)
        self.assertEqual(score.unique_passive_pending, 0)
        self.assertEqual(score.unique_rejected, 0)
        self.assertEqual(score.finding_eval_count, 0)
        self.assertEqual(score.last_updated, "")

    def test_cross_validation_counted(self):
        """Finding detected by 2+ agents increments cross_validated for each."""
        findings = [
            {
                "detected_by": ["claude", "gemini"],
                "category": "security",
                "status": "open",
            },
        ]
        scores = update_scores_from_findings(
            findings=findings,
            repo="myrepo",
            task_category="security",
            existing_scores={},
        )
        claude_score = scores[("claude", "security")]
        gemini_score = scores[("gemini", "security")]

        self.assertEqual(claude_score.cross_validated_count, 1)
        self.assertEqual(claude_score.finding_eval_count, 1)
        self.assertEqual(gemini_score.cross_validated_count, 1)
        self.assertEqual(gemini_score.finding_eval_count, 1)

    def test_unique_finding_pending(self):
        """Finding by 1 agent with open status -> unique_passive_pending."""
        findings = [
            {
                "detected_by": ["claude"],
                "category": "bug",
                "status": "open",
            },
        ]
        scores = update_scores_from_findings(
            findings=findings,
            repo="myrepo",
            task_category="bug",
            existing_scores={},
        )
        score = scores[("claude", "bug")]
        self.assertEqual(score.unique_passive_pending, 1)
        self.assertEqual(score.unique_passive_confirmed, 0)
        self.assertEqual(score.unique_rejected, 0)

    def test_unique_finding_confirmed(self):
        """Finding by 1 agent with fixed status -> unique_passive_confirmed."""
        findings = [
            {
                "detected_by": ["gemini"],
                "category": "perf",
                "status": "fixed",
            },
        ]
        scores = update_scores_from_findings(
            findings=findings,
            repo="myrepo",
            task_category="perf",
            existing_scores={},
        )
        score = scores[("gemini", "perf")]
        self.assertEqual(score.unique_passive_confirmed, 1)
        self.assertEqual(score.unique_passive_pending, 0)
        self.assertEqual(score.unique_rejected, 0)

    def test_unique_finding_rejected(self):
        """Finding by 1 agent with rejected status -> unique_rejected."""
        findings = [
            {
                "detected_by": ["codex"],
                "category": "style",
                "status": "rejected",
            },
        ]
        scores = update_scores_from_findings(
            findings=findings,
            repo="myrepo",
            task_category="style",
            existing_scores={},
        )
        score = scores[("codex", "style")]
        self.assertEqual(score.unique_rejected, 1)
        self.assertEqual(score.unique_passive_confirmed, 0)
        self.assertEqual(score.unique_passive_pending, 0)

    def test_cross_validated_rate_computed(self):
        """Rate equals cross_validated_count / finding_eval_count."""
        findings = [
            {
                "detected_by": ["claude", "gemini"],
                "category": "security",
                "status": "open",
            },
            {
                "detected_by": ["claude"],
                "category": "security",
                "status": "open",
            },
            {
                "detected_by": ["claude", "codex"],
                "category": "security",
                "status": "open",
            },
        ]
        scores = update_scores_from_findings(
            findings=findings,
            repo="myrepo",
            task_category="security",
            existing_scores={},
        )
        claude_score = scores[("claude", "security")]
        # claude evaluated 3 findings, 2 cross-validated
        self.assertEqual(claude_score.finding_eval_count, 3)
        self.assertEqual(claude_score.cross_validated_count, 2)
        self.assertAlmostEqual(claude_score.cross_validated_rate, 2 / 3)

    def test_merge_accumulates(self):
        """Merging two scores adds counts and recomputes rate."""
        old = AgentScore(
            agent="claude",
            repo="myrepo",
            task_category="security",
            cross_validated_count=3,
            finding_eval_count=5,
            unique_passive_confirmed=1,
            unique_passive_pending=2,
            unique_rejected=0,
            cross_validated_rate=3 / 5,
        )
        new = AgentScore(
            agent="claude",
            repo="myrepo",
            task_category="security",
            cross_validated_count=2,
            finding_eval_count=4,
            unique_passive_confirmed=0,
            unique_passive_pending=1,
            unique_rejected=1,
            cross_validated_rate=2 / 4,
        )
        merged = merge_agent_score(old, new)
        self.assertEqual(merged.cross_validated_count, 5)
        self.assertEqual(merged.finding_eval_count, 9)
        self.assertEqual(merged.unique_passive_confirmed, 1)
        self.assertEqual(merged.unique_passive_pending, 3)
        self.assertEqual(merged.unique_rejected, 1)
        self.assertAlmostEqual(merged.cross_validated_rate, 5 / 9)

    def test_to_dict_from_dict_roundtrip(self):
        """Serialize/deserialize preserves data."""
        score = AgentScore(
            agent="claude",
            repo="myrepo",
            task_category="security",
            cross_validated_count=7,
            cross_validated_rate=0.7,
            unique_passive_confirmed=2,
            unique_passive_pending=1,
            unique_rejected=3,
            finding_eval_count=10,
            last_updated="2026-03-11T00:00:00+00:00",
        )
        d = score.to_dict()
        restored = AgentScore.from_dict(d)
        self.assertEqual(restored.agent, score.agent)
        self.assertEqual(restored.repo, score.repo)
        self.assertEqual(restored.task_category, score.task_category)
        self.assertEqual(restored.cross_validated_count, score.cross_validated_count)
        self.assertAlmostEqual(restored.cross_validated_rate, score.cross_validated_rate)
        self.assertEqual(restored.unique_passive_confirmed, score.unique_passive_confirmed)
        self.assertEqual(restored.unique_passive_pending, score.unique_passive_pending)
        self.assertEqual(restored.unique_rejected, score.unique_rejected)
        self.assertEqual(restored.finding_eval_count, score.finding_eval_count)
        self.assertEqual(restored.last_updated, score.last_updated)


if __name__ == "__main__":
    unittest.main()
