"""Tests for session daemon socket protocol with queue and cancellation."""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from runtime.session.state import SessionState, save_state, load_state, load_history
from runtime.session.daemon import run_daemon, _dispatch_prompt, _socket_path


def _send_request(sock_path: str, request: dict, timeout: float = 10.0) -> dict:
    """Send a JSON request to the daemon and return the first response."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    client.connect(sock_path)
    client.sendall(json.dumps(request).encode("utf-8") + b"\n")
    data = b""
    while b"\n" not in data:
        chunk = client.recv(4096)
        if not chunk:
            break
        data += chunk
    client.close()
    return json.loads(data.decode("utf-8").strip())


def _send_prompt_request(sock_path: str, prompt: str, timeout: float = 30.0) -> dict:
    """Send a prompt and read both the queued ack and the final result."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    client.connect(sock_path)
    client.sendall(json.dumps({"action": "send", "prompt": prompt}).encode("utf-8") + b"\n")

    responses = []
    buf = b""
    while len(responses) < 2:
        chunk = client.recv(65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                responses.append(json.loads(line.decode("utf-8")))
    client.close()
    # Return final response; if only 1 response (error before queue), return that
    return responses[-1] if responses else {}


class TestDaemonProtocol(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.state = SessionState(name="test-session", provider="claude", repo_root=self.tmp)
        save_state(self.tmp, self.state)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _start_daemon(self) -> threading.Thread:
        t = threading.Thread(target=run_daemon, args=(self.tmp, "test-session"), daemon=True)
        t.start()
        sock_path = _socket_path(self.tmp, "test-session")
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)
        return t

    def test_ping_pong(self) -> None:
        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")
        response = _send_request(sock_path, {"action": "ping"})
        self.assertEqual(response["status"], "pong")
        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

    def test_shutdown(self) -> None:
        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")
        response = _send_request(sock_path, {"action": "shutdown"})
        self.assertEqual(response["status"], "shutdown_ack")
        t.join(timeout=5)
        state = load_state(self.tmp, "test-session")
        self.assertEqual(state.status, "stopped")

    def test_unknown_action(self) -> None:
        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")
        response = _send_request(sock_path, {"action": "bogus"})
        self.assertEqual(response["status"], "error")
        self.assertIn("Unknown action", response["message"])
        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_send_records_history(self, mock_dispatch) -> None:
        mock_dispatch.return_value = {
            "success": True,
            "response": "Found 2 issues in auth.py",
            "wall_clock_seconds": 3.5,
        }
        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")

        response = _send_prompt_request(sock_path, "review auth.py")
        self.assertEqual(response["status"], "ok")
        self.assertIn("Found 2 issues", response["response"])

        # Check history was recorded
        history = load_history(self.tmp, "test-session")
        self.assertEqual(len(history), 2)
        self.assertEqual(history[0].role, "user")
        self.assertEqual(history[0].content, "review auth.py")
        self.assertEqual(history[1].role, "assistant")

        # Check turn count
        state = load_state(self.tmp, "test-session")
        self.assertEqual(state.turn_count, 1)

        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_send_includes_history_in_prompt(self, mock_dispatch) -> None:
        mock_dispatch.return_value = {
            "success": True,
            "response": "Coverage is 80%",
            "wall_clock_seconds": 2.0,
        }
        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")

        # Turn 1
        _send_prompt_request(sock_path, "review auth.py")
        # Turn 2 — should include history
        _send_prompt_request(sock_path, "check test coverage")

        # The second call should have included history in the prompt
        calls = mock_dispatch.call_args_list
        second_prompt = calls[1][1]["prompt"] if calls[1][1] else calls[1][0][2]
        self.assertIn("Conversation History", second_prompt)
        self.assertIn("review auth.py", second_prompt)

        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

    def test_empty_prompt_rejected(self) -> None:
        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")
        # Empty prompt returns error immediately (single response, not two)
        response = _send_request(sock_path, {"action": "send", "prompt": ""})
        self.assertEqual(response["status"], "error")
        self.assertIn("Empty prompt", response["message"])
        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)


class TestDaemonQueue(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.state = SessionState(name="test-session", provider="claude", repo_root=self.tmp)
        save_state(self.tmp, self.state)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _start_daemon(self) -> threading.Thread:
        t = threading.Thread(target=run_daemon, args=(self.tmp, "test-session"), daemon=True)
        t.start()
        sock_path = _socket_path(self.tmp, "test-session")
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)
        return t

    def test_queue_status_idle(self) -> None:
        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")
        response = _send_request(sock_path, {"action": "queue"})
        self.assertEqual(response["status"], "ok")
        self.assertIsNone(response["running"])
        self.assertEqual(response["queued"], 0)
        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_queue_status_during_dispatch(self, mock_dispatch) -> None:
        dispatch_started = threading.Event()
        dispatch_release = threading.Event()

        def slow_dispatch(*args, **kwargs):
            dispatch_started.set()
            dispatch_release.wait(timeout=10)
            return {"success": True, "response": "done", "wall_clock_seconds": 1.0}

        mock_dispatch.side_effect = slow_dispatch

        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")

        # Send a prompt in background
        def sender():
            _send_prompt_request(sock_path, "do something")
        st = threading.Thread(target=sender, daemon=True)
        st.start()

        dispatch_started.wait(timeout=5)
        time.sleep(0.1)

        response = _send_request(sock_path, {"action": "queue"})
        self.assertEqual(response["status"], "ok")
        self.assertIsNotNone(response["running"])
        self.assertEqual(response["queued"], 0)

        dispatch_release.set()
        st.join(timeout=10)
        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_cancel_running_request(self, mock_dispatch) -> None:
        dispatch_started = threading.Event()

        def cancellable_dispatch(*args, cancel_event=None, **kwargs):
            dispatch_started.set()
            for _ in range(100):
                if cancel_event and cancel_event.is_set():
                    return {"success": False, "response": "", "error": "Cancelled", "wall_clock_seconds": 0.5}
                time.sleep(0.05)
            return {"success": True, "response": "done", "wall_clock_seconds": 5.0}

        mock_dispatch.side_effect = cancellable_dispatch

        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")

        send_result = {}
        def sender():
            send_result["r"] = _send_prompt_request(sock_path, "slow task")
        st = threading.Thread(target=sender, daemon=True)
        st.start()

        dispatch_started.wait(timeout=5)
        time.sleep(0.1)

        cancel_response = _send_request(sock_path, {"action": "cancel"})
        self.assertEqual(cancel_response["status"], "ok")
        self.assertGreaterEqual(cancel_response["cancelled"], 1)

        st.join(timeout=10)
        self.assertIn(send_result["r"]["status"], ("cancelled", "error"))

        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

    def test_cancel_nothing_running(self) -> None:
        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")
        response = _send_request(sock_path, {"action": "cancel"})
        self.assertEqual(response["status"], "ok")
        self.assertEqual(response["cancelled"], 0)
        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_send_returns_request_id(self, mock_dispatch) -> None:
        mock_dispatch.return_value = {
            "success": True,
            "response": "ok",
            "wall_clock_seconds": 0.1,
        }
        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")
        response = _send_prompt_request(sock_path, "test")
        self.assertIn("request_id", response)
        self.assertEqual(response["request_id"], 1)
        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_queued_requests_processed_serially(self, mock_dispatch) -> None:
        """Multiple sends should be processed one at a time."""
        call_order = []

        def ordered_dispatch(*args, cancel_event=None, **kwargs):
            prompt = args[2] if len(args) > 2 else kwargs.get("prompt", "")
            lines = prompt.strip().split("\n")
            call_order.append(lines[-1])
            time.sleep(0.05)
            return {"success": True, "response": "done: " + lines[-1], "wall_clock_seconds": 0.05}

        mock_dispatch.side_effect = ordered_dispatch

        t = self._start_daemon()
        sock_path = _socket_path(self.tmp, "test-session")

        results = [None, None, None]
        def sender(idx, prompt):
            results[idx] = _send_prompt_request(sock_path, prompt)

        threads = []
        for i, prompt in enumerate(["first", "second", "third"]):
            st = threading.Thread(target=sender, args=(i, prompt), daemon=True)
            threads.append(st)
            st.start()
            time.sleep(0.05)

        for st in threads:
            st.join(timeout=30)

        for r in results:
            self.assertEqual(r["status"], "ok")

        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)


class TestLineReader(unittest.TestCase):
    """Test _LineReader handles single-recv multi-line buffers correctly."""

    def _make_fake_socket(self, chunks: list) -> socket.socket:
        """Create a mock socket that yields predefined byte chunks."""
        from unittest.mock import MagicMock
        sock = MagicMock(spec=socket.socket)
        it = iter(chunks)
        sock.recv = lambda _: next(it, b"")
        return sock

    def test_two_responses_in_single_recv(self) -> None:
        """Both queued ack and result arrive in one recv() call."""
        from runtime.session.client import _LineReader
        combined = b'{"status":"queued","request_id":1}\n{"status":"ok","response":"done"}\n'
        reader = _LineReader(self._make_fake_socket([combined]))

        first = reader.read_one()
        self.assertEqual(first["status"], "queued")
        self.assertEqual(first["request_id"], 1)

        second = reader.read_one()
        self.assertEqual(second["status"], "ok")
        self.assertEqual(second["response"], "done")

    def test_split_across_two_recvs(self) -> None:
        """Response split across recv boundaries."""
        from runtime.session.client import _LineReader
        reader = _LineReader(self._make_fake_socket([
            b'{"status":"que',
            b'ued"}\n{"status":"ok"}\n',
        ]))

        first = reader.read_one()
        self.assertEqual(first["status"], "queued")

        second = reader.read_one()
        self.assertEqual(second["status"], "ok")

    def test_eof_returns_none(self) -> None:
        """EOF (empty recv) returns None."""
        from runtime.session.client import _LineReader
        reader = _LineReader(self._make_fake_socket([b""]))
        self.assertIsNone(reader.read_one())
