"""Passive confirmation logic for finding lifecycle management.

Two-strike rule: when an open finding is absent from two consecutive runs
where its file has changed, we infer it was fixed.

- First absence (file changed): mark passive_fix_candidate=True, keep open
- Second consecutive absence (already candidate): mark status=fixed
- Reappearance: clear passive_fix_candidate flag
- Non-open findings are skipped entirely
- File not changed: no inference
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Set


def check_passive_fixes(
    existing_findings: List[Dict[str, Any]],
    current_hashes: Set[str],
    current_commit: str,
    changed_files: Optional[Set[str]] = None,
    changed_files_by_commit: Optional[Dict[str, Set[str]]] = None,
) -> List[Dict[str, Any]]:
    """Check existing findings against current run results for passive fix inference.

    Args:
        existing_findings: Previously persisted findings from memory.
        current_hashes: Set of finding_hash values detected in the current run.
        current_commit: The current HEAD commit identifier.
        changed_files: (Legacy) Flat set of changed file paths for all findings.
            Used when changed_files_by_commit is not provided.
        changed_files_by_commit: Per-commit changed-files cache.  Each finding
            looks up its own ``last_seen_commit`` so that only changes since
            *that specific commit* are considered.

    Returns:
        List of finding dicts (copies) that need status updates.
    """
    updates: List[Dict[str, Any]] = []

    for finding in existing_findings:
        status = finding.get("status", "open")
        if status != "open":
            continue

        fhash = finding.get("finding_hash", "")
        file_path = finding.get("file", "")
        is_candidate = finding.get("passive_fix_candidate", False)
        present_in_current = fhash in current_hashes

        if present_in_current:
            # Finding reappeared — clear candidate flag if it was set
            if is_candidate:
                updated = dict(finding)
                updated["passive_fix_candidate"] = False
                updates.append(updated)
            continue

        # Finding is absent from current run — determine if its file changed
        last_commit = finding.get("last_seen_commit", "")
        if changed_files_by_commit is not None:
            # Per-finding lookup: only files changed since THIS finding's commit
            per_finding_changed = changed_files_by_commit.get(last_commit, set())
            file_changed = file_path in per_finding_changed
        elif changed_files is not None:
            # Legacy flat set
            file_changed = file_path in changed_files
        else:
            file_changed = False

        if not file_changed:
            # File not touched — no inference possible
            continue

        updated = dict(finding)
        if is_candidate:
            # Second consecutive absence — confirm fix
            updated["status"] = "fixed"
        else:
            # First absence — mark as candidate
            updated["passive_fix_candidate"] = True

        updates.append(updated)

    return updates
