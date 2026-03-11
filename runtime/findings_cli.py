"""Findings subcommand: list and confirm findings stored in evermemos.

Provides CLI-accessible operations on persisted findings without running
a full review cycle.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


def list_findings(
    client: Any,
    space: str,
    status_filter: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Fetch and filter findings from evermemos history.

    Args:
        client: EverMemosClient instance.
        space: Full space_id (e.g. "coding:org--repo--findings").
        status_filter: If set, only return findings with this status.

    Returns:
        List of deserialized finding dicts.
    """
    from .bridge.evermemos_client import EverMemosClient

    raw_history = client.fetch_history(
        space=space, memory_type="episodic_memory", limit=100
    )

    # Parse all findings, then deduplicate by finding_hash (keep latest)
    all_findings: List[Dict[str, Any]] = []
    for item in raw_history:
        content = item.get("content", "")
        if not EverMemosClient.is_finding_entry(content):
            continue
        try:
            finding = EverMemosClient.deserialize_finding(content)
        except (ValueError, Exception):
            continue
        all_findings.append(finding)

    # Deduplicate: keep only the latest version of each finding_hash
    by_hash: Dict[str, Dict[str, Any]] = {}
    for f in all_findings:
        fhash = f.get("finding_hash", "")
        if fhash:
            by_hash[fhash] = f
        else:
            by_hash[id(f)] = f  # no hash, keep as-is
    deduped = list(by_hash.values())

    if status_filter is not None:
        return [f for f in deduped if f.get("status") == status_filter]
    return deduped


def confirm_finding(
    client: Any,
    space: str,
    finding_hash: str,
    new_status: str,
) -> bool:
    """Update the status of a finding identified by its hash.

    Args:
        client: EverMemosClient instance.
        space: Full space_id.
        finding_hash: The finding_hash value to match.
        new_status: New status string (e.g. "accepted", "rejected", "wontfix").

    Returns:
        True if the finding was found and updated, False otherwise.
    """
    from .bridge.evermemos_client import EverMemosClient

    all_findings = list_findings(client, space)
    target = None
    for f in all_findings:
        if f.get("finding_hash") == finding_hash:
            target = f
            break

    if target is None:
        return False

    target["status"] = new_status
    serialized = EverMemosClient.serialize_finding(target)
    client.remember(space=space, content=serialized)
    return True


def render_findings_table(findings: List[Dict[str, Any]]) -> str:
    """Format findings as a human-readable table.

    Columns: Hash (first 12 chars), Status, Severity, Title, File.

    Returns:
        Formatted table string.
    """
    header = f"{'Hash':<14} {'Status':<12} {'Severity':<10} {'Title':<40} {'File'}"
    separator = "-" * len(header)
    lines = [header, separator]

    for f in findings:
        raw_hash = f.get("finding_hash", "")
        # Strip "sha256:" prefix for display, show first 12 hex chars
        display_hash = raw_hash
        if display_hash.startswith("sha256:"):
            display_hash = display_hash[7:]
        display_hash = display_hash[:12]

        status = f.get("status", "open")
        severity = f.get("severity", "medium")
        title = f.get("title", "")
        if len(title) > 38:
            title = title[:35] + "..."
        file_path = f.get("file", "")

        lines.append(
            f"{display_hash:<14} {status:<12} {severity:<10} {title:<40} {file_path}"
        )

    return "\n".join(lines)
