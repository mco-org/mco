"""Stable finding hash for cross-run deduplication.

Design rationale (vs MCO's _finding_dedupe_key):
- _finding_dedupe_key includes line+symbol for single-run merge precision
- compute_finding_hash excludes line+severity for cross-run stability:
  - line shifts on refactor
  - severity differs between agents (high vs critical)
  - title is included (normalized) to distinguish multiple findings in same file+category
"""
from __future__ import annotations

import hashlib
import re


def normalize_title(title: str) -> str:
    """Lowercase and collapse whitespace for hash stability."""
    return re.sub(r"\s+", " ", title.strip().lower())


def compute_finding_hash(repo: str, file_path: str, category: str, title: str) -> str:
    """Compute a stable SHA-256 hash for cross-run finding dedup."""
    normalized = "||".join([
        repo,
        file_path.replace("\\", "/"),
        category.lower().strip(),
        normalize_title(title),
    ])
    digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
    return f"sha256:{digest}"
