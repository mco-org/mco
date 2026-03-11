"""Synchronous wrapper for evermemos-mcp tool calls.

All public methods are synchronous (asyncio.run internally).
Uses connect-per-call pattern: each tool invocation opens a temporary
MCP stdio session, makes the call, and closes. Simple and safe for
the ~3-5 calls Bridge makes per run.

Serialization convention:
- Findings: "[MCO-FINDING] <json>"
- Agent scores: "[MCO-AGENT-SCORE] <json>"
- Context/synthesis: plain text (no prefix)
"""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

MCO_FINDING_PREFIX = "[MCO-FINDING] "
MCO_AGENT_SCORE_PREFIX = "[MCO-AGENT-SCORE] "


class EverMemosClient:
    """Synchronous evermemos-mcp client for Bridge layer."""

    def __init__(self, api_key: Optional[str] = None) -> None:
        resolved_key = api_key or os.environ.get("EVERMEMOS_API_KEY", "")
        if not resolved_key:
            raise ValueError(
                "EVERMEMOS_API_KEY is required. "
                "Set it as an environment variable or pass api_key to EverMemosClient."
            )
        self.api_key = resolved_key

    def _ensure_mcp_sdk(self) -> None:
        """Fail fast with actionable message if MCP SDK is missing."""
        try:
            import mcp  # noqa: F401
        except ImportError:
            raise ImportError(
                "MCP SDK not installed. Install with: pip install mco[memory]\n"
                "The mcp package is required for --memory support."
            ) from None

    async def _call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Open a temporary MCP session, call one tool, close."""
        from mcp import ClientSession, StdioServerParameters  # type: ignore[import-untyped]
        from mcp.client.stdio import stdio_client  # type: ignore[import-untyped]

        server_params = StdioServerParameters(
            command="uvx",
            args=["evermemos-mcp@latest"],
            env={**os.environ, "EVERMEMOS_API_KEY": self.api_key},
        )
        async with stdio_client(server_params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(name, arguments)
                return result

    def _call_tool_sync(self, name: str, arguments: Dict[str, Any]) -> Any:
        """Synchronous wrapper around _call_tool."""
        self._ensure_mcp_sdk()
        return asyncio.run(self._call_tool(name, arguments))

    # ── Serialization helpers (static, no MCP needed) ──────────

    @staticmethod
    def serialize_finding(finding_dict: Dict[str, Any]) -> str:
        payload = json.dumps(finding_dict, ensure_ascii=False, sort_keys=True)
        return f"{MCO_FINDING_PREFIX}{payload}"

    @staticmethod
    def deserialize_finding(content: str) -> Dict[str, Any]:
        if not content.startswith(MCO_FINDING_PREFIX):
            raise ValueError("Not a finding entry")
        json_str = content[len(MCO_FINDING_PREFIX):]
        return json.loads(json_str)

    @staticmethod
    def is_finding_entry(content: str) -> bool:
        return content.startswith(MCO_FINDING_PREFIX)

    @staticmethod
    def serialize_agent_score(score_dict: Dict[str, Any]) -> str:
        payload = json.dumps(score_dict, ensure_ascii=False, sort_keys=True)
        return f"{MCO_AGENT_SCORE_PREFIX}{payload}"

    @staticmethod
    def deserialize_agent_score(content: str) -> Dict[str, Any]:
        if not content.startswith(MCO_AGENT_SCORE_PREFIX):
            raise ValueError("Not an agent score entry")
        json_str = content[len(MCO_AGENT_SCORE_PREFIX):]
        return json.loads(json_str)

    @staticmethod
    def is_agent_score_entry(content: str) -> bool:
        return content.startswith(MCO_AGENT_SCORE_PREFIX)

    # ── evermemos tool wrappers (all synchronous) ──────────────

    def list_spaces(self) -> List[str]:
        result = self._call_tool_sync("list_spaces", {})
        if isinstance(result, list):
            return result
        return []

    def briefing(self, space: str) -> Optional[str]:
        result = self._call_tool_sync("briefing", {"space_id": space})
        return str(result) if result else None

    def fetch_history(
        self, space: str, memory_type: str = "episodic_memory", limit: int = 100
    ) -> List[Dict[str, Any]]:
        result = self._call_tool_sync("fetch_history", {
            "space_id": space,
            "memory_type": memory_type,
            "limit": min(limit, 100),
        })
        if isinstance(result, list):
            return result
        return []

    def recall(self, space: str, query: str) -> Optional[str]:
        result = self._call_tool_sync("recall", {"space_id": space, "query": query})
        return str(result) if result else None

    def remember(self, space: str, content: str, flush: bool = False) -> Dict[str, Any]:
        args: Dict[str, Any] = {"space_id": space, "content": content}
        if flush:
            args["flush"] = True
        result = self._call_tool_sync("remember", args)
        if isinstance(result, dict):
            return result
        return {"request_id": None}

    def request_status(self, request_id: str) -> Dict[str, Any]:
        result = self._call_tool_sync("request_status", {"request_id": request_id})
        if isinstance(result, dict):
            return result
        return {}

    def forget(self, memory_ids: List[str], space: str) -> None:
        self._call_tool_sync("forget", {"memory_ids": memory_ids, "space_id": space})
