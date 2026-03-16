"""Memory subcommand handlers for ``mco memory``."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional


def show_agent_stats(client: Any, space: str) -> str:
    """Fetch and format agent scores from a space as a table.

    Args:
        client: An ``EverMemosClient`` instance.
        space: The agents space id (e.g. ``coding:my-repo--agents``).

    Returns:
        Formatted table string.
    """
    from .bridge.evermemos_client import EverMemosClient

    raw = client.fetch_history(space=space, memory_type="episodic_memory", limit=100)
    scores: List[Dict[str, Any]] = []
    for item in raw:
        content = item.get("content", "")
        if not EverMemosClient.is_agent_score_entry(content):
            continue
        try:
            score_dict = EverMemosClient.deserialize_agent_score(content)
            scores.append(score_dict)
        except (ValueError, json.JSONDecodeError):
            continue

    # Deduplicate: keep only the latest version per (agent, task_category)
    by_key: Dict[str, Dict[str, Any]] = {}
    for s in scores:
        key = "{agent}:{cat}".format(agent=s.get("agent", ""), cat=s.get("task_category", ""))
        by_key[key] = s
    scores = list(by_key.values())

    if not scores:
        return "No agent scores found in space: {space}".format(space=space)

    # Build table
    headers = ["Agent", "Task Category", "Cross-Validated Rate", "Evals", "Last Updated"]
    rows: List[List[str]] = []
    for s in scores:
        rows.append([
            str(s.get("agent", "")),
            str(s.get("task_category", "")),
            "{:.2f}".format(float(s.get("cross_validated_rate", 0.0))),
            str(s.get("finding_eval_count", 0)),
            str(s.get("last_updated", "")),
        ])

    return _format_table(headers, rows)


def show_priors(client: Any, repo_root: str, space_slug: str, category: str) -> str:
    """Compute and display blended agent weight priors.

    Args:
        client: An ``EverMemosClient`` instance.
        repo_root: Path to the repository root.
        space_slug: The inferred space slug (no ``coding:`` prefix).
        category: Task category for display context.

    Returns:
        Formatted table string.
    """
    from .bridge.cold_start import get_agent_weights
    from .bridge.core import _load_agent_rates
    from .bridge.stack_detector import detect_stack

    stack = detect_stack(repo_root)

    agents_space = "coding:{slug}--agents".format(slug=space_slug)
    stack_space = "coding:stacks--{stack}".format(stack=stack)
    global_space = "coding:global--agents"

    cat = category if category else None
    repo_scores = _load_agent_rates(client, agents_space, category=cat)
    stack_scores = _load_agent_rates(client, stack_space, category=cat)
    global_scores = _load_agent_rates(client, global_space, category=cat)

    # Count actual runs from context-space run markers (not entry count)
    run_count = 0
    try:
        from .bridge.core import MCO_RUN_MARKER_PREFIX
        context_space = "coding:{slug}--context".format(slug=space_slug)
        raw = client.fetch_history(space=context_space, memory_type="episodic_memory", limit=100)
        run_count = sum(
            1 for item in raw
            if str(item.get("content", "")).startswith(MCO_RUN_MARKER_PREFIX)
        )
    except Exception:
        pass

    weights = get_agent_weights(repo_scores, stack_scores, global_scores, run_count)

    if not weights:
        return "No agent priors found. Stack: {stack}, Category: {category}".format(
            stack=stack, category=category,
        )

    headers = ["Agent", "Repo Score", "Stack Prior", "Global Prior", "Blended Weight"]
    rows: List[List[str]] = []
    for agent in sorted(weights.keys()):
        rows.append([
            agent,
            "{:.2f}".format(repo_scores.get(agent, 0.0)),
            "{:.2f}".format(stack_scores.get(agent, 0.0)),
            "{:.2f}".format(global_scores.get(agent, 0.0)),
            "{:.2f}".format(weights[agent]),
        ])

    lines = [
        "Stack: {stack} | Category: {category} | Runs: {runs}".format(
            stack=stack, category=category, runs=run_count,
        ),
        "",
        _format_table(headers, rows),
    ]
    return "\n".join(lines)


def get_status_data(client: Any, space_slug: str) -> Dict[str, Any]:
    """Return structured status data for a repo's memory spaces.

    Returns dict with: space_slug, findings_count, agent_scores_count, briefing_preview.
    """
    from .bridge.evermemos_client import EverMemosClient

    findings_space = "coding:{slug}--findings".format(slug=space_slug)
    agents_space = "coding:{slug}--agents".format(slug=space_slug)
    context_space = "coding:{slug}--context".format(slug=space_slug)

    available = client.list_spaces()

    # Findings count (deduplicated by finding_hash)
    findings_count = 0
    if findings_space in available:
        try:
            raw = client.fetch_history(space=findings_space, memory_type="episodic_memory", limit=100)
            seen_hashes: set = set()
            for item in raw:
                content = item.get("content", "")
                if not EverMemosClient.is_finding_entry(content):
                    continue
                try:
                    finding = EverMemosClient.deserialize_finding(content)
                    fhash = finding.get("finding_hash", "")
                    if fhash:
                        seen_hashes.add(fhash)
                except (ValueError, Exception):
                    continue
            findings_count = len(seen_hashes)
        except Exception:
            pass

    # Agent scores count (deduplicated by agent+category)
    scores_count = 0
    if agents_space in available:
        try:
            raw = client.fetch_history(space=agents_space, memory_type="episodic_memory", limit=100)
            seen_keys: set = set()
            for item in raw:
                content = item.get("content", "")
                if not EverMemosClient.is_agent_score_entry(content):
                    continue
                try:
                    score_dict = EverMemosClient.deserialize_agent_score(content)
                    key = "{a}:{c}".format(
                        a=score_dict.get("agent", ""),
                        c=score_dict.get("task_category", ""),
                    )
                    seen_keys.add(key)
                except (ValueError, Exception):
                    continue
            scores_count = len(seen_keys)
        except Exception:
            pass

    # Briefing preview
    briefing_preview = ""
    try:
        briefing = client.briefing(space=context_space)
        if briefing:
            briefing_preview = briefing[:200]
    except Exception:
        pass

    return {
        "space_slug": space_slug,
        "findings_count": findings_count,
        "agent_scores_count": scores_count,
        "briefing_preview": briefing_preview,
    }


def show_status(client: Any, space_slug: str) -> str:
    """Show status overview of memory spaces for a repo.

    Args:
        client: An ``EverMemosClient`` instance.
        space_slug: The inferred space slug (no ``coding:`` prefix).

    Returns:
        Formatted status string.
    """
    data = get_status_data(client, space_slug)

    findings_space = "coding:{slug}--findings".format(slug=space_slug)
    agents_space = "coding:{slug}--agents".format(slug=space_slug)
    context_space = "coding:{slug}--context".format(slug=space_slug)

    available = client.list_spaces()

    lines: List[str] = [
        "Memory Status for: {slug}".format(slug=space_slug),
        "",
    ]

    for name, space_id in [
        ("Findings", findings_space),
        ("Agents", agents_space),
        ("Context", context_space),
    ]:
        exists = space_id in available
        lines.append("  {name}: {status} ({space_id})".format(
            name=name,
            status="exists" if exists else "not found",
            space_id=space_id,
        ))

    lines.append("")
    lines.append("Findings: {count}".format(count=data["findings_count"]))
    lines.append("Agent Scores: {count}".format(count=data["agent_scores_count"]))

    briefing_preview = data["briefing_preview"]
    if briefing_preview:
        lines.append("")
        lines.append("Context Briefing Preview:")
        if len(briefing_preview) >= 200:
            lines.append("  " + briefing_preview + "...")
        else:
            lines.append("  " + briefing_preview)
    else:
        lines.append("Context Briefing: none")

    return "\n".join(lines)


def _format_table(headers: List[str], rows: List[List[str]]) -> str:
    """Format headers and rows as a simple aligned text table."""
    if not rows:
        return "  (no data)"

    # Compute column widths
    col_widths = [len(h) for h in headers]
    for row in rows:
        for i, cell in enumerate(row):
            if i < len(col_widths):
                col_widths[i] = max(col_widths[i], len(cell))

    def _fmt_row(cells: List[str]) -> str:
        parts = []
        for i, cell in enumerate(cells):
            width = col_widths[i] if i < len(col_widths) else len(cell)
            parts.append(cell.ljust(width))
        return "  ".join(parts)

    lines = [
        _fmt_row(headers),
        "  ".join("-" * w for w in col_widths),
    ]
    for row in rows:
        lines.append(_fmt_row(row))

    return "\n".join(lines)
