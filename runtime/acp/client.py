"""High-level ACP (Agent Client Protocol) client.

Wraps JsonRpcTransport with ACP-specific methods: initialize, session
management, prompt dispatch, and cancellation.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from .transport import JsonRpcTransport, JsonRpcError, TransportClosed


_CLIENT_NAME = "mco"
_PROTOCOL_VERSION = "0.1"


def _client_version() -> str:
    """Read version from package metadata, fall back to unknown."""
    try:
        from importlib.metadata import version
        return version("mco")
    except Exception:
        return "unknown"


@dataclass
class AgentInfo:
    name: str = ""
    version: str = ""


@dataclass
class SessionUpdate:
    """A session/update notification from the agent."""
    session_id: str = ""
    state: str = ""  # "working" | "idle" | "error"
    content: List[Dict[str, Any]] = field(default_factory=list)
    raw: Dict[str, Any] = field(default_factory=dict)


class ContentAccumulator:
    """Accumulates typed ACP content blocks with structured rendering."""

    def __init__(self) -> None:
        self._blocks: List[Dict[str, Any]] = []

    def add_block(self, block: Dict[str, Any]) -> None:
        self._blocks.append(block)

    def clear(self) -> None:
        self._blocks.clear()

    def collect_text(self) -> str:
        """Return only text-type content (backward compatible)."""
        parts = []
        for b in self._blocks:
            if b.get("type") == "text" and b.get("text"):
                parts.append(b["text"])
        return "\n".join(parts)

    def collect_rendered(self) -> str:
        """Return all content with type labels for human reading."""
        parts: List[str] = []
        for b in self._blocks:
            btype = b.get("type", "unknown")
            if btype == "text":
                parts.append(b.get("text", ""))
            elif btype == "thinking":
                parts.append("[Thinking] {}".format(b.get("text", "")))
            elif btype == "tool_call":
                name = b.get("name", "unknown")
                args = b.get("arguments", {})
                parts.append("[Tool: {}] {}".format(name, json.dumps(args)))
            elif btype == "tool_result":
                parts.append("[Tool Result] {}".format(b.get("output", "")))
            elif btype == "diff":
                path = b.get("path", "")
                content = b.get("content", "")
                parts.append("[Diff: {}]\n{}".format(path, content))
            else:
                text = b.get("text", "") or b.get("content", "")
                if text:
                    parts.append("[{}] {}".format(btype, text))
        return "\n".join(parts)


class AcpClient:
    """Client for the Agent Client Protocol (JSON-RPC over stdio).

    Usage:
        client = AcpClient(command=["claude", "--acp"], cwd="/path/to/repo")
        client.start()
        agent = client.initialize()
        session_id = client.new_session()
        client.prompt(session_id, "Review auth.py")
        while True:
            update = client.next_update(timeout=5.0)
            if update and update.state == "idle":
                break
        text = client.collect_text()
        client.close()
    """

    def __init__(
        self,
        command: List[str],
        cwd: str = ".",
        env: Optional[Dict[str, str]] = None,
        stderr_path: Optional[str] = None,
    ) -> None:
        self._command = command
        self._cwd = cwd
        self._env = env
        self._stderr_path = stderr_path
        self._transport = JsonRpcTransport()
        self._agent_info: Optional[AgentInfo] = None
        self._accumulator = ContentAccumulator()
        self._session_state: str = ""

    @property
    def pid(self) -> Optional[int]:
        return self._transport.pid

    @property
    def alive(self) -> bool:
        return self._transport.alive

    @property
    def agent_info(self) -> Optional[AgentInfo]:
        return self._agent_info

    def start(self, allow_paths: Optional[List[str]] = None) -> None:
        """Spawn the agent subprocess and register fs/terminal handlers."""
        self._transport.start(
            command=self._command,
            cwd=self._cwd,
            env=self._env,
            stderr_path=self._stderr_path,
        )
        # Register ACP request handlers for bidirectional communication
        from .handlers import handle_fs_read, handle_fs_write, TerminalManager
        paths = allow_paths or ["."]
        cwd = self._cwd
        self._terminal_manager = TerminalManager(cwd)
        self._transport.register_handler(
            "fs/read_text_file",
            lambda params: handle_fs_read(params, cwd, paths),
        )
        self._transport.register_handler(
            "fs/write_text_file",
            lambda params: handle_fs_write(params, cwd, paths),
        )
        self._transport.register_handler(
            "terminal/create",
            lambda params: {"terminalId": self._terminal_manager.create(params.get("command", ""))},
        )
        self._transport.register_handler(
            "terminal/output",
            lambda params: {"output": self._terminal_manager.output(params.get("terminalId", ""))},
        )
        self._transport.register_handler(
            "terminal/wait_for_exit",
            lambda params: {"exitCode": self._terminal_manager.wait_for_exit(params.get("terminalId", ""))},
        )
        self._transport.register_handler(
            "terminal/kill",
            lambda params: (self._terminal_manager.kill(params.get("terminalId", "")), {})[1],
        )
        self._transport.register_handler(
            "terminal/release",
            lambda params: (self._terminal_manager.release(params.get("terminalId", "")), {})[1],
        )

    def initialize(self, timeout: float = 30.0) -> AgentInfo:
        """Send ACP initialize handshake.

        Returns agent info on success.
        """
        result = self._transport.send_request(
            method="initialize",
            params={
                "protocolVersion": _PROTOCOL_VERSION,
                "clientInfo": {
                    "name": _CLIENT_NAME,
                    "version": _client_version(),
                },
                "capabilities": {},
            },
            timeout=timeout,
        )

        info = (result or {}).get("agentInfo", {})
        self._agent_info = AgentInfo(
            name=info.get("name", ""),
            version=info.get("version", ""),
        )
        return self._agent_info

    def new_session(
        self,
        working_directory: Optional[str] = None,
        timeout: float = 10.0,
    ) -> str:
        """Create a new ACP session. Returns session ID."""
        params: Dict[str, Any] = {}
        if working_directory:
            params["workingDirectory"] = working_directory

        result = self._transport.send_request(
            method="session/new",
            params=params,
            timeout=timeout,
        )
        return (result or {}).get("sessionId", "")

    def prompt(
        self,
        session_id: str,
        text: str,
        timeout: float = 600.0,
    ) -> None:
        """Send a prompt to a session and collect all response text.

        Blocks until both (a) the RPC response returns AND (b) session state
        reaches "idle" (or drain window expires). This handles the case where
        the RPC response arrives before the final session/update notification.
        """
        self._accumulator.clear()
        self._session_state = "working"

        self._transport.send_request(
            method="session/prompt",
            params={
                "sessionId": session_id,
                "content": [{"type": "text", "text": text}],
            },
            timeout=timeout,
        )

        # RPC response returned, but notifications may still be in flight.
        # Keep polling until we see idle state or the deadline expires.
        deadline = time.monotonic() + 5.0
        while self._session_state != "idle" and time.monotonic() < deadline:
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                break
            self.next_update(timeout=min(remaining, 0.5))

    def cancel(self, session_id: str, timeout: float = 10.0) -> None:
        """Cancel the current prompt in a session."""
        try:
            self._transport.send_request(
                method="session/cancel",
                params={"sessionId": session_id},
                timeout=timeout,
            )
        except (JsonRpcError, TransportClosed, TimeoutError):
            pass

    def next_update(self, timeout: float = 1.0) -> Optional[SessionUpdate]:
        """Read the next session/update notification.

        Returns None if no update within timeout.
        """
        msg = self._transport.receive_notification(timeout=timeout)
        if msg is None:
            return None

        method = msg.get("method", "")
        if method != "session/update":
            # Not a session update — re-queue or ignore
            return None

        params = msg.get("params", {})
        update = SessionUpdate(
            session_id=params.get("sessionId", ""),
            state=params.get("state", ""),
            content=params.get("content", []),
            raw=msg,
        )

        # Accumulate content blocks
        for block in update.content:
            self._accumulator.add_block(block)

        if update.state:
            self._session_state = update.state

        return update

    def collect_text(self) -> str:
        """Return all accumulated text from session/update notifications."""
        return self._accumulator.collect_text()

    def collect_rendered(self) -> str:
        """Return all accumulated content with type labels for human display."""
        return self._accumulator.collect_rendered()

    def drain_updates(self) -> List[SessionUpdate]:
        """Drain all pending session/update notifications."""
        updates: List[SessionUpdate] = []
        while True:
            update = self.next_update(timeout=0.01)
            if update is None:
                break
            updates.append(update)
        return updates

    def close(self) -> None:
        """Shut down the agent process."""
        if hasattr(self, "_terminal_manager"):
            self._terminal_manager.close_all()
        self._transport.close()
