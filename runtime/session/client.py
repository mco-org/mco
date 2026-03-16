"""Session client — connect to daemon socket, send prompts, broadcast."""
from __future__ import annotations

import json
import socket
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from .state import SessionState, list_sessions, session_dir


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


def send_prompt(
    repo_root: str,
    name: str,
    prompt: str,
) -> Dict[str, Any]:
    """Send a prompt to a named session daemon.

    Returns {status, response, wall_clock_seconds} or {status, message} on error.
    """
    sock_path = _socket_path(repo_root, name)
    return _send_request(sock_path, {"action": "send", "prompt": prompt})


def ping_session(repo_root: str, name: str) -> bool:
    """Check if a session daemon is alive."""
    sock_path = _socket_path(repo_root, name)
    result = _send_request(sock_path, {"action": "ping"}, timeout=5.0)
    return result.get("status") == "pong"


def stop_session(repo_root: str, name: str) -> Dict[str, Any]:
    """Send shutdown to a session daemon."""
    sock_path = _socket_path(repo_root, name)
    return _send_request(sock_path, {"action": "shutdown"}, timeout=10.0)


def broadcast_prompt(
    repo_root: str,
    prompt: str,
) -> List[Dict[str, Any]]:
    """Send a prompt to ALL active sessions in parallel.

    Returns a list of {session_name, provider, status, response, wall_clock_seconds}.
    """
    sessions = list_sessions(repo_root)
    active = [s for s in sessions if s.status == "active"]

    if not active:
        return []

    results: List[Dict[str, Any]] = []

    def _send_one(session: SessionState) -> Dict[str, Any]:
        resp = send_prompt(repo_root, session.name, prompt)
        return {
            "session_name": session.name,
            "provider": session.provider,
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
                session = futures[future]
                results.append({
                    "session_name": session.name,
                    "provider": session.provider,
                    "status": "error",
                    "response": "",
                    "wall_clock_seconds": 0,
                    "message": str(exc),
                })

    return results
