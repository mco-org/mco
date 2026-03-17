# tests/test_session_nowait.py
"""Tests for --no-wait async send."""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch

from runtime.session.state import SessionState, save_state
from runtime.session.daemon import run_daemon, _socket_path
from runtime.session.client import send_prompt_nowait
from runtime.cli import build_parser


class TestNoWaitCLI(unittest.TestCase):
    def test_no_wait_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "send", "my-sess", "test prompt", "--no-wait"])
        self.assertTrue(args.no_wait)

    def test_no_wait_default_false(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "send", "my-sess", "test prompt"])
        self.assertFalse(args.no_wait)


class TestSendPromptNowait(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.state = SessionState(name="test-nw", provider="claude", repo_root=self.tmp)
        save_state(self.tmp, self.state)

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_nowait_returns_queued_ack(self, mock_dispatch) -> None:
        mock_dispatch.return_value = {
            "success": True, "response": "done", "wall_clock_seconds": 5.0,
        }
        t = threading.Thread(target=run_daemon, args=(self.tmp, "test-nw"), daemon=True)
        t.start()
        sock_path = _socket_path(self.tmp, "test-nw")
        for _ in range(50):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)

        result = send_prompt_nowait(self.tmp, "test-nw", "hello")
        self.assertEqual(result["status"], "queued")
        self.assertIn("request_id", result)

        from runtime.session.client import stop_session
        stop_session(self.tmp, "test-nw")
        t.join(timeout=5)
