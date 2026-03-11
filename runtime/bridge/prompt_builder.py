"""Build memory-injected prompts for MCO runs."""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def build_injected_prompt(
    original: str,
    context: Optional[str],
    known_open: List[Dict[str, Any]],
    accepted_risks: List[Dict[str, Any]],
    max_injected_findings: int = 20,
    agent_weights: Optional[Dict[str, float]] = None,
    total_agents: int = 0,
) -> str:
    """Augment the user's prompt with historical memory context.

    Returns the original prompt unchanged if there's no history to inject.

    When ``agent_weights`` and ``total_agents`` are provided, each known-open
    finding is annotated with a confidence grade (HIGH/MEDIUM/LOW).
    """
    from .confidence import finding_confidence, confidence_grade

    sections: List[str] = []

    if context:
        sections.append(f"## Project Context (from previous runs)\n{context}")

    if accepted_risks:
        lines = ["## Accepted Risks (do NOT report these)"]
        for risk in accepted_risks[:max_injected_findings]:
            title = risk.get("title", "unknown")
            lines.append(f"- {title}")
        sections.append("\n".join(lines))

    if known_open:
        lines = ["## Known Open Findings (already tracked, report only if still present)"]
        for finding in known_open[:max_injected_findings]:
            title = finding.get("title", "unknown")
            file = finding.get("file", "")

            # Compute confidence grade when weights are available
            grade_label = ""
            if agent_weights is not None:
                conf = finding.get("confidence")
                if conf is None:
                    conf = finding_confidence(
                        detected_by=finding.get("detected_by", []),
                        total_agents=max(total_agents, 1),
                        agent_weights=agent_weights,
                        occurrence_count=finding.get("occurrence_count", 1),
                    )
                grade_label = f"[{confidence_grade(conf)}] "

            lines.append(f"- {grade_label}{title} ({file})")
        sections.append("\n".join(lines))

    if not sections:
        return original

    injected = "\n\n".join(sections)
    return f"{original}\n\n---\n\n{injected}"
