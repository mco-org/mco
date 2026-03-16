"""Tests for session lifecycle manager."""
from __future__ import annotations

import os
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from runtime.session.state import SessionState, save_state, load_state, load_history
from runtime.session.daemon import run_daemon, _socket_path
from runtime.session.client import send_prompt, ping_session, stop_session as client_stop, broadcast_prompt
from runtime.session.manager import _is_pid_alive


class TestIsAlivePid(unittest.TestCase):
    def test_current_process_alive(self) -> None:
        self.assertTrue(_is_pid_alive(os.getpid()))

    def test_bogus_pid_dead(self) -> None:
        self.assertFalse(_is_pid_alive(999999999))


class _DaemonTestBase(unittest.TestCase):
    """Base class that starts daemon in a thread (mocks work across threads)."""

    def _start_daemon_thread(self, repo_root: str, name: str) -> threading.Thread:
        t = threading.Thread(target=run_daemon, args=(repo_root, name), daemon=True)
        t.start()
        sock_path = _socket_path(repo_root, name)
        for _ in range(100):
            if os.path.exists(sock_path):
                break
            time.sleep(0.05)
        return t

    def _stop_daemon(self, repo_root: str, name: str, thread: threading.Thread) -> None:
        client_stop(repo_root, name)
        thread.join(timeout=5)


class TestSessionStartStopPing(_DaemonTestBase):
    def test_start_ping_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = SessionState(name="test-lc", provider="claude", repo_root=tmp)
            save_state(tmp, state)

            t = self._start_daemon_thread(tmp, "test-lc")

            # Ping
            alive = ping_session(tmp, "test-lc")
            self.assertTrue(alive)

            # Stop
            self._stop_daemon(tmp, "test-lc", t)

            final = load_state(tmp, "test-lc")
            self.assertEqual(final.status, "stopped")


class TestSessionSendHistory(_DaemonTestBase):
    @patch("runtime.session.daemon._dispatch_prompt")
    def test_send_records_response(self, mock_dispatch) -> None:
        mock_dispatch.return_value = {
            "success": True,
            "response": "Found 2 security issues",
            "wall_clock_seconds": 3.0,
        }
        with tempfile.TemporaryDirectory() as tmp:
            state = SessionState(name="test-send", provider="claude", repo_root=tmp)
            save_state(tmp, state)

            t = self._start_daemon_thread(tmp, "test-send")

            result = send_prompt(tmp, "test-send", "review auth.py")
            self.assertEqual(result["status"], "ok")
            self.assertIn("Found 2 security issues", result["response"])

            # History recorded
            history = load_history(tmp, "test-send")
            self.assertEqual(len(history), 2)
            self.assertEqual(history[0].role, "user")
            self.assertEqual(history[1].role, "assistant")

            self._stop_daemon(tmp, "test-send", t)

    @patch("runtime.session.daemon._dispatch_prompt")
    def test_multi_turn_builds_context(self, mock_dispatch) -> None:
        mock_dispatch.return_value = {
            "success": True,
            "response": "Done",
            "wall_clock_seconds": 1.0,
        }
        with tempfile.TemporaryDirectory() as tmp:
            state = SessionState(name="test-ctx", provider="claude", repo_root=tmp)
            save_state(tmp, state)

            t = self._start_daemon_thread(tmp, "test-ctx")

            send_prompt(tmp, "test-ctx", "review auth.py")
            send_prompt(tmp, "test-ctx", "now check tests")

            # Second call should include history in the prompt
            second_call_prompt = mock_dispatch.call_args_list[1][1].get("prompt") or mock_dispatch.call_args_list[1][0][2]
            self.assertIn("Conversation History", second_call_prompt)
            self.assertIn("review auth.py", second_call_prompt)

            # Turn count
            final = load_state(tmp, "test-ctx")
            self.assertEqual(final.turn_count, 2)

            self._stop_daemon(tmp, "test-ctx", t)


class TestSessionBroadcast(_DaemonTestBase):
    @patch("runtime.session.daemon._dispatch_prompt")
    def test_broadcast_to_multiple(self, mock_dispatch) -> None:
        mock_dispatch.return_value = {
            "success": True,
            "response": "Agent response",
            "wall_clock_seconds": 1.0,
        }
        with tempfile.TemporaryDirectory() as tmp:
            for name in ["b1", "b2"]:
                state = SessionState(name=name, provider="claude", repo_root=tmp)
                save_state(tmp, state)

            t1 = self._start_daemon_thread(tmp, "b1")
            t2 = self._start_daemon_thread(tmp, "b2")

            results = broadcast_prompt(tmp, "summarize")
            self.assertEqual(len(results), 2)
            names = sorted(r["session_name"] for r in results)
            self.assertEqual(names, ["b1", "b2"])

            self._stop_daemon(tmp, "b1", t1)
            self._stop_daemon(tmp, "b2", t2)


class TestSessionResume(_DaemonTestBase):
    def test_resume_after_stop(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = SessionState(name="test-resume", provider="claude", repo_root=tmp)
            save_state(tmp, state)

            t = self._start_daemon_thread(tmp, "test-resume")
            self._stop_daemon(tmp, "test-resume", t)

            # Should be stopped
            stopped = load_state(tmp, "test-resume")
            self.assertEqual(stopped.status, "stopped")

            # Resume — re-start daemon
            stopped.status = "active"
            save_state(tmp, stopped)
            t2 = self._start_daemon_thread(tmp, "test-resume")

            alive = ping_session(tmp, "test-resume")
            self.assertTrue(alive)

            self._stop_daemon(tmp, "test-resume", t2)


class TestSessionNotRunning(unittest.TestCase):
    def test_send_to_nonexistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            result = send_prompt(tmp, "nope", "hello")
            self.assertEqual(result["status"], "error")

    def test_broadcast_with_no_sessions(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            results = broadcast_prompt(tmp, "hello")
            self.assertEqual(results, [])
