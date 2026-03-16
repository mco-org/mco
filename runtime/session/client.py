"""Session client — connect to daemon socket, send prompts, broadcast."""
from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from .state import SessionState, session_dir


def _socket_path(repo_root: str, name: str) -> str:
    return str(session_dir(repo_root, name) / "sock")


def _send_request(
    sock_path: str,
    request: Dict[str, Any],
    timeout: float = 600.0,
) -> Dict[str, Any]:
    """Send a JSON-line request to a daemon socket and return the response."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    try:
        client.connect(sock_path)
        client.sendall(json.dumps(request).encode("utf-8") + b"\n")
        data = b""
        while b"\n" not in data:
            chunk = client.recv(65536)
            if not chunk:
                break
            data += chunk
        if not data:
            return {"status": "error", "message": "Empty response from daemon"}
        return json.loads(data.decode("utf-8").strip())
    except socket.timeout:
        return {"status": "error", "message": "Timeout waiting for daemon response"}
    except ConnectionRefusedError:
        return {"status": "error", "message": "Cannot connect to session daemon (socket refused)"}
    except FileNotFoundError:
        return {"status": "error", "message": "Session socket not found — session may not be running"}
    finally:
        client.close()


class _LineReader:
    """Buffered reader that splits on \\n, preserving leftover bytes between reads."""

    def __init__(self, sock: socket.socket) -> None:
        self._sock = sock
        self._buf = b""

    def read_one(self) -> Optional[Dict[str, Any]]:
        """Read and parse one JSON line. Returns None on EOF."""
        while b"\n" not in self._buf:
            chunk = self._sock.recv(65536)
            if not chunk:
                return None
            self._buf += chunk
        line, self._buf = self._buf.split(b"\n", 1)
        return json.loads(line.decode("utf-8"))


def send_prompt(
    repo_root: str,
    name: str,
    prompt: str,
) -> Dict[str, Any]:
    """Send a prompt to a named session daemon.

    The daemon sends two responses: a queued ack then the final result.
    Returns the final {status, response, wall_clock_seconds, request_id}.
    """
    sock_path = _socket_path(repo_root, name)
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(900.0)  # Long timeout for prompt execution
    try:
        client.connect(sock_path)
        client.sendall(json.dumps({"action": "send", "prompt": prompt}).encode("utf-8") + b"\n")
        reader = _LineReader(client)

        # First response: queued ack or immediate error
        first = reader.read_one()
        if first is None:
            return {"status": "error", "message": "Empty response from daemon"}
        if first.get("status") != "queued":
            # Immediate error (empty prompt, queue full, etc.)
            return first

        # Second response: actual result after worker processes
        second = reader.read_one()
        if second is None:
            return {"status": "error", "message": "Connection lost while waiting for result"}
        return second
    except socket.timeout:
        return {"status": "error", "message": "Timeout waiting for daemon response"}
    except ConnectionRefusedError:
        return {"status": "error", "message": "Cannot connect to session daemon (socket refused)"}
    except FileNotFoundError:
        return {"status": "error", "message": "Session socket not found — session may not be running"}
    finally:
        client.close()


def ping_session(repo_root: str, name: str) -> bool:
    """Check if a session daemon is alive."""
    sock_path = _socket_path(repo_root, name)
    result = _send_request(sock_path, {"action": "ping"}, timeout=5.0)
    return result.get("status") == "pong"


def stop_session(repo_root: str, name: str) -> Dict[str, Any]:
    """Send shutdown to a session daemon."""
    sock_path = _socket_path(repo_root, name)
    return _send_request(sock_path, {"action": "shutdown"}, timeout=10.0)


def cancel_session(repo_root: str, name: str) -> Dict[str, Any]:
    """Send cancel to a session daemon. Cancels running + queued requests."""
    sock_path = _socket_path(repo_root, name)
    return _send_request(sock_path, {"action": "cancel"}, timeout=10.0)


def queue_status(repo_root: str, name: str) -> Dict[str, Any]:
    """Query queue status of a session daemon."""
    sock_path = _socket_path(repo_root, name)
    return _send_request(sock_path, {"action": "queue"}, timeout=5.0)


def broadcast_prompt(
    repo_root: str,
    prompt: str,
) -> List[Dict[str, Any]]:
    """Send a prompt to ALL active sessions in parallel.

    Uses manager.list_sessions for PID liveness check (not raw state files).
    Returns a list of {session_name, provider, status, response, wall_clock_seconds}.
    """
    from .manager import list_sessions as list_sessions_live
    live_sessions = list_sessions_live(repo_root)
    active = [s for s in live_sessions if s["status"] == "active"]

    if not active:
        return []

    results: List[Dict[str, Any]] = []

    def _send_one(session_info: Dict[str, Any]) -> Dict[str, Any]:
        resp = send_prompt(repo_root, session_info["name"], prompt)
        return {
            "session_name": session_info["name"],
            "provider": session_info["provider"],
            "status": resp.get("status", "error"),
            "response": resp.get("response", ""),
            "wall_clock_seconds": resp.get("wall_clock_seconds", 0),
            "message": resp.get("message", ""),
        }

    with ThreadPoolExecutor(max_workers=len(active)) as executor:
        futures = {executor.submit(_send_one, s): s for s in active}
        for future in as_completed(futures):
            try:
                results.append(future.result())
            except Exception as exc:
                session_info = futures[future]
                results.append({
                    "session_name": session_info["name"],
                    "provider": session_info["provider"],
                    "status": "error",
                    "response": "",
                    "wall_clock_seconds": 0,
                    "message": str(exc),
                })

    return results
