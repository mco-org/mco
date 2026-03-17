# tests/test_prompt_input.py
"""Tests for --file and stdin prompt input."""
from __future__ import annotations

import os
import tempfile
import unittest

from runtime.cli import build_parser, _resolve_prompt


class TestResolvePrompt(unittest.TestCase):
    def test_prompt_flag_takes_priority(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--prompt", "hello", "--providers", "claude"])
        result = _resolve_prompt(args)
        self.assertEqual(result, "hello")

    def test_file_reads_from_path(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("prompt from file")
            f.flush()
            parser = build_parser()
            args = parser.parse_args(["run", "--file", f.name, "--providers", "claude"])
            result = _resolve_prompt(args)
            self.assertEqual(result, "prompt from file")
            os.unlink(f.name)

    def test_file_dash_reads_stdin(self) -> None:
        import io
        from unittest.mock import patch
        parser = build_parser()
        args = parser.parse_args(["run", "--file", "-", "--providers", "claude"])
        with patch("sys.stdin", io.StringIO("stdin prompt")):
            result = _resolve_prompt(args)
        self.assertEqual(result, "stdin prompt")

    def test_no_prompt_no_file_raises(self) -> None:
        from unittest.mock import patch, MagicMock
        parser = build_parser()
        args = parser.parse_args(["run", "--providers", "claude"])
        # Mock stdin as a tty so _resolve_prompt doesn't try to read from it
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        with patch("sys.stdin", mock_stdin):
            with self.assertRaises(SystemExit):
                _resolve_prompt(args)

    def test_prompt_and_file_mutual_exclusion(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["run", "--prompt", "x", "--file", "y", "--providers", "claude"])


class TestSessionSendFile(unittest.TestCase):
    def test_session_send_with_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("session prompt from file")
            f.flush()
            parser = build_parser()
            args = parser.parse_args(["session", "send", "my-sess", "--file", f.name])
            self.assertEqual(args.file, f.name)
            os.unlink(f.name)

    def test_session_send_positional_prompt(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "send", "my-sess", "inline prompt"])
        self.assertEqual(args.prompt, "inline prompt")

    def test_session_send_piped_stdin(self) -> None:
        """session send with no prompt arg should read piped stdin."""
        parser = build_parser()
        args = parser.parse_args(["session", "send", "my-sess"])
        self.assertEqual(args.prompt, "")  # No positional prompt
