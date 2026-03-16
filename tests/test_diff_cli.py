"""Tests for diff-related CLI flags."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.cli import build_parser, main


class TestDiffFlagParsing(unittest.TestCase):
    def test_diff_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--diff"])
        self.assertTrue(args.diff)

    def test_staged_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--staged"])
        self.assertTrue(args.staged)

    def test_unstaged_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--unstaged"])
        self.assertTrue(args.unstaged)

    def test_diff_and_staged_mutually_exclusive(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--diff", "--staged"])

    def test_diff_base_without_diff_flag(self) -> None:
        """--diff-base alone should be valid (implies --diff)."""
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--diff-base", "origin/main"])
        self.assertEqual(args.diff_base, "origin/main")

    def test_diff_base_with_staged_rejected(self) -> None:
        """--diff-base + --staged is rejected at runtime."""
        with patch("runtime.review_engine.run_review") as mock_run:
            exit_code = main(["review", "--repo", ".", "--prompt", "t", "--staged", "--diff-base", "x"])
            self.assertEqual(exit_code, 2)
            mock_run.assert_not_called()

    def test_diff_base_with_unstaged_rejected(self) -> None:
        """--diff-base + --unstaged is rejected at runtime."""
        with patch("runtime.review_engine.run_review") as mock_run:
            exit_code = main(["review", "--repo", ".", "--prompt", "t", "--unstaged", "--diff-base", "x"])
            self.assertEqual(exit_code, 2)
            mock_run.assert_not_called()

    def test_run_mode_also_accepts_diff(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--repo", ".", "--prompt", "test", "--diff"])
        self.assertTrue(args.diff)
