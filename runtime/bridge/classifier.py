"""Task-type auto-classification from prompt keywords and finding distributions."""
from __future__ import annotations

from typing import Any, Dict, List

CATEGORY_SIGNALS: Dict[str, List[str]] = {
    "security": ["security", "vulnerabilit", "injection", "xss", "csrf", "authentication", "authorization"],
    "performance": ["performance", "latency", "memory leak", "bottleneck", "optimization"],
    "logic": ["bug", "logic", "race condition", "deadlock", "edge case"],
    "architecture": ["architecture", "design", "coupling", "dependency"],
    "style": ["style", "lint", "format", "naming", "convention"],
}


def _score_prompt(prompt: str) -> Dict[str, float]:
    """Count keyword matches in the lowered prompt for each category."""
    lower = prompt.lower()
    scores: Dict[str, float] = {}
    for category, keywords in CATEGORY_SIGNALS.items():
        count = sum(1 for kw in keywords if kw in lower)
        if count:
            scores[category] = float(count)
    return scores


def _score_findings(findings: List[Dict[str, Any]]) -> Dict[str, float]:
    """Count finding category occurrences."""
    scores: Dict[str, float] = {}
    for finding in findings:
        cat = finding.get("category", "")
        if cat:
            scores[cat] = scores.get(cat, 0.0) + 1.0
    return scores


def classify_task(
    prompt: str,
    findings: List[Dict[str, Any]],
    prompt_weight: float = 0.3,
    findings_weight: float = 0.7,
) -> str:
    """Classify a task into a category based on prompt keywords and findings.

    Returns the category with the highest weighted score, or ``"general"``
    when no signal is detected.
    """
    prompt_scores = _score_prompt(prompt)
    finding_scores = _score_findings(findings)

    all_categories = set(prompt_scores) | set(finding_scores)
    if not all_categories:
        return "general"

    best_category = "general"
    best_score = 0.0
    for cat in all_categories:
        combined = (
            prompt_weight * prompt_scores.get(cat, 0.0)
            + findings_weight * finding_scores.get(cat, 0.0)
        )
        if combined > best_score:
            best_score = combined
            best_category = cat

    return best_category
