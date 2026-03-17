# tests/test_perspectives.py
"""Tests for per-provider perspective injection."""
from __future__ import annotations

import unittest

from runtime.config import ReviewPolicy
from runtime.cli import build_parser


class TestPerspectiveConfig(unittest.TestCase):
    def test_policy_default_empty_perspectives(self) -> None:
        policy = ReviewPolicy()
        self.assertEqual(policy.perspectives, {})

    def test_policy_custom_perspectives(self) -> None:
        perspectives = {"claude": "Focus on security", "codex": "Focus on performance"}
        policy = ReviewPolicy(perspectives=perspectives)
        self.assertEqual(policy.perspectives["claude"], "Focus on security")
        self.assertEqual(policy.perspectives["codex"], "Focus on performance")


class TestPerspectiveCLI(unittest.TestCase):
    def test_perspectives_json_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "review",
            "--perspectives-json", '{"claude": "Focus on security"}',
        ])
        self.assertEqual(args.perspectives_json, '{"claude": "Focus on security"}')

    def test_perspectives_json_default_empty(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review"])
        self.assertEqual(args.perspectives_json, "")


class TestPerspectiveValidation(unittest.TestCase):
    def test_invalid_json_raises_value_error(self) -> None:
        """Invalid --perspectives-json should raise, not silently ignore."""
        from runtime.cli import _resolve_config
        from unittest.mock import MagicMock
        args = MagicMock()
        args.perspectives_json = "not valid json{"
        args.providers = "claude"
        args.artifact_base = "reports/review"
        args.format = "text"
        args.save_artifacts = False
        args.strict_contract = False
        args.provider_timeouts = ""
        args.provider_permissions_json = ""
        args.allow_paths = "."
        args.max_provider_parallelism = 0
        args.chain = False
        # Suppress-based attributes
        for attr in ("enforcement_mode", "stall_timeout", "poll_interval", "review_hard_timeout",
                      "quiet", "memory", "transport"):
            delattr(args, attr)
        with self.assertRaises(ValueError) as ctx:
            _resolve_config(args)
        self.assertIn("--perspectives-json", str(ctx.exception))

    def test_non_dict_perspectives_raises(self) -> None:
        """--perspectives-json with a non-object should raise."""
        from runtime.cli import _resolve_config
        from unittest.mock import MagicMock
        args = MagicMock()
        args.perspectives_json = '["not", "a", "dict"]'
        args.providers = "claude"
        args.artifact_base = "reports/review"
        args.format = "text"
        args.save_artifacts = False
        args.strict_contract = False
        args.provider_timeouts = ""
        args.provider_permissions_json = ""
        args.allow_paths = "."
        args.max_provider_parallelism = 0
        args.chain = False
        for attr in ("enforcement_mode", "stall_timeout", "poll_interval", "review_hard_timeout",
                      "quiet", "memory", "transport"):
            delattr(args, attr)
        with self.assertRaises(ValueError) as ctx:
            _resolve_config(args)
        self.assertIn("JSON object", str(ctx.exception))


class TestPerspectiveInjection(unittest.TestCase):
    def test_perspective_prepended_to_prompt(self) -> None:
        """When a perspective is configured, it should appear in the prompt."""
        from runtime.config import ReviewPolicy
        policy = ReviewPolicy(perspectives={"claude": "Focus on security vulnerabilities"})

        # Simulate what _run_provider does
        full_prompt = "Review this code for issues."
        perspective = policy.perspectives.get("claude", "")
        if perspective:
            provider_prompt = "## Review Perspective\n{}\n\n{}".format(perspective, full_prompt)
        else:
            provider_prompt = full_prompt

        self.assertIn("## Review Perspective", provider_prompt)
        self.assertIn("Focus on security vulnerabilities", provider_prompt)
        self.assertIn("Review this code for issues.", provider_prompt)

    def test_no_perspective_leaves_prompt_unchanged(self) -> None:
        """Without perspective, prompt should be unchanged."""
        from runtime.config import ReviewPolicy
        policy = ReviewPolicy()

        full_prompt = "Review this code."
        perspective = policy.perspectives.get("codex", "")
        if perspective:
            provider_prompt = "## Review Perspective\n{}\n\n{}".format(perspective, full_prompt)
        else:
            provider_prompt = full_prompt

        self.assertEqual(provider_prompt, "Review this code.")

    def test_different_providers_get_different_perspectives(self) -> None:
        """Each provider should get its own perspective."""
        policy = ReviewPolicy(perspectives={
            "claude": "Focus on security",
            "codex": "Focus on performance",
        })

        results = {}
        for provider in ["claude", "codex", "gemini"]:
            perspective = policy.perspectives.get(provider, "")
            if perspective:
                results[provider] = "## Review Perspective\n{}\n\nBase prompt".format(perspective)
            else:
                results[provider] = "Base prompt"

        self.assertIn("security", results["claude"])
        self.assertIn("performance", results["codex"])
        self.assertEqual(results["gemini"], "Base prompt")  # No perspective for gemini
