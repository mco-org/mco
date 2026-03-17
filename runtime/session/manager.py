"""Session lifecycle manager — start, stop, list, resume sessions."""
from __future__ import annotations

import os
import subprocess
import sys
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


def _launch_daemon(repo_root: str, name: str) -> None:
    """Launch daemon as a detached subprocess that survives parent exit.

    Uses subprocess.Popen with start_new_session=True so the daemon
    gets its own process group and isn't killed when the parent exits.
    """
    daemon_code = (
        "import sys; sys.path.insert(0, {path!r}); "
        "from runtime.session.daemon import run_daemon; "
        "run_daemon({repo_root!r}, {name!r})"
    ).format(
        path=str(Path(__file__).resolve().parent.parent.parent),
        repo_root=repo_root,
        name=name,
    )

    # Redirect stdout/stderr to session log files
    sdir = session_dir(repo_root, name)
    sdir.mkdir(parents=True, exist_ok=True)
    stdout_log = open(sdir / "agent.stdout.log", "a")
    stderr_log = open(sdir / "agent.stderr.log", "a")

    try:
        subprocess.Popen(
            [sys.executable, "-c", daemon_code],
            stdout=stdout_log,
            stderr=stderr_log,
            stdin=subprocess.DEVNULL,
            start_new_session=True,  # Detach from parent process group
            close_fds=True,
        )
    finally:
        # Close file handles in parent process — child inherits its own copies
        stdout_log.close()
        stderr_log.close()


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

    # Launch daemon as a detached subprocess that outlives the parent.
    # Uses `python -c` to import and run the daemon function.
    _launch_daemon(repo_root, name)

    # Wait for socket to appear (daemon writes it on successful bind)
    sock_path = session_dir(repo_root, name) / "sock"
    for _ in range(100):  # 5 seconds
        if sock_path.exists():
            break
        time.sleep(0.05)

    # Verify daemon actually started
    state = load_state(repo_root, name)
    if state is None or not state.pid or not _is_pid_alive(state.pid):
        # Daemon failed to start
        if state:
            state.status = "crashed"
            state.pid = None
            save_state(repo_root, state)
        raise ValueError(
            "Session '{}' daemon failed to start. Check .mco/sessions/{}/agent.stderr.log".format(name, name)
        )

    return state


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


def ensure_session(
    provider: str,
    repo_root: str = ".",
    name: Optional[str] = None,
) -> SessionState:
    """Idempotent session create-or-return.

    If a session with the given name exists and is active with matching provider,
    return it. If stopped/crashed, resume it. If not found, create it.
    """
    if name is None:
        name = _auto_name(provider)

    repo_root = str(Path(repo_root).resolve())
    existing = load_state(repo_root, name)

    if existing is not None:
        if existing.status == "active" and existing.pid and _is_pid_alive(existing.pid):
            if existing.provider != provider:
                raise ValueError(
                    "Session '{}' exists with provider '{}', cannot ensure with '{}' (provider mismatch)".format(
                        name, existing.provider, provider,
                    )
                )
            return existing
        # Stopped or crashed — resume
        if existing.provider == provider:
            return resume_session(repo_root, name)

    # Not found — create
    return start_session(provider, repo_root=repo_root, name=name)


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

    _launch_daemon(repo_root, name)

    # Wait for socket
    sock_path = session_dir(repo_root, name) / "sock"
    for _ in range(100):
        if sock_path.exists():
            break
        time.sleep(0.05)

    state = load_state(repo_root, name)
    if state is None or not state.pid or not _is_pid_alive(state.pid):
        if state:
            state.status = "crashed"
            state.pid = None
            save_state(repo_root, state)
        raise ValueError("Session '{}' daemon failed to resume".format(name))

    return state
