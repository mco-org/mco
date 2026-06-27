from __future__ import annotations

import re
from pathlib import Path
from typing import Dict, Iterable

from .contracts import ProviderId


ARTIFACT_LAYOUT_VERSION = "stage-a-v1"
ROOT_FILES = ("summary.md", "decision.md", "findings.json", "run.json")
ROOT_DIRS = ("providers", "raw")

# Allowed task-id characters: alphanumeric, hyphens, underscores, dots.
# Rejects: absolute paths, .. traversal, path separators, empty, control chars.
_VALID_TASK_ID_RE = re.compile(r"^[a-zA-Z0-9_\-.]+$")


def validate_task_id(task_id: str) -> None:
    """Validate task_id as a safe filesystem path segment.

    Raises ValueError if task_id is empty, contains path separators,
    absolute-path markers, .. traversal, "." (current-dir), or control characters.
    """
    if not task_id or not task_id.strip():
        raise ValueError("task_id must not be empty")
    if task_id == ".":
        raise ValueError("task_id must not be a single dot (current directory)")
    if "\x00" in task_id:
        raise ValueError("task_id contains null byte")
    if any(ord(ch) < 0x20 for ch in task_id):
        raise ValueError("task_id contains control characters")
    if task_id.startswith("/") or task_id.startswith("\\"):
        raise ValueError("task_id must not be an absolute path")
    if ".." in _split_path_segments(task_id):
        raise ValueError("task_id contains path traversal")
    if not _VALID_TASK_ID_RE.match(task_id):
        raise ValueError("task_id contains invalid characters (path separators not allowed)")


def _split_path_segments(value: str) -> list:
    """Split value by both forward and backslash separators."""
    return re.split(r"[/\\]", value)


def task_artifact_root(base_dir: str, task_id: str) -> Path:
    validate_task_id(task_id)
    return Path(base_dir) / task_id


def provider_artifact_name(provider: ProviderId) -> str:
    return f"{provider}.json"


def expected_paths(base_dir: str, task_id: str, providers: Iterable[ProviderId]) -> Dict[str, Path]:
    root = task_artifact_root(base_dir, task_id)
    paths: Dict[str, Path] = {"root": root}

    for filename in ROOT_FILES:
        paths[filename] = root / filename

    providers_dir = root / "providers"
    raw_dir = root / "raw"
    paths["providers_dir"] = providers_dir
    paths["raw_dir"] = raw_dir

    for provider in providers:
        paths[f"providers/{provider}.json"] = providers_dir / provider_artifact_name(provider)
        paths[f"raw/{provider}.stdout.log"] = raw_dir / f"{provider}.stdout.log"
        paths[f"raw/{provider}.stderr.log"] = raw_dir / f"{provider}.stderr.log"

    return paths

