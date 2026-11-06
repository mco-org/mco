from __future__ import annotations

import json
import subprocess
from pathlib import Path
import unittest
from unittest.mock import patch

from runtime.adapters.kimi import KimiAdapter
from runtime.contracts import TaskInput


def _task(access=None, model="") -> TaskInput:
    permissions = {} if access is None else {"access": access}
    return TaskInput(
        task_id="test",
        prompt="Review this repository.",
        repo_root="/tmp",
        target_paths=["."],
        metadata={"provider_permissions": permissions, "model": model},
    )


def _stream(*messages) -> str:
    return "\n".join(json.dumps(message) for message in messages)


class KimiAdapterTests(unittest.TestCase):
    def test_detect_defers_auth_without_starting_inference_or_login(self) -> None:
        with patch.object(KimiAdapter, "_resolve_binary", return_value="kimi"), \
                patch("runtime.adapters.shim.subprocess.run", return_value=subprocess.CompletedProcess(["kimi", "--version"], 0, "2.5.2", "")) as run:
            presence = KimiAdapter().detect()
        self.assertTrue(presence.detected)
        self.assertEqual(presence.reason, "auth_deferred_to_run")
        self.assertEqual(run.call_count, 1)
        self.assertEqual(run.call_args.args[0], ["kimi", "--version"])

    def test_detect_rejects_legacy_unsupported_and_unknown_versions(self) -> None:
        versions = (
            ("kimi, version 1.52.0\nkimi-cli is no longer maintained. Please use the new Kimi Code CLI.\n", "unsupported_version"),
            ("2.4.9", "unsupported_version"),
            ("2.5.1", "unsupported_version"),
            ("custom development build", "version_not_verified"),
            ("", "version_not_verified"),
        )
        for output, reason in versions:
            with self.subTest(output=output), \
                    patch.object(KimiAdapter, "_resolve_binary", return_value="kimi"), \
                    patch("runtime.adapters.shim.subprocess.run", return_value=subprocess.CompletedProcess(["kimi", "--version"], 0, output, "")):
                presence = KimiAdapter().detect()
                self.assertFalse(presence.auth_ok)
                self.assertEqual(presence.reason, reason)

    def test_decoder_preserves_unicode_line_separators_in_json_strings(self) -> None:
        answer = "before\u2028middle\u2029after"
        raw = json.dumps({"role": "assistant", "content": answer}, ensure_ascii=False) + "\n"
        self.assertEqual(KimiAdapter().decode_transport(raw).final_answer, answer)

    def test_default_command_uses_headless_read_only_profile(self) -> None:
        command = KimiAdapter()._build_command(_task())
        self.assertEqual(command[:5], ["kimi", "-p", "Review this repository.", "--output-format", "stream-json"])
        profile = Path(command[command.index("--agent-file") + 1])
        self.assertTrue(profile.is_absolute())
        text = profile.read_text(encoding="utf-8")
        self.assertIn("tools: [Read, Grep, Glob]", text)
        self.assertIn("${base_prompt}", text)
        for flag in ("--print", "--plan", "--yolo", "--auto", "--continue", "--session"):
            self.assertNotIn(flag, command)

    def test_write_profile_has_file_tools_without_shell_or_delegation(self) -> None:
        command = KimiAdapter()._build_command(_task("write"))
        text = Path(command[command.index("--agent-file") + 1]).read_text(encoding="utf-8")
        self.assertIn("tools: [Read, Grep, Glob, Write, Edit]", text)
        for tool in ("Bash", "Agent", "Skill", "mcp__"):
            self.assertNotIn(tool, text)

    def test_yolo_uses_native_print_permissions_without_conflicting_flags(self) -> None:
        command = KimiAdapter()._build_command(_task("yolo", " kimi-code/k3 "))
        self.assertNotIn("--agent-file", command)
        self.assertNotIn("--yolo", command)
        self.assertNotIn("--auto", command)
        self.assertEqual(command[-2:], ["--model", "kimi-code/k3"])

    def test_unknown_access_is_rejected_before_launch(self) -> None:
        for access in ("plan", "unsafe", True):
            with self.subTest(access=access), self.assertRaises(ValueError):
                KimiAdapter()._build_command(_task(access))

    def test_missing_profile_fails_closed(self) -> None:
        with patch("runtime.adapters.kimi.Path.is_file", return_value=False):
            with self.assertRaisesRegex(ValueError, "profile"):
                KimiAdapter()._build_command(_task())

    def test_decoder_excludes_tools_and_earlier_assistant_commentary(self) -> None:
        raw = _stream(
            {"role": "meta", "type": "system.version", "version": "2.5.2"},
            {"role": "assistant", "content": "I will read it.", "tool_calls": [{"id": "1"}]},
            {"role": "tool", "content": "Do not include this tool output"},
            {"role": "assistant", "content": "Final answer"},
            {"role": "meta", "type": "session.resume_hint", "content": "resume command"},
        )
        result = KimiAdapter().decode_transport(raw)
        self.assertEqual(result.final_answer, "Final answer")
        self.assertEqual(result.status, "succeeded")
        self.assertEqual("".join(delta.text for delta in result.deltas), "I will read it.Final answer")

    def test_decoder_supports_legacy_blocks_without_reasoning(self) -> None:
        raw = _stream({"role": "assistant", "content": [
            {"type": "think", "think": "private"},
            {"type": "text", "text": "Final "},
            {"type": "text", "text": "answer"},
        ]})
        self.assertEqual(KimiAdapter().decode_transport(raw).final_answer, "Final answer")

    def test_decoder_supports_string_content_and_ignores_invalid_lines(self) -> None:
        raw = "invalid\n[]\n" + _stream({"role": "assistant", "content": "Answer"})
        self.assertEqual(KimiAdapter().decode_transport(raw).final_answer, "Answer")

    def test_empty_or_tool_only_output_is_not_success(self) -> None:
        adapter = KimiAdapter()
        for raw in ("", "not JSON", _stream({"role": "tool", "content": "output"}), _stream({"role": "assistant", "content": "", "tool_calls": [{"id": "1"}]})):
            with self.subTest(raw=raw):
                self.assertFalse(adapter._is_success(0, raw, ""))

    def test_nonzero_exit_or_explicit_error_is_not_success(self) -> None:
        adapter = KimiAdapter()
        raw = _stream({"role": "assistant", "content": "partial"})
        self.assertFalse(adapter._is_success(1, raw, "failed"))
        raw += "\n" + _stream({"type": "error", "message": "session occupied"})
        self.assertEqual(adapter.decode_transport(raw).status, "failed")
        self.assertFalse(adapter._is_success(0, raw, ""))


if __name__ == "__main__":
    unittest.main()
