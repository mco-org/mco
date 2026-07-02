from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

SKILL_NAME = "mco-cli"
SKILL_FILENAME = "SKILL.md"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _reference_skill_candidates(package_root: Path, cwd: Path) -> List[Path]:
    candidates = [
        cwd / "skills" / SKILL_NAME / SKILL_FILENAME,
        package_root / "skills" / SKILL_NAME / SKILL_FILENAME,
    ]
    unique: List[Path] = []
    seen: set[str] = set()
    for candidate in candidates:
        key = str(candidate.resolve()) if candidate.exists() else str(candidate)
        if key in seen:
            continue
        seen.add(key)
        unique.append(candidate)
    return unique


def _resolve_reference_skill(
    *,
    package_root: Path,
    cwd: Optional[Path] = None,
) -> Tuple[Optional[Path], str, Optional[str]]:
    search_root = cwd or Path.cwd()
    for candidate in _reference_skill_candidates(package_root, search_root):
        if candidate.is_file():
            return candidate, "ok", _file_sha256(candidate)
    return None, "reference_not_found", None


def _installation_candidates(*, cwd: Optional[Path] = None) -> List[Tuple[str, Path]]:
    search_root = cwd or Path.cwd()
    home = Path.home()
    candidates: List[Tuple[str, Path]] = [
        ("claude-global", home / ".claude" / "skills" / SKILL_NAME / SKILL_FILENAME),
        ("cursor-global", home / ".cursor" / "skills" / SKILL_NAME / SKILL_FILENAME),
        ("cursor-skills-cursor", home / ".cursor" / "skills-cursor" / SKILL_NAME / SKILL_FILENAME),
        ("codex-global", home / ".codex" / "skills" / SKILL_NAME / SKILL_FILENAME),
        ("project-cursor", search_root / ".cursor" / "skills" / SKILL_NAME / SKILL_FILENAME),
        ("project-claude", search_root / ".claude" / "skills" / SKILL_NAME / SKILL_FILENAME),
    ]
    claude_config = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
    if claude_config:
        candidates.append(
            ("claude-config-dir", Path(claude_config) / "skills" / SKILL_NAME / SKILL_FILENAME)
        )
    return candidates


def _installation_record(
    label: str,
    path: Path,
    *,
    reference_sha256: Optional[str],
) -> Dict[str, object]:
    record: Dict[str, object] = {
        "label": label,
        "path": str(path),
        "exists": path.is_file(),
    }
    if not path.is_file():
        record["status"] = "missing"
        record["reason"] = "file_not_found"
        return record

    sha256 = _file_sha256(path)
    record["sha256"] = sha256
    if reference_sha256 is None:
        record["status"] = "unknown"
        record["reason"] = "reference_unavailable"
        return record

    if sha256 == reference_sha256:
        record["status"] = "match"
        record["reason"] = "hash_match"
        return record

    record["status"] = "drift"
    record["reason"] = "hash_mismatch"
    return record


def check_skill_health(
    *,
    enabled: bool,
    package_root: Optional[Path] = None,
    cwd: Optional[Path] = None,
) -> Tuple[Dict[str, object], Dict[str, object]]:
    if not enabled:
        skipped = {
            "enabled": False,
            "status": "skipped",
            "reason": "pass --skill-health to enable skill health check",
        }
        return skipped, {"enabled": False, "status": "skipped", "reason": skipped["reason"]}

    root = package_root or Path(__file__).resolve().parent.parent
    reference_path, reference_status, reference_sha256 = _resolve_reference_skill(
        package_root=root,
        cwd=cwd,
    )
    reference_payload: Dict[str, object] = {
        "skill": SKILL_NAME,
        "filename": SKILL_FILENAME,
        "status": reference_status,
    }
    if reference_path is not None:
        reference_payload["path"] = str(reference_path)
    if reference_sha256 is not None:
        reference_payload["sha256"] = reference_sha256

    installations: List[Dict[str, object]] = []
    matched: List[str] = []
    drifted: List[str] = []
    missing: List[str] = []
    unknown: List[str] = []

    for label, path in _installation_candidates(cwd=cwd):
        record = _installation_record(label, path, reference_sha256=reference_sha256)
        installations.append(record)
        status = str(record.get("status") or "unknown")
        if status == "match":
            matched.append(label)
        elif status == "drift":
            drifted.append(label)
        elif status == "missing":
            missing.append(label)
        else:
            unknown.append(label)

    if reference_status != "ok":
        health_status = "unknown"
        health_reason = "reference_skill_not_found"
    elif drifted:
        health_status = "drift"
        health_reason = "installed_skill_hash_mismatch"
    elif matched:
        health_status = "ok"
        health_reason = "installed_skill_matches_reference"
    else:
        health_status = "ok"
        health_reason = "reference_found_no_local_installations"

    skill_health: Dict[str, object] = {
        "enabled": True,
        "status": health_status,
        "reason": health_reason,
        "reference": reference_payload,
        "installations": installations,
        "summary": {
            "matched": len(matched),
            "drifted": len(drifted),
            "missing": len(missing),
            "unknown": len(unknown),
        },
    }
    skill_drift: Dict[str, object] = {
        "enabled": True,
        "status": "drift" if drifted else "ok",
        "matched": matched,
        "drifted": drifted,
        "missing": missing,
        "unknown": unknown,
    }
    return skill_health, skill_drift
