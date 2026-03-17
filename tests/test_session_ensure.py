# tests/test_session_ensure.py
"""Tests for session ensure (idempotent create-or-return)."""
from __future__ import annotations

import tempfile
import unittest
from unittest.mock import patch

from runtime.session.state import SessionState, save_state
from runtime.session.manager import ensure_session
from runtime.cli import build_parser


class TestEnsureSession(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("runtime.session.manager._is_pid_alive", return_value=True)
    @patch("runtime.session.manager._launch_daemon")
    def test_ensure_creates_new_session(self, mock_launch, mock_alive) -> None:
        # Simulate daemon writing state with pid after launch
        from runtime.session.state import session_dir
        def _fake_launch(repo_root, name):
            sdir = session_dir(repo_root, name)
            sdir.mkdir(parents=True, exist_ok=True)
            (sdir / "sock").touch()
            st = SessionState(name=name, provider="claude", pid=12345, status="active", repo_root=repo_root)
            save_state(repo_root, st)
        mock_launch.side_effect = _fake_launch

        state = ensure_session("claude", repo_root=self.tmp, name="test-ensure")
        self.assertEqual(state.name, "test-ensure")
        self.assertEqual(state.provider, "claude")
        mock_launch.assert_called_once()

    @patch("runtime.session.manager._launch_daemon")
    @patch("runtime.session.manager._is_pid_alive", return_value=True)
    def test_ensure_returns_existing_active(self, mock_alive, mock_launch) -> None:
        existing = SessionState(name="test-ensure", provider="claude", pid=99999, status="active", repo_root=self.tmp)
        save_state(self.tmp, existing)
        state = ensure_session("claude", repo_root=self.tmp, name="test-ensure")
        self.assertEqual(state.pid, 99999)
        mock_launch.assert_not_called()

    @patch("runtime.session.manager._launch_daemon")
    @patch("runtime.session.manager._is_pid_alive", return_value=True)
    def test_ensure_provider_mismatch_raises(self, mock_alive, mock_launch) -> None:
        existing = SessionState(name="test-ensure", provider="claude", pid=99999, status="active", repo_root=self.tmp)
        save_state(self.tmp, existing)
        with self.assertRaises(ValueError) as ctx:
            ensure_session("codex", repo_root=self.tmp, name="test-ensure")
        self.assertIn("mismatch", str(ctx.exception).lower())


class TestEnsureCLIParsing(unittest.TestCase):
    def test_ensure_subcommand_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "ensure", "--provider", "claude", "--name", "my-sess"])
        self.assertEqual(args.session_action, "ensure")
        self.assertEqual(args.provider, "claude")
        self.assertEqual(args.name, "my-sess")
