"""High-level ACP (Agent Client Protocol) client.

Wraps JsonRpcTransport with ACP-specific methods: initialize, session
management, prompt dispatch, and cancellation.
"""
from __future__ import annotations

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
        self._accumulated_text: List[str] = []
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

    def start(self) -> None:
        """Spawn the agent subprocess."""
        self._transport.start(
            command=self._command,
            cwd=self._cwd,
            env=self._env,
            stderr_path=self._stderr_path,
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
        self._accumulated_text.clear()
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

        # Accumulate text content
        for block in update.content:
            if block.get("type") == "text" and block.get("text"):
                self._accumulated_text.append(block["text"])

        if update.state:
            self._session_state = update.state

        return update

    def collect_text(self) -> str:
        """Return all accumulated text from session/update notifications."""
        return "\n".join(self._accumulated_text)

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
        self._transport.close()
