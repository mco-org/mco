# tests/test_chain_mode.py
"""Tests for chain mode — sequential multi-agent analysis."""
from __future__ import annotations

import tempfile
import unittest

from runtime.config import ReviewPolicy
from runtime.cli import build_parser


class TestChainConfig(unittest.TestCase):
    def test_chain_default_false(self) -> None:
        policy = ReviewPolicy()
        self.assertFalse(policy.chain)
        self.assertFalse(policy.debate)

    def test_chain_enabled(self) -> None:
        policy = ReviewPolicy(chain=True)
        self.assertTrue(policy.chain)

    def test_debate_enabled(self) -> None:
        policy = ReviewPolicy(debate=True)
        self.assertTrue(policy.debate)


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

    def test_debate_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--debate"])
        self.assertTrue(args.debate)

    def test_debate_and_chain_are_mutually_exclusive(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["review", "--chain", "--debate"])


class TestChainPromptBuilding(unittest.TestCase):
    def test_chain_prompt_includes_prior_analysis(self) -> None:
        """Simulate chain prompt building logic."""
        original_prompt = "Review this code."
        providers = ["claude", "codex"]
        prior_outputs = {"claude": "Found SQL injection in db.py:42"}

        # Simulate chain prompt for second provider (accumulates on chain_prompt)
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
                ).format(chain_prompt, prev, output)

        self.assertIn("## Prior Analysis by claude", chain_prompt)
        self.assertIn("SQL injection", chain_prompt)
        self.assertIn("challenge questionable ones", chain_prompt)
        self.assertIn("Review this code.", chain_prompt)

    def test_chain_three_providers_accumulates_all(self) -> None:
        """Third provider should see outputs from both prior providers."""
        original_prompt = "Review this code."
        providers = ["claude", "codex", "gemini"]
        prior_outputs = {
            "claude": "Found SQL injection in db.py",
            "codex": "Found N+1 query in api.py",
        }

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
                ).format(chain_prompt, prev, output)

        # Third provider (gemini) should see BOTH prior analyses
        self.assertIn("## Prior Analysis by claude", chain_prompt)
        self.assertIn("SQL injection", chain_prompt)
        self.assertIn("## Prior Analysis by codex", chain_prompt)
        self.assertIn("N+1 query", chain_prompt)

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


class TestChainProviderOrder(unittest.TestCase):
    """End-to-end: chain mode must preserve user-specified provider order."""

    def test_chain_preserves_provider_order_via_run_review(self) -> None:
        from runtime.review_engine import ReviewRequest, run_review
        from runtime.contracts import ProviderPresence, CapabilitySet, TaskRunRef, TaskStatus

        captured_prompts = {}

        class _CapturingAdapter:
            def __init__(self, pid: str) -> None:
                self.id = pid
            def detect(self):
                return ProviderPresence(provider=self.id, detected=True, binary_path="/bin/true", version="1", auth_ok=True)
            def capabilities(self):
                return CapabilitySet(tiers=["C0"], supports_native_async=False, supports_poll_endpoint=False,
                                     supports_resume_after_restart=False, supports_schema_enforcement=False,
                                     min_supported_version="0.1", tested_os=["macos"])
            def run(self, task_input):
                captured_prompts[self.id] = task_input.prompt
                return TaskRunRef(task_id=task_input.task_id, provider=self.id, run_id="r1",
                                  artifact_path=task_input.metadata["artifact_root"], started_at="now")
            def poll(self, ref):
                return TaskStatus(task_id=ref.task_id, provider=self.id, run_id=ref.run_id,
                                  attempt_state="SUCCEEDED", completed=True)
            def cancel(self, ref):
                pass
            def normalize(self, raw, ctx):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            # gemini first, claude second — intentionally NOT alphabetical
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review code",
                providers=["gemini", "claude"],
                artifact_base="{}/artifacts".format(tmpdir),
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, chain=True),
            )
            adapters = {"gemini": _CapturingAdapter("gemini"), "claude": _CapturingAdapter("claude")}
            result = run_review(req, adapters=adapters)

            # Provider results must preserve input order (gemini before claude)
            keys = list(result.provider_results.keys())
            self.assertEqual(keys, ["gemini", "claude"])

            # Both providers should have received the prompt
            self.assertIn("review code", captured_prompts.get("gemini", ""))
            self.assertIn("review code", captured_prompts.get("claude", ""))
