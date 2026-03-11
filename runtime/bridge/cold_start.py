from __future__ import annotations

from typing import Dict


def get_agent_weights(
    repo_scores: Dict[str, float],
    stack_scores: Dict[str, float],
    global_scores: Dict[str, float],
    run_count: int,
) -> Dict[str, float]:
    """Blend repo-specific, tech-stack, and global baseline scores.

    Uses a maturity factor (alpha) based on run_count to transition
    from prior-based estimates to repo-observed scores as data accumulates.

    Algorithm:
        1. prior[agent] = 0.7 * stack + 0.3 * global
        2. alpha = min(1.0, run_count / 10.0)
        3. If repo and prior exist:  final = alpha * repo + (1 - alpha) * prior
        4. If only prior exists:     final = prior
        5. If only repo exists:      final = repo
        6. All sources empty ->      empty result
    """
    alpha = min(1.0, run_count / 10.0)

    # Collect all agent names across every source.
    all_agents: set[str] = set()
    all_agents.update(repo_scores)
    all_agents.update(stack_scores)
    all_agents.update(global_scores)

    result: Dict[str, float] = {}

    for agent in all_agents:
        has_repo = agent in repo_scores
        has_stack = agent in stack_scores
        has_global = agent in global_scores

        # Build prior from stack (70%) + global (30%) when either is available.
        prior: float | None = None
        if has_stack or has_global:
            stack_val = stack_scores.get(agent, 0.0)
            global_val = global_scores.get(agent, 0.0)
            prior = 0.7 * stack_val + 0.3 * global_val

        if has_repo and prior is not None:
            result[agent] = alpha * repo_scores[agent] + (1.0 - alpha) * prior
        elif prior is not None:
            result[agent] = prior
        elif has_repo:
            result[agent] = repo_scores[agent]
        # else: agent somehow appeared but has no usable data — skip.

    return result
