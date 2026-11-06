from __future__ import annotations

import unittest

from runtime.adapters.agy import AgyAdapter
from runtime.adapters.codex import CodexAdapter
from runtime.adapters.grok import GrokAdapter
from runtime.contracts import TaskInput


def _task(permissions: dict[str, str]) -> TaskInput:
    return TaskInput(
        task_id="current-cli",
        prompt="Review this repository.",
        repo_root="/tmp",
        target_paths=["."],
        timeout_seconds=60,
        metadata={"provider_permissions": permissions},
    )


class CurrentCliAdapterTests(unittest.TestCase):
    def test_codex_does_not_treat_failed_mcp_startup_as_success(self) -> None:
        raw = '{"type":"error","message":"required MCP server failed to initialize"}\n'
        self.assertFalse(CodexAdapter()._is_success(1, raw, "MCP client startup failed"))

    def test_codex_nonzero_exit_is_not_overridden_by_completion_event(self) -> None:
        raw = '{"type":"turn.completed","usage":{"input_tokens":1,"output_tokens":1}}\n'
        self.assertFalse(CodexAdapter()._is_success(1, raw, "turn failed"))

    def test_codex_success_with_nonfatal_mcp_warning(self) -> None:
        raw = '{"type": "turn.completed", "usage": {"input_tokens": 1}}\n'
        self.assertTrue(CodexAdapter()._is_success(0, raw, "MCP client warning"))

    def test_agy_accepts_current_auto_mode_with_sandbox(self) -> None:
        command = AgyAdapter()._build_command(_task({"mode": "auto"}))
        self.assertEqual(command[command.index("--mode") + 1], "auto")
        self.assertIn("--sandbox", command)
        self.assertNotIn("--dangerously-skip-permissions", command)

    def test_grok_accepts_current_permission_modes(self) -> None:
        for mode in ("default", "auto", "dontAsk"):
            with self.subTest(mode=mode):
                command = GrokAdapter()._build_command(_task({"permission_mode": mode}))
                self.assertEqual(command[command.index("--permission-mode") + 1], mode)
                self.assertNotIn("--always-approve", command)

    def test_grok_still_rejects_unknown_permission_mode(self) -> None:
        with self.assertRaises(ValueError):
            GrokAdapter()._build_command(_task({"permission_mode": "unsafe"}))

    def test_grok_headless_permission_refusal_is_not_success(self) -> None:
        # Grok 1.0.77 returns zero and leaves its pre-tool text on stdout.
        stdout = "I'll read `fixture.txt` and write the same text into `result.txt`.\n"
        stderr = (
            "permission required: Execute `od -An -tx1 fixture.txt | head -5; wc -c fixture.txt` "
            "was not run, as a headless run cannot ask for approval\n"
        )
        self.assertFalse(GrokAdapter()._is_success(0, stdout, stderr))

    def test_grok_permission_words_in_answers_and_unrelated_warnings_are_allowed(self) -> None:
        stdout = "Explain why permission required: Edit was not run, as a headless run cannot ask for approval."
        self.assertTrue(GrokAdapter()._is_success(0, stdout, "warning: permission required by another program\n"))

    def test_grok_nonzero_or_empty_output_is_not_success(self) -> None:
        self.assertFalse(GrokAdapter()._is_success(1, "partial answer", ""))
        self.assertFalse(GrokAdapter()._is_success(0, "", ""))


if __name__ == "__main__":
    unittest.main()
