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
        "reason": "Hermes oneshot approval semantics are provider-controlled and bypass interactive approval",
    },
    "pi": {
        "level": "read_only",
        "reason": "default command locks Pi tools to read,grep,find,ls and disables extensions",
    },
    "copilot": {
        "level": "approval_bypass",
        "reason": "default command enables all Copilot tools and disables interactive questions",
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
    if provider == "grok" and "approval_mode" in permissions:
        approval_mode = str(permissions["approval_mode"]).strip()
        levels = {"ask": "workspace_write", "always-approve": "approval_bypass"}
        return {
            "level": levels.get(approval_mode, "unknown"),
            "reason": "effective Grok approval_mode={}".format(approval_mode),
        }
    if provider == "cursor":
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
