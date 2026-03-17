from __future__ import annotations

import shlex
from typing import Any, Dict, List, Mapping, Optional

from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .custom import CommandShimAdapter
from .gemini import GeminiAdapter
from .ollama import OllamaAdapter
from .opencode import OpenCodeAdapter
from .qwen import QwenAdapter


def _configured_agent_adapter(agent: Dict[str, Any]) -> Optional[Any]:
    name = str(agent.get("name", "")).strip()
    if not name:
        return None
    agent_transport = str(agent.get("transport", "shim")).strip().lower() or "shim"
    command_text = str(agent.get("command", "")).strip()
    model = str(agent.get("model", "")).strip()
    permission_keys = list(agent.get("permission_keys", []) or [])

    if agent_transport == "acp":
        if not command_text:
            return None
        from ..acp.adapter import AcpAdapter

        cmd = shlex.split(command_text)
        if not cmd:
            return None
        return AcpAdapter(
            provider_id=name,
            binary_name=cmd[0],
            acp_command=cmd,
            permission_keys=permission_keys,
        )

    if command_text:
        return CommandShimAdapter.from_command_text(
            provider_id=name,
            command_text=command_text,
            permission_keys=permission_keys,
        )

    if model:
        return OllamaAdapter(provider_id=name, model=model)

    return None


def adapter_registry(
    transport: str = "shim",
    extra_agents: Optional[Dict[str, List[str]]] = None,
    configured_agents: Optional[List[Dict[str, Any]]] = None,
) -> Mapping[str, Any]:
    """Single source of truth for provider-id -> adapter mapping.

    transport: "shim" (default, stdout parsing), "acp" (Agent Client Protocol).
    extra_agents: Optional dict of {name: [command, args...]} for custom ACP agents.
    """
    configured = list(configured_agents or [])

    if transport == "acp":
        from ..acp.adapter import AcpAdapter, _ACP_COMMANDS

        # Permission keys + CLI flags each provider's shim adapter supports.
        # ACP adapters inherit these so strict enforcement stays consistent,
        # and the flags are actually passed to the agent binary at launch.
        _PROVIDER_PERMISSIONS: Dict[str, Dict[str, Any]] = {
            "claude": {
                "keys": ClaudeAdapter().supported_permission_keys(),
                "flags": {"permission_mode": "--permission-mode"},
            },
            "codex": {
                "keys": CodexAdapter().supported_permission_keys(),
                "flags": {"sandbox": "--sandbox"},
            },
        }

        registry: Dict[str, Any] = {}
        # Built-in ACP providers
        for provider_id, acp_cmd in _ACP_COMMANDS.items():
            perm_info = _PROVIDER_PERMISSIONS.get(provider_id, {})
            registry[provider_id] = AcpAdapter(
                provider_id=provider_id,
                binary_name=acp_cmd[0],
                acp_command=acp_cmd,
                permission_keys=perm_info.get("keys", []),
                permission_flags=perm_info.get("flags", {}),
            )
        # Custom CLI agents — no inherited keys, only ACP-specific (terminal)
        if extra_agents:
            for name, cmd in extra_agents.items():
                registry[name] = AcpAdapter(
                    provider_id=name,
                    binary_name=cmd[0],
                    acp_command=cmd,
                )
        # Config-defined agents can choose their own transport
        for agent in configured:
            name = str(agent.get("name", "")).strip()
            if not name or name in registry:
                continue
            adapter = _configured_agent_adapter(agent)
            if adapter is not None:
                registry[name] = adapter
        # Providers without ACP support keep shim adapters
        shim_fallbacks = {
            "claude": ClaudeAdapter,
            "codex": CodexAdapter,
            "gemini": GeminiAdapter,
            "opencode": OpenCodeAdapter,
            "qwen": QwenAdapter,
        }
        for pid, adapter_cls in shim_fallbacks.items():
            if pid not in registry:
                registry[pid] = adapter_cls()
        return registry

    # Default: shim adapters plus configured agents
    registry = {
        "claude": ClaudeAdapter(),
        "codex": CodexAdapter(),
        "gemini": GeminiAdapter(),
        "opencode": OpenCodeAdapter(),
        "qwen": QwenAdapter(),
    }
    for agent in configured:
        name = str(agent.get("name", "")).strip()
        if not name or name in registry:
            continue
        adapter = _configured_agent_adapter(agent)
        if adapter is not None:
            registry[name] = adapter
    if extra_agents:
        from ..acp.adapter import AcpAdapter

        for name, cmd in extra_agents.items():
            if name in registry:
                continue
            registry[name] = AcpAdapter(
                provider_id=name,
                binary_name=cmd[0],
                acp_command=cmd,
            )
    return registry


__all__ = [
    "ClaudeAdapter",
    "CodexAdapter",
    "CommandShimAdapter",
    "GeminiAdapter",
    "OllamaAdapter",
    "OpenCodeAdapter",
    "QwenAdapter",
    "adapter_registry",
]
