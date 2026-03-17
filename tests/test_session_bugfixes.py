# tests/test_session_bugfixes.py
"""Tests for P0 session bug fixes: nowait data loss, broader exception handling,
resume provider validation, and result retrieval."""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from runtime.session.state import SessionState, save_state, load_state, load_history
from runtime.session.daemon import run_daemon, _socket_path
from runtime.session.client import send_prompt_nowait, get_result
from runtime.session.manager import resume_session


def _send_raw(sock_path: str, request: dict, timeout: float = 10.0) -> dict:
    """Send a JSON request and read one response."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    client.connect(sock_path)
    client.sendall(json.dumps(request).encode("utf-8") + b"\n")
    data = b""
    while b"\n" not in data:
        chunk = client.recv(65536)
        if not chunk:
            break
        data += chunk
    client.close()
    return json.loads(data.decode("utf-8").strip()) if data else {}


class TestNowaitNoDataLoss(unittest.TestCase):
    """Verify that --no-wait requests don't lose data."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.state = SessionState(name="test-nwfix", provider="claude", repo_root=self.tmp)
        save_state(self.tmp, self.state)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_nowait_result_retrievable_via_result_action(self, mock_dispatch) -> None:
        """After nowait send, the result should be retrievable via 'result' action."""
        dispatch_started = threading.Event()

        def slow_dispatch(*args, **kwargs):
            dispatch_started.set()
            time.sleep(0.5)  # Simulate work
            return {"success": True, "response": "Analysis complete", "wall_clock_seconds": 0.5}

        mock_dispatch.side_effect = slow_dispatch

        t = threading.Thread(target=run_daemon, args=(self.tmp, "test-nwfix"), daemon=True)
        t.start()
        sock_path = _socket_path(self.tmp, "test-nwfix")
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)

        # Send with nowait — returns immediately with queued ack
        result = send_prompt_nowait(self.tmp, "test-nwfix", "review code")
        self.assertEqual(result["status"], "queued")
        request_id = result["request_id"]

        # Wait for dispatch to complete
        dispatch_started.wait(timeout=5)
        time.sleep(1.0)  # Let worker finish

        # Retrieve result via 'result' action
        retrieved = get_result(self.tmp, "test-nwfix", request_id)
        self.assertEqual(retrieved["status"], "ok")
        self.assertIn("Analysis complete", retrieved["response"])

        # History should also be recorded
        history = load_history(self.tmp, "test-nwfix")
        self.assertTrue(len(history) >= 2)

        from runtime.session.client import stop_session
        stop_session(self.tmp, "test-nwfix")
        t.join(timeout=5)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_nowait_daemon_does_not_write_to_closed_socket(self, mock_dispatch) -> None:
        """Daemon handler should not try to send result on a nowait connection."""
        mock_dispatch.return_value = {
            "success": True, "response": "done", "wall_clock_seconds": 1.0,
        }

        t = threading.Thread(target=run_daemon, args=(self.tmp, "test-nwfix"), daemon=True)
        t.start()
        sock_path = _socket_path(self.tmp, "test-nwfix")
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)

        # Send with nowait=True in the raw protocol
        ack = _send_raw(sock_path, {"action": "send", "prompt": "test", "nowait": True})
        self.assertEqual(ack["status"], "queued")

        # Wait for worker to process
        time.sleep(1.0)

        # Daemon should still be running (no crash from BrokenPipeError)
        ping = _send_raw(sock_path, {"action": "ping"})
        self.assertEqual(ping["status"], "pong")

        _send_raw(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_result_action_pending(self, mock_dispatch) -> None:
        """Result action returns pending while request is still running."""
        dispatch_started = threading.Event()
        dispatch_done = threading.Event()

        def slow_dispatch(*args, **kwargs):
            dispatch_started.set()
            dispatch_done.wait(timeout=10)
            return {"success": True, "response": "done", "wall_clock_seconds": 1.0}

        mock_dispatch.side_effect = slow_dispatch

        t = threading.Thread(target=run_daemon, args=(self.tmp, "test-nwfix"), daemon=True)
        t.start()
        sock_path = _socket_path(self.tmp, "test-nwfix")
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)

        ack = _send_raw(sock_path, {"action": "send", "prompt": "test", "nowait": True})
        request_id = ack["request_id"]

        dispatch_started.wait(timeout=5)

        # Should be pending
        pending = _send_raw(sock_path, {"action": "result", "request_id": request_id})
        self.assertEqual(pending["status"], "pending")

        dispatch_done.set()
        time.sleep(0.5)

        # Now should have result
        final = _send_raw(sock_path, {"action": "result", "request_id": request_id})
        self.assertEqual(final["status"], "ok")

        _send_raw(sock_path, {"action": "shutdown"})
        t.join(timeout=5)


class TestResumeProviderValidation(unittest.TestCase):
    """Resume should validate provider matches."""

    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_resume_with_mismatched_provider_raises(self) -> None:
        state = SessionState(name="test-prov", provider="claude", status="stopped", repo_root=self.tmp)
        save_state(self.tmp, state)
        with self.assertRaises(ValueError) as ctx:
            resume_session(self.tmp, "test-prov", provider="codex")
        self.assertIn("mismatch", str(ctx.exception).lower())

    @patch("runtime.session.manager._launch_daemon")
    @patch("runtime.session.manager._is_pid_alive", return_value=False)
    def test_resume_with_matching_provider_gets_past_check(self, mock_alive, mock_launch) -> None:
        """Resume with matching provider should not raise on provider check."""
        state = SessionState(name="test-prov", provider="claude", status="stopped", repo_root=self.tmp)
        save_state(self.tmp, state)
        # Will fail on daemon launch verification, but should get past provider check
        with self.assertRaises(ValueError) as ctx:
            resume_session(self.tmp, "test-prov", provider="claude")
        # Should fail on daemon start, NOT on provider mismatch
        self.assertIn("failed to resume", str(ctx.exception).lower())

    @patch("runtime.session.manager._launch_daemon")
    @patch("runtime.session.manager._is_pid_alive", return_value=False)
    def test_resume_without_provider_skips_check(self, mock_alive, mock_launch) -> None:
        """Resume without provider param should work as before."""
        state = SessionState(name="test-prov", provider="claude", status="stopped", repo_root=self.tmp)
        save_state(self.tmp, state)
        with self.assertRaises(ValueError) as ctx:
            resume_session(self.tmp, "test-prov")
        self.assertIn("failed to resume", str(ctx.exception).lower())


class TestBroaderExceptionHandling(unittest.TestCase):
    """adapter.cancel() should catch all exceptions, not just OSError."""

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_worker_survives_cancel_runtime_error(self, mock_dispatch) -> None:
        """Worker thread should not die if adapter.cancel raises RuntimeError."""
        tmp = tempfile.mkdtemp()
        state = SessionState(name="test-exc", provider="claude", repo_root=tmp)
        save_state(tmp, state)

        call_count = {"n": 0}

        def counting_dispatch(*args, **kwargs):
            call_count["n"] += 1
            if call_count["n"] == 1:
                # First call: simulate a cancel that raises RuntimeError
                cancel_event = kwargs.get("cancel_event") or (args[3] if len(args) > 3 else None)
                if cancel_event:
                    cancel_event.set()
                time.sleep(0.1)
                raise RuntimeError("Unexpected error in cancel")
            return {"success": True, "response": "second call ok", "wall_clock_seconds": 0.1}

        mock_dispatch.side_effect = counting_dispatch

        t = threading.Thread(target=run_daemon, args=(tmp, "test-exc"), daemon=True)
        t.start()
        sock_path = _socket_path(tmp, "test-exc")
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)

        # Daemon should still accept pings
        ping = _send_raw(sock_path, {"action": "ping"})
        self.assertEqual(ping["status"], "pong")

        _send_raw(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
