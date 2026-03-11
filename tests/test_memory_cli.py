# tests/test_memory_cli.py
from __future__ import annotations

import unittest

from runtime.cli import build_parser, main


class TestMemoryCliArgs(unittest.TestCase):
    def test_memory_flag_accepted_on_review(self):
        parser = build_parser()
        args = parser.parse_args([
            "review", "--repo", ".", "--prompt", "test", "--memory",
        ])
        self.assertTrue(args.memory)

    def test_memory_flag_accepted_on_run(self):
        parser = build_parser()
        args = parser.parse_args([
            "run", "--repo", ".", "--prompt", "test", "--memory",
        ])
        self.assertTrue(args.memory)

    def test_space_flag_accepted(self):
        parser = build_parser()
        args = parser.parse_args([
            "review", "--repo", ".", "--prompt", "test",
            "--memory", "--space", "coding:my-repo",
        ])
        self.assertEqual(args.space, "coding:my-repo")

    def test_space_without_memory_returns_exit_code_2(self):
        """--space without --memory should return 2 (not SystemExit from argparse)."""
        exit_code = main(["review", "--repo", ".", "--prompt", "test", "--space", "coding:my-repo"])
        self.assertEqual(exit_code, 2)

    def test_no_memory_flag_defaults_false(self):
        parser = build_parser()
        args = parser.parse_args([
            "review", "--repo", ".", "--prompt", "test",
        ])
        self.assertFalse(args.memory)


class TestReviewRequestMemoryField(unittest.TestCase):
    def test_review_request_has_memory_fields(self):
        from runtime.review_engine import ReviewRequest
        from runtime.config import ReviewPolicy

        req = ReviewRequest(
            repo_root="/tmp",
            prompt="test",
            providers=["claude"],
            artifact_base="/tmp/artifacts",
            policy=ReviewPolicy(),
            memory_enabled=True,
            memory_space="coding:test-repo",
        )
        self.assertTrue(req.memory_enabled)
        self.assertEqual(req.memory_space, "coding:test-repo")

    def test_review_request_memory_defaults(self):
        from runtime.review_engine import ReviewRequest
        from runtime.config import ReviewPolicy

        req = ReviewRequest(
            repo_root="/tmp",
            prompt="test",
            providers=["claude"],
            artifact_base="/tmp/artifacts",
            policy=ReviewPolicy(),
        )
        self.assertFalse(req.memory_enabled)
        self.assertIsNone(req.memory_space)


if __name__ == "__main__":
    unittest.main()
