from __future__ import annotations

from typing import Dict, Mapping, Optional


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
        "level": "read_only",
        "reason": "default adapter command uses Gemini plan approval mode",
    },
    "opencode": {
        "level": "read_only",
        "reason": "default adapter command uses OpenCode plan agent mode",
    },
    "qwen": {
        "level": "read_only",
        "reason": "default adapter command uses Qwen plan approval mode",
    },
    "hermes": {
        "level": "approval_bypass",
        "reason": "Hermes oneshot approval semantics are provider-controlled and bypass interactive approval",
    },
    "pi": {
        "level": "read_only",
        "reason": "default command locks Pi tools to read,grep,find,ls and disables extensions",
    },
    "copilot": {
        "level": "read_only",
        "reason": "default adapter command denies Copilot write and shell tools",
    },
    "grok": {
        "level": "workspace_write",
        "reason": "default headless command keeps Grok approval prompts enabled; granted tools may modify the workspace",
    },
    "cursor": {
        "level": "read_only",
        "reason": "default headless command uses Cursor ask mode without --force",
    },
}


def provider_risk(provider: str, transport: str = "shim") -> Dict[str, str]:
    if transport == "acp":
        return {
            "level": "unknown",
            "reason": "ACP permissions are provider-controlled unless an explicit supported override is applied",
        }
    risk = _PROVIDER_RISKS.get(str(provider), None)
    if risk is None:
        return {
            "level": "unknown",
            "reason": "custom or unclassified provider; inspect its command before execution",
        }
    return dict(risk)


def effective_provider_risk(
    provider: str,
    applied_permissions: Optional[Mapping[str, str]] = None,
    transport: str = "shim",
) -> Dict[str, str]:
    permissions = applied_permissions or {}
    if provider == "claude" and "permission_mode" in permissions:
        permission_mode = str(permissions["permission_mode"]).strip()
        levels = {
            "plan": "read_only",
            "acceptEdits": "workspace_write",
            "bypassPermissions": "approval_bypass",
        }
        level = levels.get(permission_mode, "unknown")
        return {
            "level": level,
            "reason": "effective Claude permission_mode={}".format(permission_mode),
        }
    if provider == "codex" and permissions.get("bypass") == "true":
        return {
            "level": "elevated",
            "reason": "effective Codex bypass=true disables approvals and sandboxing",
        }
    if provider == "codex" and "sandbox" in permissions:
        sandbox = str(permissions["sandbox"]).strip()
        levels = {
            "read-only": "read_only",
            "workspace-write": "workspace_write",
            "danger-full-access": "elevated",
        }
        level = levels.get(sandbox, "unknown")
        return {
            "level": level,
            "reason": "effective Codex sandbox={}".format(sandbox),
        }
    if provider in ("gemini", "qwen") and "approval_mode" in permissions:
        approval_mode = str(permissions["approval_mode"]).strip()
        levels = {
            "plan": "read_only",
            "default": "workspace_write",
            "auto_edit": "workspace_write",
            "auto-edit": "workspace_write",
            "auto": "workspace_write",
            "yolo": "approval_bypass",
        }
        return {
            "level": levels.get(approval_mode, "unknown"),
            "reason": "effective {} approval_mode={}".format(provider, approval_mode),
        }
    if provider == "opencode" and "agent_mode" in permissions:
        agent_mode = str(permissions["agent_mode"]).strip()
        auto = str(permissions.get("auto", "false")).strip()
        if auto == "true":
            level = "approval_bypass"
        else:
            level = {"plan": "read_only", "build": "workspace_write"}.get(agent_mode, "unknown")
        return {
            "level": level,
            "reason": "effective OpenCode agent_mode={} auto={}".format(agent_mode, auto),
        }
    if provider == "pi" and "tool_profile" in permissions:
        tool_profile = str(permissions["tool_profile"]).strip()
        levels = {"read_only": "read_only", "write": "workspace_write", "yolo": "approval_bypass"}
        return {
            "level": levels.get(tool_profile, "unknown"),
            "reason": "effective Pi tool_profile={}".format(tool_profile),
        }
    if provider == "copilot" and "access" in permissions:
        access = str(permissions["access"]).strip()
        levels = {"read_only": "read_only", "write": "workspace_write", "yolo": "approval_bypass"}
        return {
            "level": levels.get(access, "unknown"),
            "reason": "effective Copilot access={}".format(access),
        }
    if provider == "hermes" and permissions.get("yolo") == "true":
        return {
            "level": "approval_bypass",
            "reason": "effective Hermes yolo=true bypasses approval prompts",
        }
    if provider == "grok" and "permission_mode" in permissions:
        permission_mode = str(permissions["permission_mode"]).strip()
        levels = {
            "plan": "read_only",
            "acceptEdits": "workspace_write",
            "bypassPermissions": "approval_bypass",
        }
        return {
            "level": levels.get(permission_mode, "unknown"),
            "reason": "effective Grok permission_mode={}".format(permission_mode),
        }
    if provider == "grok" and "approval_mode" in permissions:
        approval_mode = str(permissions["approval_mode"]).strip()
        levels = {"ask": "workspace_write", "always-approve": "approval_bypass"}
        return {
            "level": levels.get(approval_mode, "unknown"),
            "reason": "effective Grok approval_mode={}".format(approval_mode),
        }
    if provider == "cursor":
        sandbox = str(permissions.get("sandbox", "enabled")).strip()
        if sandbox == "disabled":
            return {
                "level": "elevated",
                "reason": "effective Cursor sandbox=disabled permits access outside the workspace boundary",
            }
        force = str(permissions.get("force", "false")).strip()
        if force == "true":
            return {
                "level": "approval_bypass",
                "reason": "effective Cursor force=true bypasses interactive approvals",
            }
        if force not in ("", "false"):
            return {
                "level": "unknown",
                "reason": "effective Cursor force={}".format(force),
            }
        if "mode" not in permissions:
            return provider_risk(provider, transport=transport)
        mode = str(permissions["mode"]).strip()
        levels = {"ask": "read_only", "plan": "read_only", "agent": "workspace_write"}
        return {
            "level": levels.get(mode, "unknown"),
            "reason": "effective Cursor mode={}".format(mode),
        }
    return provider_risk(provider, transport=transport)
