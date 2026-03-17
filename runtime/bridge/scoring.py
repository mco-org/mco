"""Agent reliability scoring with cross-validation tracking.

Tracks how reliably each AI agent finds issues across runs, including
cross-validation (found by 2+ agents), unique confirmed fixes, and
false-positive (rejected) rates.
"""
from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Tuple


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class AgentScore:
    """Reliability score for a single agent in a specific category."""

    agent: str
    repo: str
    task_category: str
    cross_validated_count: int = 0
    cross_validated_rate: float = 0.0
    unique_passive_confirmed: int = 0
    unique_passive_pending: int = 0
    unique_rejected: int = 0
    finding_eval_count: int = 0
    last_updated: str = ""

    def to_dict(self) -> Dict[str, Any]:
        return {
            "agent": self.agent,
            "repo": self.repo,
            "task_category": self.task_category,
            "cross_validated_count": self.cross_validated_count,
            "cross_validated_rate": self.cross_validated_rate,
            "unique_passive_confirmed": self.unique_passive_confirmed,
            "unique_passive_pending": self.unique_passive_pending,
            "unique_rejected": self.unique_rejected,
            "finding_eval_count": self.finding_eval_count,
            "last_updated": self.last_updated,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> AgentScore:
        return cls(
            agent=data["agent"],
            repo=data["repo"],
            task_category=data["task_category"],
            cross_validated_count=data.get("cross_validated_count", 0),
            cross_validated_rate=data.get("cross_validated_rate", 0.0),
            unique_passive_confirmed=data.get("unique_passive_confirmed", 0),
            unique_passive_pending=data.get("unique_passive_pending", 0),
            unique_rejected=data.get("unique_rejected", 0),
            finding_eval_count=data.get("finding_eval_count", 0),
            last_updated=data.get("last_updated", ""),
        )


def update_scores_from_findings(
    findings: List[Dict[str, Any]],
    repo: str,
    task_category: str,
    existing_scores: Dict[Tuple[str, str], AgentScore],
) -> Dict[Tuple[str, str], AgentScore]:
    """Update agent scores based on a batch of evaluated findings.

    For each finding, examines ``detected_by`` to determine cross-validation
    status and increments the appropriate counters per agent.

    Args:
        findings: List of finding dicts, each with ``detected_by``, ``category``,
            and ``status`` fields.
        repo: Repository identifier.
        task_category: Task category label for grouping scores.
        existing_scores: Mutable dict of ``(agent, category) -> AgentScore``.
            Updated in-place and returned.

    Returns:
        The updated scores dict (same object as ``existing_scores``).
    """
    scores = dict(existing_scores)
    now = _now_iso()

    for finding in findings:
        detected_by: List[str] = finding.get("detected_by", [])
        category: str = finding.get("category", task_category)
        status: str = finding.get("status", "open")

        is_cross_validated = len(detected_by) > 1

        for agent in detected_by:
            key = (agent, category)

            if key not in scores:
                scores[key] = AgentScore(
                    agent=agent,
                    repo=repo,
                    task_category=category,
                )

            score = scores[key]
            score.finding_eval_count += 1

            if is_cross_validated:
                score.cross_validated_count += 1
            else:
                # Unique finding — classify by status
                if status == "fixed":
                    score.unique_passive_confirmed += 1
                elif status == "rejected":
                    score.unique_rejected += 1
                else:
                    score.unique_passive_pending += 1

            # Recompute rate
            score.cross_validated_rate = (
                score.cross_validated_count / score.finding_eval_count
            )
            score.last_updated = now

    return scores


def merge_agent_score(old: AgentScore, new: AgentScore) -> AgentScore:
    """Merge two AgentScore instances by accumulating counts and recomputing rate.

    Args:
        old: The existing score to merge into.
        new: The incoming score to merge from.

    Returns:
        A new AgentScore with accumulated counts and recomputed rate.
    """
    total_eval = old.finding_eval_count + new.finding_eval_count
    total_cv = old.cross_validated_count + new.cross_validated_count

    return AgentScore(
        agent=old.agent,
        repo=old.repo,
        task_category=old.task_category,
        cross_validated_count=total_cv,
        cross_validated_rate=total_cv / total_eval if total_eval > 0 else 0.0,
        unique_passive_confirmed=old.unique_passive_confirmed + new.unique_passive_confirmed,
        unique_passive_pending=old.unique_passive_pending + new.unique_passive_pending,
        unique_rejected=old.unique_rejected + new.unique_rejected,
        finding_eval_count=total_eval,
        last_updated=_now_iso(),
    )


def update_stack_aggregate(
    client: Any,
    stack_space: str,
    new_scores: Dict[Tuple[str, str], AgentScore],
) -> None:
    """Aggregate agent scores across repos into a tech-stack-level space.

    Reads existing scores from *stack_space*, merges incoming *new_scores*
    using :func:`merge_agent_score`, and writes the merged results back.
    This feeds cold-start priors for new repos that share the same stack.

    Args:
        client: An :class:`~runtime.bridge.evermemos_client.EverMemosClient`
            (or compatible mock).
        stack_space: The evermemos space id, e.g. ``"coding:stacks--python"``.
        new_scores: Mapping of ``(agent, task_category)`` to new
            :class:`AgentScore` instances from the current run.
    """
    from .evermemos_client import EverMemosClient

    # Step 1-3: Read existing stack-level scores and build lookup
    existing_by_key: Dict[Tuple[str, str], AgentScore] = {}
    try:
        raw = client.fetch_history(
            space=stack_space, memory_type="episodic_memory", limit=100,
        )
        for item in raw:
            content = item.get("content", "")
            if not EverMemosClient.is_agent_score_entry(content):
                continue
            try:
                score_dict = EverMemosClient.deserialize_agent_score(content)
                score_obj = AgentScore.from_dict(score_dict)
                key = (score_obj.agent, score_obj.task_category)
                existing_by_key[key] = score_obj
            except (ValueError, json.JSONDecodeError, KeyError):
                continue
    except Exception as exc:
        print("[mco-bridge] failed to load agent scores for stack update: {}".format(exc), file=sys.stderr)

    # Step 4-5: Merge and write back
    for key, new_score in new_scores.items():
        if key in existing_by_key:
            merged = merge_agent_score(existing_by_key[key], new_score)
        else:
            merged = new_score
        content = EverMemosClient.serialize_agent_score(merged.to_dict())
        client.remember(space=stack_space, content=content)
