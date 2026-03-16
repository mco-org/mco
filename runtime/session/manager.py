"""Session lifecycle manager — start, stop, list, resume sessions."""
from __future__ import annotations

import multiprocessing
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

from .state import (
    SessionState,
    HistoryEntry,
    _auto_name,
    _now_iso,
    list_sessions as _list_sessions_from_state,
    load_state,
    save_state,
    session_dir,
)


def _is_pid_alive(pid: int) -> bool:
    """Check if a process with the given PID is running."""
    try:
        os.kill(pid, 0)
        return True
    except (OSError, ProcessLookupError):
        return False


def start_session(
    provider: str,
    repo_root: str = ".",
    name: Optional[str] = None,
) -> SessionState:
    """Start a new session daemon.

    Creates session directory, saves initial state, forks daemon process.
    Returns the session state.
    """
    if name is None:
        name = _auto_name(provider)

    repo_root = str(Path(repo_root).resolve())

    # Check if session already exists and is active
    existing = load_state(repo_root, name)
    if existing is not None and existing.status == "active":
        if existing.pid and _is_pid_alive(existing.pid):
            raise ValueError("Session '{}' is already active (pid={})".format(name, existing.pid))

    state = SessionState(
        name=name,
        provider=provider,
        status="active",
        repo_root=repo_root,
    )
    save_state(repo_root, state)

    # Fork daemon
    from .daemon import run_daemon
    proc = multiprocessing.Process(
        target=run_daemon,
        args=(repo_root, name),
        daemon=True,
    )
    proc.start()

    # Wait for socket to appear
    sock_path = session_dir(repo_root, name) / "sock"
    for _ in range(100):  # 5 seconds
        if sock_path.exists():
            break
        time.sleep(0.05)

    # Update PID (daemon writes its own, but we also track the process object PID)
    state = load_state(repo_root, name)
    if state is not None:
        return state

    return SessionState(name=name, provider=provider, status="active", repo_root=repo_root)


def stop_session(repo_root: str, name: str) -> bool:
    """Stop a session by sending shutdown to daemon. Returns True if stopped."""
    from .client import stop_session as client_stop
    result = client_stop(repo_root, name)
    if result.get("status") == "shutdown_ack":
        return True

    # If socket is gone, try SIGTERM on PID
    state = load_state(repo_root, name)
    if state and state.pid and _is_pid_alive(state.pid):
        try:
            os.kill(state.pid, 15)  # SIGTERM
        except (OSError, ProcessLookupError):
            pass
        state.status = "stopped"
        state.pid = None
        save_state(repo_root, state)
        return True

    # Already stopped
    if state:
        state.status = "stopped"
        state.pid = None
        save_state(repo_root, state)
    return True


def list_sessions(repo_root: str) -> List[Dict[str, Any]]:
    """List all sessions with live status check.

    Returns list of dicts with session info + actual liveness status.
    """
    sessions = _list_sessions_from_state(repo_root)
    result: List[Dict[str, Any]] = []
    for s in sessions:
        alive = bool(s.pid and _is_pid_alive(s.pid))
        actual_status = s.status
        if s.status == "active" and not alive:
            actual_status = "crashed"
            # Update on disk
            s.status = "crashed"
            s.pid = None
            save_state(repo_root, s)
        result.append({
            "name": s.name,
            "provider": s.provider,
            "status": actual_status,
            "pid": s.pid,
            "created_at": s.created_at,
            "last_active": s.last_active,
            "turn_count": s.turn_count,
        })
    return result


def resume_session(repo_root: str, name: str) -> SessionState:
    """Resume a stopped or crashed session.

    Restarts the daemon process. History is preserved on disk.
    """
    repo_root = str(Path(repo_root).resolve())
    state = load_state(repo_root, name)
    if state is None:
        raise ValueError("Session '{}' not found".format(name))

    if state.status == "active" and state.pid and _is_pid_alive(state.pid):
        return state  # Already running

    # Mark as active and restart daemon
    state.status = "active"
    save_state(repo_root, state)

    from .daemon import run_daemon
    proc = multiprocessing.Process(
        target=run_daemon,
        args=(repo_root, name),
        daemon=True,
    )
    proc.start()

    # Wait for socket
    sock_path = session_dir(repo_root, name) / "sock"
    for _ in range(100):
        if sock_path.exists():
            break
        time.sleep(0.05)

    return load_state(repo_root, name) or state
