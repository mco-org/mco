"""Forget cleaner: removes rejected findings from evermemos memory.

Rejected findings should not pollute future recall results. This module
iterates through findings and calls client.forget() for each rejected
finding that has a memory_id. wontfix findings are preserved as they
represent accepted risks.
"""
from __future__ import annotations

import sys
from typing import Any, Dict, List


def clean_rejected_findings(
    client: Any,
    findings: List[Dict[str, Any]],
    space: str,
) -> Dict[str, int]:
    """Remove rejected findings from evermemos memory.

    Args:
        client: An evermemos client with a forget(memory_ids, space) method.
        findings: List of finding dicts, each with at least a "status" key.
        space: The evermemos space to forget from.

    Returns:
        {"forgotten_count": N, "skipped_no_id": M}
    """
    forgotten_count = 0
    skipped_no_id = 0

    for finding in findings:
        if finding.get("status") != "rejected":
            continue

        memory_id = finding.get("memory_id")
        if not memory_id:
            skipped_no_id += 1
            continue

        try:
            client.forget(memory_ids=[memory_id], space=space)
            forgotten_count += 1
        except Exception as exc:
            print(
                f"[mco-bridge] forget failed for memory_id={memory_id}: {exc}",
                file=sys.stderr,
            )

    return {"forgotten_count": forgotten_count, "skipped_no_id": skipped_no_id}
