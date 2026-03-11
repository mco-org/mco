"""Bridge-layer data structures for finding persistence."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional


@dataclass
class PersistedFinding:
    """A finding with lifecycle state, stored in evermemos."""
    finding_hash: str
    category: str
    severity: str
    title: str
    description: str
    file: str
    line: Optional[int]
    detected_by: List[str]
    occurrence_count: int
    first_seen: str
    last_seen: str
    last_seen_commit: str
    status: str  # open | fixed | accepted | rejected | wontfix
    confidence: float
    passive_fix_candidate: bool = False
    memory_id: Optional[str] = None
    request_id: Optional[str] = None

    VALID_STATUSES = ("open", "fixed", "accepted", "rejected", "wontfix")
