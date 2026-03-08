from __future__ import annotations

from typing import Mapping

from .claude import ClaudeAdapter
from .codex import CodexAdapter
from .gemini import GeminiAdapter
from .opencode import OpenCodeAdapter
from .qwen import QwenAdapter


def adapter_registry() -> Mapping[str, ClaudeAdapter | CodexAdapter | GeminiAdapter | OpenCodeAdapter | QwenAdapter]:
    """Single source of truth for provider-id -> adapter mapping."""
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
