from __future__ import annotations

import subprocess
from pathlib import Path
from typing import Callable, Dict, List, Optional, Sequence

from .skill_agents import known_skill_agents, skills_cli_package
from .skill_health import SKILL_FILENAME, SKILL_NAME, check_skill_health

SKILLS_CLI_PACKAGE = skills_cli_package()
SKILL_SYNC_TIMEOUT_SECONDS = 600


def normalize_skill_agents(values: Sequence[str]) -> List[str]:
    agents: List[str] = []
    seen: set[str] = set()
    allowed = known_skill_agents()
    for raw in values:
        value = str(raw).strip()
        if not value:
            continue
        if value.startswith("-") or any(ord(ch) < 32 for ch in value):
            raise ValueError("invalid skill agent: {}".format(value))
        if value not in allowed:
            raise ValueError("unknown skill agent: {}".format(value))
        if value not in seen:
            agents.append(value)
            seen.add(value)
    if not agents:
        raise ValueError("agent_selection_required")
    return agents


def build_skill_sync_argv(package_root: Path, agents: Sequence[str]) -> List[str]:
    normalized = normalize_skill_agents(agents)
    argv = [
        "npx",
        "-y",
        SKILLS_CLI_PACKAGE,
        "add",
        str(package_root),
        "--skill",
        SKILL_NAME,
        "--copy",
        "--global",
        "--yes",
    ]
    for agent in normalized:
        argv.extend(["--agent", agent])
    return argv


def bundled_skill_path(package_root: Path) -> Path:
    return package_root / "skills" / SKILL_NAME / SKILL_FILENAME


def read_bundled_skill(package_root: Path) -> str:
    path = bundled_skill_path(package_root)
    if not path.is_file():
        raise FileNotFoundError("bundled skill not found: {}".format(path))
    return path.read_text(encoding="utf-8")


def skill_status(
    package_root: Path,
    *,
    cwd: Optional[Path] = None,
) -> Dict[str, object]:
    skill_health, skill_drift = check_skill_health(
        enabled=True,
        package_root=package_root,
        cwd=cwd,
        reference_preference="bundled_only",
    )
    return {
        "skill_health": skill_health,
        "skill_drift": skill_drift,
    }


def sync_bundled_skill(
    package_root: Path,
    agents: Sequence[str],
    *,
    dry_run: bool = False,
    timeout_seconds: int = SKILL_SYNC_TIMEOUT_SECONDS,
    runner: Callable[..., subprocess.CompletedProcess[str]] = subprocess.run,
) -> Dict[str, object]:
    argv = build_skill_sync_argv(package_root, agents)
    normalized = normalize_skill_agents(agents)
    payload: Dict[str, object] = {
        "status": "planned" if dry_run else "pending",
        "skill": SKILL_NAME,
        "agents": normalized,
        "argv": argv,
        "dry_run": dry_run,
    }
    if dry_run:
        return payload

    try:
        completed = runner(
            argv,
            capture_output=True,
            text=True,
            check=False,
            timeout=timeout_seconds,
        )
    except subprocess.TimeoutExpired:
        payload["exit_code"] = 124
        payload["stderr"] = "skill sync timed out after {} seconds".format(timeout_seconds)
        payload["status"] = "failed"
        return payload

    payload["exit_code"] = completed.returncode
    payload["stdout"] = completed.stdout
    payload["stderr"] = completed.stderr
    payload["status"] = "installed" if completed.returncode == 0 else "failed"
    return payload
