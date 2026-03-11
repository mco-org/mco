from __future__ import annotations

import unittest

from runtime.bridge.cold_start import get_agent_weights


class TestColdStartWeightMixing(unittest.TestCase):
    def test_pure_cold_start_uses_stack_and_global(self) -> None:
        """No repo scores, run_count=0 -> 70% stack + 30% global."""
        stack_scores = {"claude": 0.8, "gemini": 0.6}
        global_scores = {"claude": 0.5, "gemini": 0.5}

        result = get_agent_weights(
            repo_scores={},
            stack_scores=stack_scores,
            global_scores=global_scores,
            run_count=0,
        )

        self.assertAlmostEqual(result["claude"], 0.71)
        self.assertAlmostEqual(result["gemini"], 0.57)

    def test_fully_mature_uses_repo_only(self) -> None:
        """run_count=10, alpha=1.0 -> 100% repo scores."""
        repo_scores = {"claude": 0.9, "gemini": 0.7}
        stack_scores = {"claude": 0.8, "gemini": 0.6}
        global_scores = {"claude": 0.5, "gemini": 0.5}

        result = get_agent_weights(
            repo_scores=repo_scores,
            stack_scores=stack_scores,
            global_scores=global_scores,
            run_count=10,
        )

        self.assertAlmostEqual(result["claude"], 0.9)
        self.assertAlmostEqual(result["gemini"], 0.7)

    def test_partial_maturity_blends(self) -> None:
        """run_count=5, alpha=0.5 -> 50% repo + 50% prior."""
        repo_scores = {"claude": 1.0}
        stack_scores = {"claude": 0.6}
        global_scores = {"claude": 0.4}

        result = get_agent_weights(
            repo_scores=repo_scores,
            stack_scores=stack_scores,
            global_scores=global_scores,
            run_count=5,
        )

        # prior = 0.7*0.6 + 0.3*0.4 = 0.54
        # final = 0.5*1.0 + 0.5*0.54 = 0.77
        self.assertAlmostEqual(result["claude"], 0.77)

    def test_empty_all_returns_empty(self) -> None:
        """All sources empty -> empty dict."""
        result = get_agent_weights(
            repo_scores={},
            stack_scores={},
            global_scores={},
            run_count=0,
        )

        self.assertEqual(result, {})

    def test_missing_agent_in_some_sources(self) -> None:
        """Agent only in repo -> uses repo directly."""
        repo_scores = {"cursor": 0.85}

        result = get_agent_weights(
            repo_scores=repo_scores,
            stack_scores={},
            global_scores={},
            run_count=3,
        )

        self.assertAlmostEqual(result["cursor"], 0.85)
