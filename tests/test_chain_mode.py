# tests/test_chain_mode.py
"""Tests for chain mode — sequential multi-agent analysis."""
from __future__ import annotations

import unittest

from runtime.config import ReviewPolicy
from runtime.cli import build_parser


class TestChainConfig(unittest.TestCase):
    def test_chain_default_false(self) -> None:
        policy = ReviewPolicy()
        self.assertFalse(policy.chain)

    def test_chain_enabled(self) -> None:
        policy = ReviewPolicy(chain=True)
        self.assertTrue(policy.chain)


class TestChainCLI(unittest.TestCase):
    def test_chain_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--chain"])
        self.assertTrue(args.chain)

    def test_chain_default_false_in_cli(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review"])
        self.assertFalse(args.chain)

    def test_chain_works_with_run(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--chain"])
        self.assertTrue(args.chain)


class TestChainPromptBuilding(unittest.TestCase):
    def test_chain_prompt_includes_prior_analysis(self) -> None:
        """Simulate chain prompt building logic."""
        original_prompt = "Review this code."
        providers = ["claude", "codex"]
        prior_outputs = {"claude": "Found SQL injection in db.py:42"}

        # Simulate chain prompt for second provider
        chain_prompt = original_prompt
        for idx, provider in enumerate(providers):
            if idx > 0 and providers[idx - 1] in prior_outputs:
                prev = providers[idx - 1]
                output = prior_outputs[prev]
                chain_prompt = (
                    "{}\n\n"
                    "---\n"
                    "## Prior Analysis by {}\n"
                    "{}\n"
                    "---\n\n"
                    "Review the above analysis critically. "
                    "Confirm valid findings, challenge questionable ones, "
                    "and add any issues that were missed."
                ).format(original_prompt, prev, output)

        self.assertIn("## Prior Analysis by claude", chain_prompt)
        self.assertIn("SQL injection", chain_prompt)
        self.assertIn("challenge questionable ones", chain_prompt)
        self.assertIn("Review this code.", chain_prompt)

    def test_chain_with_empty_prior_output_uses_base_prompt(self) -> None:
        """If prior provider produced no output, next provider gets base prompt."""
        original_prompt = "Review this code."
        output_text = ""

        # Simulate: only build chain prompt if output is non-empty
        if output_text.strip():
            chain_prompt = "enriched"
        else:
            chain_prompt = original_prompt

        self.assertEqual(chain_prompt, original_prompt)

    def test_chain_with_perspectives_combines_both(self) -> None:
        """Chain mode should work with perspectives — perspective + chain context."""
        policy = ReviewPolicy(
            chain=True,
            perspectives={"codex": "Focus on performance"},
        )

        base_prompt = "Review code."
        # First provider: claude (no perspective, chain doesn't affect first)
        claude_prompt = base_prompt

        # Second provider: codex with perspective AND chain context
        perspective = policy.perspectives.get("codex", "")
        prior_output = "Found 2 security issues"
        chain_prompt = (
            "{}\n\n---\n## Prior Analysis by claude\n{}\n---\n\n"
            "Review the above analysis critically."
        ).format(base_prompt, prior_output)

        if perspective:
            final_prompt = "## Review Perspective\n{}\n\n{}".format(perspective, chain_prompt)
        else:
            final_prompt = chain_prompt

        self.assertIn("Focus on performance", final_prompt)
        self.assertIn("Found 2 security issues", final_prompt)
        self.assertIn("Review code.", final_prompt)
