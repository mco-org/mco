"""Session daemon — unix socket listener with request queue and cancellation."""
from __future__ import annotations

import json
import os
import queue
import signal
import socket
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

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
_MAX_QUEUE_DEPTH = 10


def _socket_path(repo_root: str, name: str) -> str:
    return str(session_dir(repo_root, name) / "sock")


@dataclass
class _QueuedRequest:
    """A prompt waiting to be processed by the worker thread."""
    request_id: int
    prompt: str
    done: threading.Event = field(default_factory=threading.Event)
    result: Optional[Dict[str, Any]] = None
    cancelled: bool = False


class _DaemonContext:
    """Shared mutable state for daemon threads."""

    def __init__(self) -> None:
        self.request_queue: queue.Queue[_QueuedRequest] = queue.Queue(
            maxsize=_MAX_QUEUE_DEPTH,
        )
        self.lock = threading.Lock()
        self.current_request: Optional[_QueuedRequest] = None
        self.cancel_event = threading.Event()
        self.next_id = 1
        self.running = True


def _dispatch_prompt(
    provider: str,
    repo_root: str,
    prompt: str,
    cancel_event: Optional[threading.Event] = None,
) -> Dict[str, Any]:
    """Run a single prompt through the provider adapter and return the result.

    Returns {success, response, wall_clock_seconds}.
    If cancel_event is set during execution, cancels the provider and returns early.
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

        # Poll until completion or cancellation
        while True:
            # Check for cancellation
            if cancel_event and cancel_event.is_set():
                try:
                    adapter.cancel(run_ref)
                except (OSError, ProcessLookupError):
                    pass
                return {
                    "success": False,
                    "response": "",
                    "error": "Cancelled",
                    "wall_clock_seconds": round(time.time() - started, 2),
                }

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


def _worker_loop(
    ctx: _DaemonContext,
    state: SessionState,
    repo_root: str,
) -> None:
    """Worker thread — processes queued requests one at a time."""
    while ctx.running:
        try:
            req = ctx.request_queue.get(timeout=1.0)
        except queue.Empty:
            continue

        # Mark as current
        with ctx.lock:
            ctx.current_request = req
            ctx.cancel_event.clear()

        # Skip if already cancelled before worker picked it up
        if req.cancelled:
            req.result = {
                "status": "error",
                "response": "",
                "message": "Cancelled before execution",
                "wall_clock_seconds": 0,
            }
            req.done.set()
            with ctx.lock:
                ctx.current_request = None
            continue

        # Build prompt with conversation history
        history = load_history(repo_root, state.name)
        full_prompt = build_history_prompt(history, req.prompt)

        # Dispatch to agent
        result = _dispatch_prompt(
            state.provider, repo_root, full_prompt, ctx.cancel_event,
        )

        # Build response
        success = result.get("success", False)
        cancelled = ctx.cancel_event.is_set()

        if success and result.get("response") and not cancelled:
            # Record history on success
            append_history(repo_root, state.name, HistoryEntry(
                role="user", content=req.prompt,
            ))
            append_history(repo_root, state.name, HistoryEntry(
                role="assistant",
                content=result["response"],
                wall_clock_seconds=result.get("wall_clock_seconds", 0),
            ))
            state.turn_count += 1

        state.last_active = _now_iso()
        save_state(repo_root, state)

        response: Dict[str, Any] = {
            "status": "ok" if success else "error",
            "response": result.get("response", ""),
            "wall_clock_seconds": result.get("wall_clock_seconds", 0),
            "request_id": req.request_id,
        }
        if cancelled:
            response["status"] = "cancelled"
            response["message"] = "Cancelled"
        elif not success and result.get("error"):
            response["message"] = result["error"]

        req.result = response
        req.done.set()

        with ctx.lock:
            ctx.current_request = None


_MAX_REQUEST_SIZE = 1024 * 1024  # 1 MB


def _read_request(conn: socket.socket) -> Optional[Dict[str, Any]]:
    """Read a single JSON-line request from the connection."""
    data = b""
    while True:
        chunk = conn.recv(4096)
        if not chunk:
            break
        data += chunk
        if len(data) > _MAX_REQUEST_SIZE:
            raise ValueError("Request exceeds maximum size of {} bytes".format(_MAX_REQUEST_SIZE))
        if b"\n" in data:
            break
    if not data:
        return None
    return json.loads(data.decode("utf-8").strip())


def _send_response(conn: socket.socket, response: Dict[str, Any]) -> None:
    """Send a JSON-line response on the connection."""
    conn.sendall(json.dumps(response).encode("utf-8") + b"\n")


def _handle_connection(
    conn: socket.socket,
    ctx: _DaemonContext,
    state: SessionState,
    repo_root: str,
) -> bool:
    """Handle one client connection. Returns False if shutdown requested."""
    try:
        request = _read_request(conn)
        if request is None:
            return True

        action = request.get("action", "")

        if action == "ping":
            _send_response(conn, {"status": "pong"})
            return True

        if action == "shutdown":
            # Drain and cancel all queued requests
            while not ctx.request_queue.empty():
                try:
                    queued = ctx.request_queue.get_nowait()
                    queued.cancelled = True
                    queued.result = {
                        "status": "cancelled",
                        "response": "",
                        "message": "Session shutting down",
                        "wall_clock_seconds": 0,
                    }
                    queued.done.set()
                except queue.Empty:
                    break
            # Cancel current request if any
            with ctx.lock:
                if ctx.current_request is not None:
                    ctx.cancel_event.set()
            _send_response(conn, {"status": "shutdown_ack"})
            return False

        if action == "send":
            prompt = request.get("prompt", "")
            if not prompt:
                _send_response(conn, {"status": "error", "message": "Empty prompt"})
                return True

            # Create queued request
            with ctx.lock:
                request_id = ctx.next_id
                ctx.next_id += 1

            req = _QueuedRequest(request_id=request_id, prompt=prompt)

            try:
                ctx.request_queue.put_nowait(req)
            except queue.Full:
                _send_response(conn, {
                    "status": "error",
                    "message": "Queue full ({} pending). Try again later.".format(_MAX_QUEUE_DEPTH),
                })
                return True

            # Tell client the request is queued with its position
            position = ctx.request_queue.qsize()
            _send_response(conn, {
                "status": "queued",
                "request_id": request_id,
                "position": position,
            })

            # Block until worker processes this request
            req.done.wait()

            # Send the actual result
            if req.result is not None:
                _send_response(conn, req.result)
            else:
                _send_response(conn, {
                    "status": "error",
                    "message": "Request dropped",
                    "request_id": request_id,
                })
            return True

        if action == "cancel":
            with ctx.lock:
                current = ctx.current_request
                if current is not None:
                    ctx.cancel_event.set()
                    running_id = current.request_id

            if current is None:
                _send_response(conn, {
                    "status": "ok",
                    "message": "Nothing running",
                    "cancelled": 0,
                })
                return True

            # Also cancel all queued requests
            cancelled_count = 1  # The running one
            while not ctx.request_queue.empty():
                try:
                    queued = ctx.request_queue.get_nowait()
                    queued.cancelled = True
                    queued.result = {
                        "status": "cancelled",
                        "response": "",
                        "message": "Cancelled",
                        "wall_clock_seconds": 0,
                        "request_id": queued.request_id,
                    }
                    queued.done.set()
                    cancelled_count += 1
                except queue.Empty:
                    break

            _send_response(conn, {
                "status": "ok",
                "request_id": running_id,
                "cancelled": cancelled_count,
            })
            return True

        if action == "queue":
            with ctx.lock:
                running_id = ctx.current_request.request_id if ctx.current_request else None
                queue_size = ctx.request_queue.qsize()

            _send_response(conn, {
                "status": "ok",
                "running": running_id,
                "queued": queue_size,
            })
            return True

        _send_response(conn, {"status": "error", "message": "Unknown action: {}".format(action)})
        return True

    except Exception as exc:
        try:
            _send_response(conn, {"status": "error", "message": str(exc)})
        except Exception:
            pass
        return True


def _connection_handler(
    conn: socket.socket,
    ctx: _DaemonContext,
    state: SessionState,
    repo_root: str,
) -> None:
    """Threaded connection handler — wraps _handle_connection with cleanup."""
    try:
        should_continue = _handle_connection(conn, ctx, state, repo_root)
        if not should_continue:
            ctx.running = False
    finally:
        conn.close()


def run_daemon(repo_root: str, name: str) -> None:
    """Main daemon loop — listen on unix socket, handle requests.

    Uses a worker thread for serial prompt execution and handler threads
    for concurrent connection handling (cancel/queue/ping while busy).
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
    server.listen(5)
    server.settimeout(1.0)

    # Update state with PID — only after successful bind
    state.pid = os.getpid()
    state.status = "active"
    save_state(repo_root, state)

    ctx = _DaemonContext()

    # Start worker thread
    worker = threading.Thread(
        target=_worker_loop, args=(ctx, state, repo_root), daemon=True,
    )
    worker.start()

    def _sigterm_handler(signum: int, frame: Any) -> None:
        ctx.running = False

    if threading.current_thread() is threading.main_thread():
        signal.signal(signal.SIGTERM, _sigterm_handler)

    handler_threads: List[threading.Thread] = []

    try:
        while ctx.running:
            try:
                conn, _ = server.accept()
            except socket.timeout:
                continue
            except OSError:
                break

            t = threading.Thread(
                target=_connection_handler,
                args=(conn, ctx, state, repo_root),
                daemon=True,
            )
            t.start()
            handler_threads.append(t)

            # Prune finished handler threads periodically
            handler_threads = [t for t in handler_threads if t.is_alive()]
    finally:
        ctx.running = False

        # Drain queue so worker can exit
        while not ctx.request_queue.empty():
            try:
                req = ctx.request_queue.get_nowait()
                req.cancelled = True
                req.result = {
                    "status": "cancelled",
                    "response": "",
                    "message": "Daemon shutting down",
                    "wall_clock_seconds": 0,
                }
                req.done.set()
            except queue.Empty:
                break

        # Cancel current request
        ctx.cancel_event.set()

        # Wait for handler threads (they'll unblock once queued requests resolve)
        for ht in handler_threads:
            ht.join(timeout=3)

        worker.join(timeout=5)
        server.close()
        if os.path.exists(sock_path):
            os.unlink(sock_path)
        state.status = "stopped"
        state.pid = None
        save_state(repo_root, state)
