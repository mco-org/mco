from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .gemini import GeminiAdapter
from .opencode import OpenCodeAdapter
from .qwen import QwenAdapter


def adapter_registry(
    transport: str = "shim",
    extra_agents: Optional[Dict[str, List[str]]] = None,
) -> Mapping[str, Any]:
    """Single source of truth for provider-id -> adapter mapping.

    transport: "shim" (default, stdout parsing), "acp" (Agent Client Protocol).
    extra_agents: Optional dict of {name: [command, args...]} for custom ACP agents.
    """
    if transport == "acp":
        from ..acp.adapter import AcpAdapter, _ACP_COMMANDS

        # Permission keys each provider's shim adapter declares.
        # ACP adapters inherit these so strict enforcement stays consistent.
        _SHIM_PERMISSION_KEYS: Dict[str, List[str]] = {
            "claude": ClaudeAdapter().supported_permission_keys(),
            "codex": CodexAdapter().supported_permission_keys(),
        }

        registry: Dict[str, Any] = {}
        # Built-in ACP providers
        for provider_id, acp_cmd in _ACP_COMMANDS.items():
            registry[provider_id] = AcpAdapter(
                provider_id=provider_id,
                binary_name=acp_cmd[0],
                acp_command=acp_cmd,
                permission_keys=_SHIM_PERMISSION_KEYS.get(provider_id, []),
            )
        # Custom agents — no inherited keys, only ACP-specific (terminal)
        if extra_agents:
            for name, cmd in extra_agents.items():
                registry[name] = AcpAdapter(
                    provider_id=name,
                    binary_name=cmd[0],
                    acp_command=cmd,
                )
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

    # Default: shim adapters
    return {
        "claude": ClaudeAdapter(),
        "codex": CodexAdapter(),
        "gemini": GeminiAdapter(),
        "opencode": OpenCodeAdapter(),
        "qwen": QwenAdapter(),
    }


__all__ = [
    "ClaudeAdapter",
    "CodexAdapter",
    "GeminiAdapter",
    "OpenCodeAdapter",
    "QwenAdapter",
    "adapter_registry",
]
