# tests/test_quiet_mode.py
"""Tests for --quiet output mode."""
from __future__ import annotations

import unittest

from runtime.cli import build_parser


class TestQuietFlag(unittest.TestCase):
    def test_quiet_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--prompt", "test", "--providers", "claude", "--quiet"])
        self.assertTrue(args.quiet)

    def test_quiet_default_suppressed(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--prompt", "test", "--providers", "claude"])
        # With argparse.SUPPRESS, quiet attr is absent when not passed
        self.assertFalse(getattr(args, "quiet", False))

    def test_quiet_and_json_mutual_exclusion(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["run", "--prompt", "test", "--quiet", "--json"])

    def test_quiet_and_stream_mutual_exclusion(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["run", "--prompt", "test", "--quiet", "--stream", "jsonl"])
