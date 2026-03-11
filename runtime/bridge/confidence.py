"""Finding confidence calculation combining consensus, reliability, and recurrence.

Produces a single 0.0–1.0 confidence score for a finding based on how many
agents detected it, those agents' reliability weights, and how many times the
finding has recurred across runs.
"""
from __future__ import annotations

from typing import Dict, List

DEFAULT_AGENT_WEIGHT: float = 0.5


def finding_confidence(
    detected_by: List[str],
    total_agents: int,
    agent_weights: Dict[str, float],
    occurrence_count: int,
) -> float:
    """Compute a weighted confidence score for a finding.

    Formula: ``0.4 * consensus + 0.4 * reliability + 0.2 * recurrence``

    Args:
        detected_by: Agent identifiers that flagged this finding.
        total_agents: Total number of agents in the run (clamped to min 1).
        agent_weights: Mapping of agent id to reliability weight (0.0–1.0).
        occurrence_count: How many times this finding has been seen across runs.

    Returns:
        Confidence score in ``[0.0, 1.0]``.
    """
    safe_total = max(1, total_agents)
    consensus = len(detected_by) / safe_total

    weights = [
        agent_weights.get(agent, DEFAULT_AGENT_WEIGHT) for agent in detected_by
    ]
    reliability = sum(weights) / len(weights) if weights else DEFAULT_AGENT_WEIGHT

    recurrence = min(1.0, occurrence_count / 3.0)

    return 0.4 * consensus + 0.4 * reliability + 0.2 * recurrence


def confidence_grade(confidence: float) -> str:
    """Map a numeric confidence score to a human-readable grade.

    Args:
        confidence: Score in ``[0.0, 1.0]``.

    Returns:
        ``"HIGH"`` (>= 0.75), ``"MEDIUM"`` (>= 0.45), or ``"LOW"``.
    """
    if confidence >= 0.75:
        return "HIGH"
    if confidence >= 0.45:
        return "MEDIUM"
    return "LOW"
