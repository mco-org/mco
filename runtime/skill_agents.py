from __future__ import annotations

import json
from functools import lru_cache
from importlib.resources import files
from typing import Dict, FrozenSet, List, Tuple


@lru_cache(maxsize=1)
def _manifest() -> Dict[str, object]:
    text = files("runtime").joinpath("data", "skill_calling_agents.json").read_text(encoding="utf-8")
    payload = json.loads(text)
    agents = payload.get("agents")
    if not isinstance(agents, dict):
        raise ValueError("invalid skill calling agent manifest")
    return agents


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
