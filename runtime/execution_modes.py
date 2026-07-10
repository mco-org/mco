from __future__ import annotations

from typing import Dict, Optional


EXECUTION_MODES = ("read_only", "write", "yolo")

_PROVIDER_EXECUTION_PERMISSIONS: Dict[str, Dict[str, Optional[Dict[str, str]]]] = {
    "claude": {
        "read_only": {"permission_mode": "plan"},
        "write": {"permission_mode": "acceptEdits"},
        "yolo": {"permission_mode": "bypassPermissions"},
    },
    "codex": {
        "read_only": {"sandbox": "read-only", "approval_policy": "never"},
        "write": {"sandbox": "workspace-write", "approval_policy": "never"},
        "yolo": {"bypass": "true"},
    },
    "gemini": {
        "read_only": {"approval_mode": "plan"},
        "write": {"approval_mode": "auto_edit"},
        "yolo": {"approval_mode": "yolo"},
    },
    "opencode": {
        "read_only": {"agent_mode": "plan", "auto": "false"},
        "write": {"agent_mode": "build", "auto": "true"},
        "yolo": {"agent_mode": "build", "auto": "true"},
    },
    "qwen": {
        "read_only": {"approval_mode": "plan"},
        "write": {"approval_mode": "auto-edit"},
        "yolo": {"approval_mode": "yolo"},
    },
    "hermes": {"read_only": None, "write": None, "yolo": {"yolo": "true"}},
    "pi": {
        "read_only": {"tool_profile": "read_only"},
        "write": {"tool_profile": "write"},
        "yolo": {"tool_profile": "yolo"},
    },
    "copilot": {
        "read_only": {"access": "read_only"},
        "write": {"access": "write"},
        "yolo": {"access": "yolo"},
    },
    "grok": {
        "read_only": {"permission_mode": "plan"},
        "write": {"permission_mode": "acceptEdits"},
        "yolo": {"permission_mode": "bypassPermissions"},
    },
    "cursor": {
        "read_only": {"mode": "ask", "force": "false", "sandbox": "enabled"},
        "write": {"mode": "agent", "force": "true", "sandbox": "enabled"},
        "yolo": {"mode": "agent", "force": "true", "sandbox": "disabled"},
    },
}


def execution_permissions(provider: str, execution_mode: str) -> Optional[Dict[str, str]]:
    modes = _PROVIDER_EXECUTION_PERMISSIONS.get(provider)
    if modes is None:
        return None
    permissions = modes.get(execution_mode)
    return None if permissions is None else dict(permissions)


__all__ = ["EXECUTION_MODES", "execution_permissions"]
