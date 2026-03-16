"""Tests for session CLI subcommand parsing."""
from __future__ import annotations

import unittest

from runtime.cli import build_parser


class TestSessionCLIParsing(unittest.TestCase):
    def test_session_start_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "start", "--provider", "claude"])
        self.assertEqual(args.session_action, "start")
        self.assertEqual(args.provider, "claude")

    def test_session_start_with_name(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "start", "--provider", "claude", "--name", "my-review"])
        self.assertEqual(args.name, "my-review")

    def test_session_send_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "send", "my-review", "review auth.py"])
        self.assertEqual(args.session_action, "send")
        self.assertEqual(args.name, "my-review")
        self.assertEqual(args.prompt, "review auth.py")

    def test_session_broadcast_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "broadcast", "summarize findings"])
        self.assertEqual(args.session_action, "broadcast")
        self.assertEqual(args.prompt, "summarize findings")

    def test_session_list_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "list"])
        self.assertEqual(args.session_action, "list")

    def test_session_stop_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "stop", "my-review"])
        self.assertEqual(args.session_action, "stop")
        self.assertEqual(args.name, "my-review")

    def test_session_history_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "history", "my-review"])
        self.assertEqual(args.session_action, "history")

    def test_session_resume_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "resume", "my-review"])
        self.assertEqual(args.session_action, "resume")

    def test_session_cancel_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "cancel", "my-review"])
        self.assertEqual(args.session_action, "cancel")
        self.assertEqual(args.name, "my-review")

    def test_session_cancel_json(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "cancel", "my-review", "--json"])
        self.assertTrue(args.json)

    def test_session_queue_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "queue", "my-review"])
        self.assertEqual(args.session_action, "queue")
        self.assertEqual(args.name, "my-review")

    def test_session_queue_json(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["session", "queue", "my-review", "--json"])
        self.assertTrue(args.json)

    def test_session_requires_action(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["session"])
