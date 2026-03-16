"""JSON-RPC 2.0 transport over stdio for ACP agents.

Spawns an agent subprocess, sends JSON-RPC requests on stdin,
reads responses and notifications from stdout. Thread-safe.
"""
from __future__ import annotations

import json
import os
import queue
import subprocess
import threading
from typing import Any, Dict, List, Optional


class JsonRpcError(Exception):
    """Error response from the JSON-RPC peer."""

    def __init__(self, code: int, message: str, data: Any = None) -> None:
        self.code = code
        self.rpc_message = message
        self.data = data
        super().__init__("JSON-RPC error {}: {}".format(code, message))


class TransportClosed(Exception):
    """Raised when the transport is no longer usable."""


class JsonRpcTransport:
    """Bidirectional JSON-RPC 2.0 transport over stdin/stdout of a subprocess.

    - Requests: caller sends a JSON-RPC request and blocks until the matching
      response (same `id`) arrives. Multiple in-flight requests are supported.
    - Notifications (no `id`): queued for the caller to consume via
      `receive_notification()`.
    - A background reader thread routes incoming messages.
    """

    def __init__(self) -> None:
        self._process: Optional[subprocess.Popen[str]] = None
        self._next_id = 1
        self._id_lock = threading.Lock()
        self._write_lock = threading.Lock()
        self._pending: Dict[int, threading.Event] = {}
        self._results: Dict[int, Dict[str, Any]] = {}
        self._notifications: queue.Queue[Dict[str, Any]] = queue.Queue()
        self._reader_thread: Optional[threading.Thread] = None
        self._running = False
        self._stderr_path: Optional[str] = None

    @property
    def pid(self) -> Optional[int]:
        return self._process.pid if self._process else None

    @property
    def alive(self) -> bool:
        return self._process is not None and self._process.poll() is None

    def start(
        self,
        command: List[str],
        cwd: str = ".",
        env: Optional[Dict[str, str]] = None,
        stderr_path: Optional[str] = None,
    ) -> None:
        """Spawn the agent subprocess and start the reader thread."""
        if self._process is not None:
            raise RuntimeError("Transport already started")

        stderr_file = None
        if stderr_path:
            self._stderr_path = stderr_path
            stderr_file = open(stderr_path, "w", encoding="utf-8")

        try:
            self._process = subprocess.Popen(
                command,
                cwd=cwd,
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=stderr_file or subprocess.DEVNULL,
                text=True,
                start_new_session=True,
                env=env or os.environ.copy(),
            )
        except Exception:
            if stderr_file:
                stderr_file.close()
            raise

        self._running = True
        self._reader_thread = threading.Thread(
            target=self._read_loop, daemon=True,
        )
        self._reader_thread.start()

    def _read_loop(self) -> None:
        """Background thread: read NDJSON from stdout, route to pending or notifications."""
        assert self._process is not None
        assert self._process.stdout is not None
        try:
            for raw_line in self._process.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue

                msg_id = msg.get("id")
                if msg_id is not None and msg_id in self._pending:
                    # Response to a request
                    self._results[msg_id] = msg
                    self._pending[msg_id].set()
                else:
                    # Notification or unsolicited message
                    self._notifications.put(msg)
        except (ValueError, OSError):
            pass
        finally:
            self._running = False
            # Wake up any pending requests so they don't hang forever
            for event in list(self._pending.values()):
                event.set()

    def send_request(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
        timeout: float = 600.0,
    ) -> Any:
        """Send a JSON-RPC request and block until the response arrives.

        Returns the `result` field on success.
        Raises JsonRpcError on error response, TransportClosed if process died.
        """
        if not self.alive:
            raise TransportClosed("Agent process is not running")

        with self._id_lock:
            msg_id = self._next_id
            self._next_id += 1

        event = threading.Event()
        self._pending[msg_id] = event

        request: Dict[str, Any] = {
            "jsonrpc": "2.0",
            "id": msg_id,
            "method": method,
        }
        if params is not None:
            request["params"] = params

        self._write(request)

        if not event.wait(timeout):
            self._pending.pop(msg_id, None)
            self._results.pop(msg_id, None)
            raise TimeoutError(
                "No response for '{}' within {}s".format(method, timeout),
            )

        result_msg = self._results.pop(msg_id, None)
        self._pending.pop(msg_id, None)

        if result_msg is None:
            raise TransportClosed("Transport closed while waiting for response")

        if "error" in result_msg:
            err = result_msg["error"]
            raise JsonRpcError(
                code=err.get("code", -1),
                message=err.get("message", "Unknown error"),
                data=err.get("data"),
            )

        return result_msg.get("result")

    def send_notification(
        self,
        method: str,
        params: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Send a JSON-RPC notification (no id, no response expected)."""
        if not self.alive:
            raise TransportClosed("Agent process is not running")

        msg: Dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if params is not None:
            msg["params"] = params
        self._write(msg)

    def receive_notification(self, timeout: float = 1.0) -> Optional[Dict[str, Any]]:
        """Read the next notification from the queue. Returns None on timeout."""
        try:
            return self._notifications.get(timeout=timeout)
        except queue.Empty:
            return None

    def drain_notifications(self) -> List[Dict[str, Any]]:
        """Drain all queued notifications."""
        items: List[Dict[str, Any]] = []
        while not self._notifications.empty():
            try:
                items.append(self._notifications.get_nowait())
            except queue.Empty:
                break
        return items

    def close(self) -> None:
        """Terminate the subprocess and clean up."""
        self._running = False
        if self._process is not None:
            try:
                if self._process.stdin:
                    self._process.stdin.close()
            except OSError:
                pass
            try:
                self._process.terminate()
                self._process.wait(timeout=5)
            except (subprocess.TimeoutExpired, OSError):
                try:
                    self._process.kill()
                    self._process.wait(timeout=2)
                except OSError:
                    pass
            self._process = None
        # Wake pending requests
        for event in list(self._pending.values()):
            event.set()

    def _write(self, msg: Dict[str, Any]) -> None:
        """Write a JSON message to stdin (thread-safe)."""
        assert self._process is not None
        assert self._process.stdin is not None
        with self._write_lock:
            try:
                self._process.stdin.write(json.dumps(msg) + "\n")
                self._process.stdin.flush()
            except (BrokenPipeError, OSError) as exc:
                raise TransportClosed("Failed to write to agent stdin: {}".format(exc))
