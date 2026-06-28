from __future__ import annotations

from typing import Dict


RISK_LEVELS = ("read_only", "workspace_write", "elevated", "approval_bypass", "unknown")

_PROVIDER_RISKS: Dict[str, Dict[str, str]] = {
    "claude": {
        "level": "read_only",
        "reason": "default command uses Claude plan permission mode",
    },
    "codex": {
        "level": "workspace_write",
        "reason": "default command uses Codex workspace-write sandbox",
    },
    "gemini": {
        "level": "approval_bypass",
        "reason": "default command passes Gemini -y non-interactive approval flag",
    },
    "opencode": {
        "level": "workspace_write",
        "reason": "default command runs OpenCode in the repository working tree",
    },
    "qwen": {
        "level": "approval_bypass",
        "reason": "default command passes Qwen -y non-interactive approval flag",
    },
    "hermes": {
        "level": "approval_bypass",
        "reason": "explicit opt-in provider; Hermes oneshot approval semantics are provider-controlled",
    },
    "pi": {
        "level": "read_only",
        "reason": "default command locks Pi tools to read,grep,find,ls and disables extensions",
    },
}


def provider_risk(provider: str) -> Dict[str, str]:
    risk = _PROVIDER_RISKS.get(str(provider), None)
    if risk is None:
        return {
            "level": "unknown",
            "reason": "custom or unclassified provider; inspect its command before execution",
        }
    return dict(risk)
