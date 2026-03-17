# tests/test_signal_cancel.py
"""Tests for Ctrl+C graceful cancel in session send."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock


class TestSessionSendKeyboardInterrupt(unittest.TestCase):
    @patch("runtime.session.client.send_prompt", side_effect=KeyboardInterrupt)
    @patch("runtime.session.client.cancel_session")
    def test_keyboard_interrupt_calls_cancel(self, mock_cancel, mock_send) -> None:
        """Ctrl+C during session send should call cancel_session."""
        mock_cancel.return_value = {"status": "ok", "cancelled": 1}
        from runtime.cli import _handle_session
        import argparse
        args = argparse.Namespace(
            session_action="send",
            name="test-sess",
            prompt="hello",
            file="",
            repo=".",
            json=False,
            no_wait=False,
        )
        exit_code = _handle_session(args)
        self.assertEqual(exit_code, 130)
        mock_cancel.assert_called_once()
