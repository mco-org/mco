from __future__ import annotations

import unittest

from runtime.hooks import RunHooks


class TestRunHooks(unittest.TestCase):
    def test_empty_hooks_returns_none_for_pre_run(self):
        hooks = RunHooks()
        result = hooks.invoke_pre_run(prompt="test", repo_root="/tmp", providers=["claude"])
        self.assertIsNone(result)

    def test_empty_hooks_returns_none_for_post_run(self):
        hooks = RunHooks()
        result = hooks.invoke_post_run(
            findings=[],
            provider_results={},
            repo_root="/tmp",
            prompt="test",
            providers=["claude"],
        )
        self.assertIsNone(result)

    def test_pre_run_receives_args_and_returns_prompt(self):
        captured = {}

        def my_hook(prompt, repo_root, providers):
            captured["prompt"] = prompt
            captured["repo_root"] = repo_root
            captured["providers"] = providers
            return prompt + "\n\n[injected context]"

        hooks = RunHooks()
        hooks.set_pre_run(my_hook)
        result = hooks.invoke_pre_run(prompt="review this", repo_root="/repo", providers=["claude", "gemini"])
        self.assertEqual(result, "review this\n\n[injected context]")
        self.assertEqual(captured["repo_root"], "/repo")
        self.assertEqual(captured["providers"], ["claude", "gemini"])

    def test_post_run_receives_findings(self):
        captured = {}

        def my_hook(findings, provider_results, repo_root, prompt, providers):
            captured["findings"] = findings
            captured["provider_results"] = provider_results

        hooks = RunHooks()
        hooks.set_post_run(my_hook)
        findings = [{"title": "SQL injection", "severity": "high"}]
        provider_results = {"claude": {"success": True}}
        hooks.invoke_post_run(
            findings=findings,
            provider_results=provider_results,
            repo_root="/repo",
            prompt="test",
            providers=["claude"],
        )
        self.assertEqual(captured["findings"], findings)
        self.assertEqual(captured["provider_results"], provider_results)

    def test_pre_run_exception_logged_not_raised(self):
        def bad_hook(prompt, repo_root, providers):
            raise RuntimeError("boom")

        hooks = RunHooks()
        hooks.set_pre_run(bad_hook)
        result = hooks.invoke_pre_run(prompt="test", repo_root="/tmp", providers=["claude"])
        self.assertIsNone(result)

    def test_post_run_exception_logged_not_raised(self):
        def bad_hook(findings, provider_results, repo_root, prompt, providers):
            raise RuntimeError("boom")

        hooks = RunHooks()
        hooks.set_post_run(bad_hook)
        result = hooks.invoke_post_run(
            findings=[],
            provider_results={},
            repo_root="/tmp",
            prompt="test",
            providers=["claude"],
        )
        self.assertIsNone(result)

    def test_set_overwrites_previous(self):
        """Second set_pre_run replaces the first -- single slot, not a list."""
        calls = []

        def hook_a(prompt, repo_root, providers):
            calls.append("a")
            return prompt

        def hook_b(prompt, repo_root, providers):
            calls.append("b")
            return prompt

        hooks = RunHooks()
        hooks.set_pre_run(hook_a)
        hooks.set_pre_run(hook_b)
        hooks.invoke_pre_run(prompt="test", repo_root="/tmp", providers=["claude"])
        self.assertEqual(calls, ["b"])


if __name__ == "__main__":
    unittest.main()
