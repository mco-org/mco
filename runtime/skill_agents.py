from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Dict, FrozenSet, List, Optional, Tuple


@lru_cache(maxsize=1)
def _payload() -> Dict[str, object]:
    text = files("runtime").joinpath("data", "skill_calling_agents.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    if not isinstance(payload, dict):
        raise ValueError("invalid skill calling agent manifest")
    return payload


@lru_cache(maxsize=1)
def _manifest() -> Dict[str, object]:
    payload = _payload()
    agents = payload.get("agents")
    if not isinstance(agents, dict):
        raise ValueError("invalid skill calling agent manifest")
    return agents


def skills_cli_package() -> str:
    value = str(_payload().get("skills_cli_package") or "").strip()
    if not value:
        raise ValueError("skill calling agent manifest is missing skills_cli_package")
    return value


def known_skill_agents() -> FrozenSet[str]:
    return frozenset(_manifest().keys())


def calling_agent_binaries() -> List[Tuple[str, str]]:
    pairs: List[Tuple[str, str]] = []
    for agent_id, spec in _manifest().items():
        if not isinstance(spec, dict):
            continue
        binaries = spec.get("binaries", [])
        if not isinstance(binaries, list):
            continue
        for binary in binaries:
            value = str(binary).strip()
            if value:
                pairs.append((value, str(agent_id)))
    return pairs


def calling_agent_skill_directories() -> List[Tuple[str, str, str, Optional[str]]]:
    locations: List[Tuple[str, str, str, Optional[str]]] = []
    for agent_id, spec in _manifest().items():
        if not isinstance(spec, dict):
            continue
        config_home_env = spec.get("config_home_env")
        env_name = str(config_home_env).strip() if config_home_env else None
        for key, scope in (
            ("global_skill_directories", "global"),
            ("legacy_global_skill_directories", "legacy-global"),
            ("project_skill_directories", "project"),
        ):
            directories = spec.get(key, [])
            if not isinstance(directories, list):
                continue
            for directory in directories:
                value = str(directory).strip()
                if value:
                    locations.append((str(agent_id), scope, value, env_name))
    return locations
