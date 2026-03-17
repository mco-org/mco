"""Bridge core: implements pre_run and post_run hooks.

Phase 1 covers: list_spaces, briefing, fetch_history, remember.
Agent scoring, passive_confirm, forget are Phase 2+.

State management: all mutable state lives in BridgeContext (a dataclass),
not in module globals. register_hooks() creates a context and the hook
closures capture it. This keeps tests clean and avoids cross-run pollution.
"""
from __future__ import annotations

import json
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from .evermemos_client import EverMemosClient
from .finding_hash import compute_finding_hash
from .prompt_builder import build_injected_prompt
from .space import infer_space_slug

# Prefix for run-count markers stored in the context space.
MCO_RUN_MARKER_PREFIX = "[MCO-RUN-MARKER] "


@dataclass
class BridgeContext:
    """Per-run state for the Bridge layer. Created in register_hooks(), not global."""
    memory_space_override: Optional[str] = None
    space_slug: Optional[str] = None
    client: Optional[EverMemosClient] = None
    # Phase 2-4 additions:
    stack: str = "unknown"
    run_count: int = 0
    agent_weights: Dict[str, float] = field(default_factory=dict)
    total_agents: int = 0

    def get_client(self) -> EverMemosClient:
        if self.client is None:
            self.client = EverMemosClient()
        return self.client

    def get_slug(self, repo_root: str) -> str:
        if self.space_slug is None:
            self.space_slug = infer_space_slug(repo_root, explicit=self.memory_space_override)
        return self.space_slug


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _current_commit(repo_root: str) -> str:
    """Best-effort: get current HEAD commit short hash."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, check=False, cwd=repo_root,
        )
        return result.stdout.strip() if result.returncode == 0 else "unknown"
    except OSError:
        return "unknown"


def _changed_files_since(repo_root: str, since_commit: str) -> set:
    """Get files changed between since_commit and HEAD."""
    try:
        result = subprocess.run(
            ["git", "diff", "--name-only", since_commit, "HEAD"],
            capture_output=True, text=True, check=False, cwd=repo_root,
        )
        if result.returncode == 0:
            return set(result.stdout.strip().splitlines())
    except OSError:
        pass
    return set()


def _dedupe_findings_latest(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate findings by finding_hash, keeping only the latest version.

    fetch_history returns items in chronological order, so later entries
    are newer.  We keep the last occurrence of each hash.
    """
    by_hash: Dict[str, Dict[str, Any]] = {}
    for f in items:
        fhash = f.get("finding_hash", "")
        if fhash:
            by_hash[fhash] = f
    return list(by_hash.values())


def _dedupe_scores_latest(items: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deduplicate agent scores by (agent, task_category), keeping latest."""
    by_key: Dict[str, Dict[str, Any]] = {}
    for s in items:
        key = f"{s.get('agent', '')}:{s.get('task_category', '')}"
        by_key[key] = s
    return list(by_key.values())


def _parse_history_findings(
    raw_history: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Parse fetch_history items into finding dicts, injecting memory_id from outer item."""
    results: List[Dict[str, Any]] = []
    for item in raw_history:
        content = item.get("content", "")
        if not EverMemosClient.is_finding_entry(content):
            continue
        try:
            finding = EverMemosClient.deserialize_finding(content)
        except (ValueError, json.JSONDecodeError):
            continue
        # Fix 4: Inject memory_id from the outer fetch_history item
        item_id = item.get("id") or item.get("memory_id")
        if item_id:
            finding["memory_id"] = item_id
        results.append(finding)
    return results


def _count_run_markers(raw_history: List[Dict[str, Any]]) -> int:
    """Count [MCO-RUN-MARKER] entries in a context-space history."""
    return sum(
        1 for item in raw_history
        if str(item.get("content", "")).startswith(MCO_RUN_MARKER_PREFIX)
    )


def _load_agent_rates(
    client: EverMemosClient,
    space: str,
    category: Optional[str] = None,
) -> Dict[str, float]:
    """Read agent scores from an evermemos space and return {agent: cross_validated_rate}.

    Args:
        category: If set, only return scores matching this task_category.
            If None, average across all categories per agent.

    Returns an empty dict on any error (missing space, network issue, etc.).
    """
    try:
        raw = client.fetch_history(space=space, memory_type="episodic_memory", limit=100)
    except Exception as exc:
        print("[mco-bridge] failed to load agent rates: {}".format(exc), file=sys.stderr)
        return {}

    # Parse and deduplicate scores
    all_scores: List[Dict[str, Any]] = []
    for item in raw:
        content = item.get("content", "")
        if not EverMemosClient.is_agent_score_entry(content):
            continue
        try:
            score_dict = EverMemosClient.deserialize_agent_score(content)
            all_scores.append(score_dict)
        except (ValueError, json.JSONDecodeError):
            continue

    all_scores = _dedupe_scores_latest(all_scores)

    if category is not None:
        # Filter to specific category
        rates: Dict[str, float] = {}
        for s in all_scores:
            if s.get("task_category") == category:
                agent = s.get("agent", "")
                if agent:
                    rates[agent] = float(s.get("cross_validated_rate", 0.0))
        return rates
    else:
        # Average across all categories per agent
        agent_sums: Dict[str, float] = {}
        agent_counts: Dict[str, int] = {}
        for s in all_scores:
            agent = s.get("agent", "")
            if not agent:
                continue
            rate = float(s.get("cross_validated_rate", 0.0))
            agent_sums[agent] = agent_sums.get(agent, 0.0) + rate
            agent_counts[agent] = agent_counts.get(agent, 0) + 1
        return {
            a: agent_sums[a] / agent_counts[a]
            for a in agent_sums
            if agent_counts[a] > 0
        }


def _merge_finding_with_existing(
    existing: Dict[str, Any],
    new_raw: Dict[str, Any],
    commit: str,
) -> Dict[str, Any]:
    """Merge a new occurrence into an existing persisted finding.

    Updates: occurrence_count, last_seen, last_seen_commit, detected_by union.
    Preserves: first_seen, finding_hash, status, category.
    """
    merged = dict(existing)
    merged["occurrence_count"] = existing.get("occurrence_count", 1) + 1
    merged["last_seen"] = _now_iso()
    merged["last_seen_commit"] = commit

    old_by: List[str] = list(existing.get("detected_by", []))
    new_by: List[str] = list(new_raw.get("detected_by", []))
    merged["detected_by"] = sorted(set(old_by) | set(new_by))

    return merged


def make_pre_run(ctx: BridgeContext) -> Callable[..., Optional[str]]:
    """Create a pre_run hook closure that captures BridgeContext."""

    def bridge_pre_run(
        prompt: str,
        repo_root: str,
        providers: List[str],
    ) -> Optional[str]:
        try:
            return _pre_run_impl(ctx, prompt, repo_root, providers)
        except Exception as exc:
            print(f"[mco-bridge] pre_run failed, continuing without memory: {exc}", file=sys.stderr)
            return None

    return bridge_pre_run


def _pre_run_impl(
    ctx: BridgeContext,
    prompt: str,
    repo_root: str,
    providers: List[str],
) -> Optional[str]:
    client = ctx.get_client()
    slug = ctx.get_slug(repo_root)

    findings_space = f"coding:{slug}--findings"
    context_space = f"coding:{slug}--context"

    # Step 0: Verify space exists
    available = client.list_spaces()
    space_exists = findings_space in available

    # Step 1: Get project context via briefing
    context = None
    if space_exists:
        context = client.briefing(space=context_space)

    # Step 2: Get historical findings via fetch_history
    open_findings: List[Dict[str, Any]] = []
    accepted_risks: List[Dict[str, Any]] = []
    if space_exists:
        raw_history = client.fetch_history(
            space=findings_space,
            memory_type="episodic_memory",
            limit=100,
        )
        # Parse + deduplicate: only the latest version of each finding_hash
        all_findings = _dedupe_findings_latest(_parse_history_findings(raw_history))
        for finding in all_findings:
            status = finding.get("status", "open")
            if status == "open":
                open_findings.append(finding)
            elif status in ("accepted", "wontfix"):
                accepted_risks.append(finding)

    # Step 3: Detect tech stack
    from .stack_detector import detect_stack
    ctx.stack = detect_stack(repo_root)

    # Step 4: Count actual runs from context-space run markers
    ctx.run_count = 0
    if space_exists:
        try:
            context_history = client.fetch_history(
                space=context_space, memory_type="episodic_memory", limit=100,
            )
            ctx.run_count = _count_run_markers(context_history)
        except Exception as exc:
            print("[mco-bridge] failed to count run markers: {}".format(exc), file=sys.stderr)

    # Step 5: Retrieve agent scores for weight computation
    from .cold_start import get_agent_weights
    agents_space = f"coding:{slug}--agents"
    stack_space = f"coding:stacks--{ctx.stack}"
    global_space = "coding:global--agents"

    repo_scores = _load_agent_rates(client, agents_space)
    stack_scores = _load_agent_rates(client, stack_space)
    global_scores = _load_agent_rates(client, global_space)

    ctx.agent_weights = get_agent_weights(repo_scores, stack_scores, global_scores, ctx.run_count)
    ctx.total_agents = len(providers)

    # Step 6: Build augmented prompt
    injected = build_injected_prompt(
        original=prompt,
        context=context,
        known_open=open_findings,
        accepted_risks=accepted_risks,
        agent_weights=ctx.agent_weights,
        total_agents=ctx.total_agents,
    )

    if injected != prompt:
        count = len(open_findings) + len(accepted_risks)
        print(f"[mco-bridge] Injected {count} historical findings into prompt", file=sys.stderr)

    return injected


def make_post_run(ctx: BridgeContext) -> Callable[..., None]:
    """Create a post_run hook closure that captures BridgeContext."""

    def bridge_post_run(
        findings: List[Dict[str, Any]],
        provider_results: Dict[str, Dict[str, Any]],
        repo_root: str,
        prompt: str,
        providers: List[str],
    ) -> None:
        try:
            _post_run_impl(ctx, findings, provider_results, repo_root, prompt, providers)
        except Exception as exc:
            print(f"[mco-bridge] post_run failed, findings not persisted: {exc}", file=sys.stderr)

    return bridge_post_run


def _post_run_impl(
    ctx: BridgeContext,
    findings: List[Dict[str, Any]],
    provider_results: Dict[str, Dict[str, Any]],
    repo_root: str,
    prompt: str,
    providers: List[str],
) -> None:
    client = ctx.get_client()
    slug = ctx.get_slug(repo_root)
    findings_space = f"coding:{slug}--findings"
    commit = _current_commit(repo_root)

    # Load existing findings to enable merge (not just append)
    # Deduplicate: only keep the latest version of each finding_hash
    existing_by_hash: Dict[str, Dict[str, Any]] = {}
    try:
        raw_history = client.fetch_history(
            space=findings_space,
            memory_type="episodic_memory",
            limit=100,
        )
        all_existing = _dedupe_findings_latest(_parse_history_findings(raw_history))
        for finding in all_existing:
            fhash = finding.get("finding_hash", "")
            if fhash:
                existing_by_hash[fhash] = finding
    except Exception as exc:
        print("[mco-bridge] failed to load existing findings: {}".format(exc), file=sys.stderr)

    # --- Confidence calculation (before remember) ---
    from .confidence import finding_confidence as _finding_confidence

    written = 0
    written_persisted: List[Dict[str, Any]] = []
    critical_high_request_ids: List[str] = []
    current_hashes: set = set()
    for raw_finding in findings:
        title = str(raw_finding.get("title", ""))
        category = str(raw_finding.get("category", ""))
        file_path = ""
        evidence = raw_finding.get("evidence")
        if isinstance(evidence, dict):
            file_path = str(evidence.get("file", ""))

        if not title:
            continue

        fhash = compute_finding_hash(
            repo=slug,
            file_path=file_path,
            category=category,
            title=title,
        )
        current_hashes.add(fhash)

        existing = existing_by_hash.get(fhash)
        if existing:
            # Merge: increment occurrence, update timestamps, union detected_by
            persisted = _merge_finding_with_existing(existing, raw_finding, commit)
        else:
            # New finding
            detected_by = raw_finding.get("detected_by")
            if not isinstance(detected_by, list):
                detected_by = providers[:1]
            persisted = {
                "finding_hash": fhash,
                "category": category,
                "severity": str(raw_finding.get("severity", "medium")),
                "title": title,
                "description": str(raw_finding.get("recommendation", "")),
                "file": file_path,
                "line": evidence.get("line") if isinstance(evidence, dict) else None,
                "detected_by": detected_by,
                "occurrence_count": 1,
                "first_seen": _now_iso(),
                "last_seen": _now_iso(),
                "last_seen_commit": commit,
                "status": "open",
                "confidence": float(raw_finding.get("confidence", 0.5)),
            }

        # Compute confidence BEFORE remember()
        persisted["confidence"] = _finding_confidence(
            detected_by=persisted.get("detected_by", []),
            total_agents=ctx.total_agents if ctx.total_agents > 0 else len(providers),
            agent_weights=ctx.agent_weights,
            occurrence_count=persisted.get("occurrence_count", 1),
        )

        content = EverMemosClient.serialize_finding(persisted)
        result = client.remember(space=findings_space, content=content)
        written += 1
        written_persisted.append(persisted)

        # Track request_ids for critical/high findings for status polling
        severity = persisted.get("severity", "medium").lower()
        request_id = result.get("request_id") if isinstance(result, dict) else None
        if severity in ("critical", "high") and request_id:
            critical_high_request_ids.append(request_id)

    if written:
        print(f"[mco-bridge] Wrote {written} findings to {findings_space}", file=sys.stderr)

    # --- Task classification ---
    from .classifier import classify_task
    task_category = classify_task(prompt, findings)

    # --- Agent scoring ---
    from .scoring import update_scores_from_findings, merge_agent_score, AgentScore
    new_scores = update_scores_from_findings(written_persisted, slug, task_category, {})

    agents_space = f"coding:{slug}--agents"
    # Read existing agent scores, merge, and write back
    existing_agent_scores: Dict[str, AgentScore] = {}
    try:
        agent_history = client.fetch_history(
            space=agents_space, memory_type="episodic_memory", limit=100,
        )
        for item in agent_history:
            content = item.get("content", "")
            if not EverMemosClient.is_agent_score_entry(content):
                continue
            try:
                score_dict = EverMemosClient.deserialize_agent_score(content)
                score_obj = AgentScore.from_dict(score_dict)
                key = (score_obj.agent, score_obj.task_category)
                existing_agent_scores[key] = score_obj
            except (ValueError, json.JSONDecodeError, KeyError):
                continue
    except Exception as exc:
        print("[mco-bridge] failed to load agent scores: {}".format(exc), file=sys.stderr)

    scores_written = 0
    for key, new_score in new_scores.items():
        if key in existing_agent_scores:
            merged_score = merge_agent_score(existing_agent_scores[key], new_score)
        else:
            merged_score = new_score
        score_content = EverMemosClient.serialize_agent_score(merged_score.to_dict())
        client.remember(space=agents_space, content=score_content)
        scores_written += 1

    if scores_written:
        print(f"[mco-bridge] Wrote {scores_written} agent scores to {agents_space}", file=sys.stderr)

    # --- Update stack aggregate for cold-start priors ---
    from .scoring import update_stack_aggregate
    stack_space = f"coding:stacks--{ctx.stack}"
    update_stack_aggregate(client, stack_space, new_scores)

    # --- Status polling for critical/high findings ---
    if critical_high_request_ids:
        from .status_poller import poll_until_searchable
        poll_until_searchable(client, critical_high_request_ids, timeout_s=30, interval_s=3)

    # --- Passive confirmation ---
    # Build per-commit changed-files cache (not a union — each finding
    # should only see changes since *its own* last_seen_commit)
    commits_in_history = {
        f.get("last_seen_commit", "")
        for f in existing_by_hash.values()
        if f.get("last_seen_commit")
    }
    changed_files_by_commit: Dict[str, set] = {}
    for c in commits_in_history:
        if c and c != "unknown":
            changed_files_by_commit[c] = _changed_files_since(repo_root, c)

    from .passive_confirm import check_passive_fixes
    passive_updates = check_passive_fixes(
        existing_findings=list(existing_by_hash.values()),
        current_hashes=current_hashes,
        current_commit=commit,
        changed_files_by_commit=changed_files_by_commit,
    )
    for updated in passive_updates:
        content = EverMemosClient.serialize_finding(updated)
        client.remember(space=findings_space, content=content)

    if passive_updates:
        fixed_count = sum(1 for u in passive_updates if u.get("status") == "fixed")
        candidate_count = len(passive_updates) - fixed_count
        print(f"[mco-bridge] Passive confirmation: {fixed_count} fixed, {candidate_count} candidates", file=sys.stderr)

    # --- Forget rejected findings ---
    from .forget_cleaner import clean_rejected_findings
    clean_rejected_findings(client, list(existing_by_hash.values()), space=findings_space)

    # --- Write run marker for accurate run_count tracking ---
    context_space = f"coding:{slug}--context"
    run_marker = json.dumps({
        "timestamp": _now_iso(),
        "providers": providers,
        "findings_count": written,
        "task_category": task_category,
    })
    client.remember(
        space=context_space,
        content=f"{MCO_RUN_MARKER_PREFIX}{run_marker}",
    )
