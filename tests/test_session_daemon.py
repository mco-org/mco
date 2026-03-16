"""Tests for session daemon socket protocol."""
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
from runtime.session.daemon import run_daemon, _handle_connection, _dispatch_prompt, _socket_path


def _send_request(sock_path: str, request: dict, timeout: float = 10.0) -> dict:
    """Send a JSON request to the daemon and return the response."""
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
        # Wait for socket to appear
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
        # State should be stopped
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

        response = _send_request(sock_path, {"action": "send", "prompt": "review auth.py"})
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
        _send_request(sock_path, {"action": "send", "prompt": "review auth.py"})
        # Turn 2 — should include history
        _send_request(sock_path, {"action": "send", "prompt": "check test coverage"})

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
        response = _send_request(sock_path, {"action": "send", "prompt": ""})
        self.assertEqual(response["status"], "error")
        self.assertIn("Empty prompt", response["message"])
        _send_request(sock_path, {"action": "shutdown"})
        t.join(timeout=5)
