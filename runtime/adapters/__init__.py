from __future__ import annotations

from typing import Any, Dict, Mapping

from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .gemini import GeminiAdapter
from .opencode import OpenCodeAdapter
from .qwen import QwenAdapter


def adapter_registry(
    transport: str = "shim",
) -> Mapping[str, Any]:
    """Single source of truth for provider-id -> adapter mapping.

    transport: "shim" (default, stdout parsing), "acp" (Agent Client Protocol).
    """
    if transport == "acp":
        from ..acp.adapter import AcpAdapter, _ACP_COMMANDS
        registry: Dict[str, Any] = {}
        # Providers with known ACP commands get ACP adapters
        for provider_id, acp_cmd in _ACP_COMMANDS.items():
            registry[provider_id] = AcpAdapter(
                provider_id=provider_id,
                binary_name=acp_cmd[0],
                acp_command=acp_cmd,
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
