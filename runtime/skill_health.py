from __future__ import annotations

import hashlib
import os
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Tuple

from .skill_agents import calling_agent_skill_directories

SKILL_NAME = "mco-cli"
SKILL_FILENAME = "SKILL.md"


def _file_sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _skill_file_hashes(skill_path: Path) -> Dict[str, str]:
    root = skill_path.parent
    return {
        path.relative_to(root).as_posix(): _file_sha256(path)
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _skill_tree_sha256(file_hashes: Mapping[str, str]) -> str:
    digest = hashlib.sha256()
    for relative_path, sha256 in sorted(file_hashes.items()):
        digest.update(relative_path.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha256.encode("ascii"))
        digest.update(b"\n")
    return digest.hexdigest()


def _reference_skill_candidates(
    package_root: Path,
    cwd: Path,
    *,
    reference_preference: str = "cwd_first",
) -> List[Path]:
    bundled = package_root / "skills" / SKILL_NAME / SKILL_FILENAME
    project = cwd / "skills" / SKILL_NAME / SKILL_FILENAME
    if reference_preference == "bundled_only":
        return [bundled]
    return [project, bundled]


def _resolve_reference_skill(
    *,
    package_root: Path,
    cwd: Optional[Path] = None,
    reference_preference: str = "cwd_first",
) -> Tuple[Optional[Path], str, Optional[str], Dict[str, str]]:
    search_root = cwd or Path.cwd()
    for candidate in _reference_skill_candidates(
        package_root,
        search_root,
        reference_preference=reference_preference,
    ):
        if candidate.is_file():
            file_hashes = _skill_file_hashes(candidate)
            return candidate, "ok", _skill_tree_sha256(file_hashes), file_hashes
    return None, "reference_not_found", None, {}


def _installation_candidates(*, cwd: Optional[Path] = None) -> List[Tuple[str, Path]]:
    search_root = cwd or Path.cwd()
    home = Path.home()
    candidates: List[Tuple[str, Path]] = []
    for agent_id, scope, directory, config_home_env in calling_agent_skill_directories():
        if scope == "project":
            skill_root = search_root / directory
            label = "project-{}".format(agent_id)
        else:
            skill_root = home / directory
            label = "{}-{}".format(agent_id, scope)
            if scope == "global" and config_home_env:
                config_home = os.environ.get(config_home_env, "").strip()
                if config_home:
                    skill_root = Path(config_home) / "skills"
        candidates.append((label, skill_root / SKILL_NAME / SKILL_FILENAME))
    return candidates


def _installation_record(
    label: str,
    path: Path,
    *,
    reference_sha256: Optional[str],
    reference_file_hashes: Mapping[str, str],
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

    if reference_sha256 is None:
        record["status"] = "unknown"
        record["reason"] = "reference_unavailable"
        return record

    installed_hashes = _skill_file_hashes(path)
    reference_files = set(reference_file_hashes)
    installed_files = set(installed_hashes)
    missing_files = sorted(reference_files - installed_files)
    extra_files = sorted(installed_files - reference_files)
    changed_files = sorted(
        relative_path
        for relative_path in reference_files & installed_files
        if installed_hashes[relative_path] != reference_file_hashes[relative_path]
    )

    record["sha256"] = _skill_tree_sha256(installed_hashes)
    if (
        not missing_files
        and not extra_files
        and not changed_files
        and record["sha256"] == reference_sha256
    ):
        record["status"] = "match"
        record["reason"] = "tree_hash_match"
        return record

    record["status"] = "drift"
    record["reason"] = "skill_tree_mismatch"
    if missing_files:
        record["missing_files"] = missing_files
    if extra_files:
        record["extra_files"] = extra_files
    if changed_files:
        record["changed_files"] = changed_files
    return record


def check_skill_health(
    *,
    enabled: bool,
    package_root: Optional[Path] = None,
    cwd: Optional[Path] = None,
    reference_preference: str = "cwd_first",
) -> Tuple[Dict[str, object], Dict[str, object]]:
    if not enabled:
        skipped = {
            "enabled": False,
            "status": "skipped",
            "reason": "pass --skill-health to enable skill health check",
        }
        return skipped, {"enabled": False, "status": "skipped", "reason": skipped["reason"]}

    root = package_root or Path(__file__).resolve().parent.parent
    reference_path, reference_status, reference_sha256, reference_file_hashes = _resolve_reference_skill(
        package_root=root,
        cwd=cwd,
        reference_preference=reference_preference,
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
        reference_payload["files"] = sorted(reference_file_hashes)

    installations: List[Dict[str, object]] = []
    matched: List[str] = []
    drifted: List[str] = []
    missing: List[str] = []
    unknown: List[str] = []

    for label, path in _installation_candidates(cwd=cwd):
        record = _installation_record(
            label,
            path,
            reference_sha256=reference_sha256,
            reference_file_hashes=reference_file_hashes,
        )
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
        health_status = "not_installed"
        health_reason = "no_local_skill_installations"

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
