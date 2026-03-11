"""Tests for finding confidence calculation."""
from __future__ import annotations

import unittest

from runtime.bridge.confidence import (
    DEFAULT_AGENT_WEIGHT,
    confidence_grade,
    finding_confidence,
)


class TestFindingConfidence(unittest.TestCase):
    def test_full_consensus_high_reliability(self) -> None:
        """All 3 agents detect, high weights, occurrence 3 -> 0.92."""
        result = finding_confidence(
            detected_by=["a", "b", "c"],
            total_agents=3,
            agent_weights={"a": 0.9, "b": 0.8, "c": 0.7},
            occurrence_count=3,
        )
        # consensus=1.0, reliability=0.8, recurrence=1.0
        # 0.4*1.0 + 0.4*0.8 + 0.2*1.0 = 0.92
        self.assertAlmostEqual(result, 0.92)

    def test_single_agent_low_occurrence(self) -> None:
        """1 of 3 agents, weight 0.5, occurrence 1 -> ~0.4."""
        result = finding_confidence(
            detected_by=["a"],
            total_agents=3,
            agent_weights={"a": 0.5},
            occurrence_count=1,
        )
        # consensus=1/3, reliability=0.5, recurrence=1/3
        # 0.4*(1/3) + 0.4*0.5 + 0.2*(1/3)
        expected = 0.4 * (1 / 3) + 0.4 * 0.5 + 0.2 * (1 / 3)
        self.assertAlmostEqual(result, expected)

    def test_missing_agent_weight_uses_default(self) -> None:
        """Unknown agent should use DEFAULT_AGENT_WEIGHT (0.5)."""
        result = finding_confidence(
            detected_by=["unknown_agent"],
            total_agents=1,
            agent_weights={},
            occurrence_count=3,
        )
        # consensus=1.0, reliability=0.5 (default), recurrence=1.0
        expected = 0.4 * 1.0 + 0.4 * DEFAULT_AGENT_WEIGHT + 0.2 * 1.0
        self.assertAlmostEqual(result, expected)

    def test_zero_total_agents_safe(self) -> None:
        """total_agents=0 doesn't crash (clamped to 1)."""
        result = finding_confidence(
            detected_by=["a"],
            total_agents=0,
            agent_weights={"a": 0.8},
            occurrence_count=1,
        )
        # consensus = 1/1 = 1.0 (clamped), reliability=0.8, recurrence=1/3
        expected = 0.4 * 1.0 + 0.4 * 0.8 + 0.2 * (1 / 3)
        self.assertAlmostEqual(result, expected)


class TestConfidenceGrade(unittest.TestCase):
    def test_high_grade(self) -> None:
        self.assertEqual(confidence_grade(0.8), "HIGH")
        self.assertEqual(confidence_grade(0.75), "HIGH")

    def test_medium_grade(self) -> None:
        self.assertEqual(confidence_grade(0.6), "MEDIUM")
        self.assertEqual(confidence_grade(0.45), "MEDIUM")

    def test_low_grade(self) -> None:
        self.assertEqual(confidence_grade(0.3), "LOW")
        self.assertEqual(confidence_grade(0.44), "LOW")
