"""Session daemon — unix socket listener that dispatches prompts to agents."""
from __future__ import annotations

import json
import os
import signal
import socket
import time
from pathlib import Path
from typing import Any, Dict, Optional

from .state import (
    SessionState,
    HistoryEntry,
    _now_iso,
    append_history,
    build_history_prompt,
    load_history,
    load_state,
    save_state,
    session_dir,
)


_STALL_TIMEOUT_SECONDS = 900  # Match default provider stall timeout


def _socket_path(repo_root: str, name: str) -> str:
    return str(session_dir(repo_root, name) / "sock")


def _dispatch_prompt(
    provider: str,
    repo_root: str,
    prompt: str,
) -> Dict[str, Any]:
    """Run a single prompt through the provider adapter and return the result.

    Returns {success, response, wall_clock_seconds}.
    """
    from ..cli import SUPPORTED_PROVIDERS, _doctor_adapter_registry
    from ..contracts import TaskInput

    adapters = _doctor_adapter_registry()
    adapter = adapters.get(provider)
    if adapter is None:
        return {"success": False, "response": "", "error": "No adapter for provider: {}".format(provider)}

    presence = adapter.detect()
    if not presence.detected or not presence.auth_ok:
        return {"success": False, "response": "", "error": "Provider not available: {}".format(provider)}

    import tempfile
    import uuid
    with tempfile.TemporaryDirectory(prefix="mco-session-") as artifact_dir:
        unique_id = "session-{}-{}".format(int(time.time()), uuid.uuid4().hex[:8])
        task_input = TaskInput(
            task_id=unique_id,
            prompt=prompt,
            repo_root=repo_root,
            target_paths=["."],
            timeout_seconds=_STALL_TIMEOUT_SECONDS,
            metadata={"artifact_root": artifact_dir},
        )
        run_ref = adapter.run(task_input)
        started = time.time()

        # Poll until completion
        while True:
            status = adapter.poll(run_ref)
            if status.completed:
                break
            time.sleep(1.0)

            # Stall timeout
            if time.time() - started > _STALL_TIMEOUT_SECONDS:
                try:
                    adapter.cancel(run_ref)
                except (OSError, ProcessLookupError):
                    pass
                return {
                    "success": False,
                    "response": "",
                    "error": "Provider timed out after {}s".format(_STALL_TIMEOUT_SECONDS),
                    "wall_clock_seconds": round(time.time() - started, 2),
                }

        wall_clock = round(time.time() - started, 2)

        # Read output and extract human-readable text
        raw_dir = Path(run_ref.artifact_path) / "raw"
        stdout_path = raw_dir / "{}.stdout.log".format(provider)
        stderr_path = raw_dir / "{}.stderr.log".format(provider)
        raw_stdout = ""
        raw_stderr = ""
        if stdout_path.exists():
            raw_stdout = stdout_path.read_text(encoding="utf-8", errors="replace")
        if stderr_path.exists():
            raw_stderr = stderr_path.read_text(encoding="utf-8", errors="replace")

        # Use extract_final_text to strip protocol noise (JSON wrappers, event streams)
        from ..adapters.parsing import extract_final_text_from_output
        combined = raw_stdout
        if raw_stderr:
            combined = combined + "\n" + raw_stderr if combined else raw_stderr
        response = extract_final_text_from_output(combined) or raw_stdout

        success = status.attempt_state == "SUCCEEDED"
        return {
            "success": success,
            "response": response.strip(),
            "wall_clock_seconds": wall_clock,
        }


def _handle_connection(
    conn: socket.socket,
    state: SessionState,
    repo_root: str,
) -> bool:
    """Handle one client connection. Returns False if shutdown requested."""
    try:
        data = b""
        while True:
            chunk = conn.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in data:
                break

        if not data:
            return True

        request = json.loads(data.decode("utf-8").strip())
        action = request.get("action", "")

        if action == "ping":
            conn.sendall(json.dumps({"status": "pong"}).encode("utf-8") + b"\n")
            return True

        if action == "shutdown":
            conn.sendall(json.dumps({"status": "shutdown_ack"}).encode("utf-8") + b"\n")
            return False

        if action == "send":
            prompt = request.get("prompt", "")
            if not prompt:
                conn.sendall(json.dumps({"status": "error", "message": "Empty prompt"}).encode("utf-8") + b"\n")
                return True

            # Build prompt with conversation history
            history = load_history(repo_root, state.name)
            full_prompt = build_history_prompt(history, prompt)

            # Dispatch to agent
            result = _dispatch_prompt(state.provider, repo_root, full_prompt)

            # Only record history on successful dispatch
            if result.get("success") and result.get("response"):
                append_history(repo_root, state.name, HistoryEntry(role="user", content=prompt))
                append_history(repo_root, state.name, HistoryEntry(
                    role="assistant",
                    content=result["response"],
                    wall_clock_seconds=result.get("wall_clock_seconds", 0),
                ))

            # Update state only on success
            if result.get("success"):
                state.turn_count += 1
            state.last_active = _now_iso()
            save_state(repo_root, state)

            response = {
                "status": "ok" if result["success"] else "error",
                "response": result.get("response", ""),
                "wall_clock_seconds": result.get("wall_clock_seconds", 0),
            }
            if not result["success"] and result.get("error"):
                response["message"] = result["error"]
            conn.sendall(json.dumps(response).encode("utf-8") + b"\n")
            return True

        conn.sendall(json.dumps({"status": "error", "message": "Unknown action: {}".format(action)}).encode("utf-8") + b"\n")
        return True

    except Exception as exc:
        try:
            conn.sendall(json.dumps({"status": "error", "message": str(exc)}).encode("utf-8") + b"\n")
        except Exception:
            pass
        return True


def run_daemon(repo_root: str, name: str) -> None:
    """Main daemon loop — listen on unix socket, handle requests.

    This function is meant to run in a forked process.
    """
    state = load_state(repo_root, name)
    if state is None:
        return

    sock_path = _socket_path(repo_root, name)

    # Clean up stale socket
    if os.path.exists(sock_path):
        os.unlink(sock_path)

    server = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    try:
        server.bind(sock_path)
    except OSError as exc:
        # Socket path too long or permission denied — mark crashed
        state.status = "crashed"
        state.pid = None
        save_state(repo_root, state)
        import sys
        print("Daemon bind failed: {}".format(exc), file=sys.stderr)
        return
    server.listen(5)  # Allow queued connections during broadcast
    server.settimeout(1.0)  # Allow periodic shutdown checks

    # Update state with PID — only after successful bind
    state.pid = os.getpid()
    state.status = "active"
    save_state(repo_root, state)

    _running = True

    def _sigterm_handler(signum: int, frame: Any) -> None:
        nonlocal _running
        _running = False

    # signal.signal only works in main thread
    import threading
    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _sigterm_handler)

    try:
        while _running:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            try:
                should_continue = _handle_connection(conn, state, repo_root)
                if not should_continue:
                    break
            finally:
                conn.close()
    finally:
        server.close()
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        state.status = "stopped"
        state.pid = None
        save_state(repo_root, state)
