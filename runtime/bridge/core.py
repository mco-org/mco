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


@dataclass
class BridgeContext:
    """Per-run state for the Bridge layer. Created in register_hooks(), not global."""
    memory_space_override: Optional[str] = None
    space_slug: Optional[str] = None
    client: Optional[EverMemosClient] = None

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
        for item in raw_history:
            content = item.get("content", "")
            if not EverMemosClient.is_finding_entry(content):
                continue
            try:
                finding = EverMemosClient.deserialize_finding(content)
            except (ValueError, json.JSONDecodeError):
                continue
            status = finding.get("status", "open")
            if status == "open":
                open_findings.append(finding)
            elif status in ("accepted", "wontfix"):
                accepted_risks.append(finding)

    # Step 3: Build augmented prompt
    injected = build_injected_prompt(
        original=prompt,
        context=context,
        known_open=open_findings,
        accepted_risks=accepted_risks,
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
    existing_by_hash: Dict[str, Dict[str, Any]] = {}
    try:
        raw_history = client.fetch_history(
            space=findings_space,
            memory_type="episodic_memory",
            limit=100,
        )
        for item in raw_history:
            content = item.get("content", "")
            if not EverMemosClient.is_finding_entry(content):
                continue
            try:
                finding = EverMemosClient.deserialize_finding(content)
                fhash = finding.get("finding_hash", "")
                if fhash:
                    existing_by_hash[fhash] = finding
            except (ValueError, json.JSONDecodeError):
                continue
    except Exception:
        pass  # cold start or connection issue — proceed with empty history

    written = 0
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

        content = EverMemosClient.serialize_finding(persisted)
        client.remember(space=findings_space, content=content)
        written += 1

    if written:
        print(f"[mco-bridge] Wrote {written} findings to {findings_space}", file=sys.stderr)

    # --- Passive confirmation ---
    # Get files changed since the earliest last_seen_commit in existing findings
    commits_in_history = {
        f.get("last_seen_commit", "")
        for f in existing_by_hash.values()
        if f.get("last_seen_commit")
    }
    all_changed_files: set = set()
    for c in commits_in_history:
        if c and c != "unknown":
            all_changed_files.update(_changed_files_since(repo_root, c))

    from .passive_confirm import check_passive_fixes
    passive_updates = check_passive_fixes(
        existing_findings=list(existing_by_hash.values()),
        current_hashes=current_hashes,
        current_commit=commit,
        changed_files=all_changed_files,
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
