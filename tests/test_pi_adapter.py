from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.adapters.pi import PiAdapter
from runtime.contracts import NormalizeContext, TaskInput


class TestPiAdapterBuildCommand(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = PiAdapter()

    def test_build_command_basic(self) -> None:
        task = TaskInput(
            task_id="test-1",
            prompt="Review for bugs",
            repo_root="/tmp",
            target_paths=["."],
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("pi", cmd)
        self.assertIn("-p", cmd)
        self.assertIn("--mode", cmd)
        self.assertIn("json", cmd)
        self.assertIn("Review for bugs", cmd)
        self.assertIn("--no-session", cmd)
        self.assertIn("--no-context-files", cmd)
        self.assertIn("--no-skills", cmd)
        self.assertIn("--no-extensions", cmd)
        # Strict read-only allowlist
        self.assertIn("--tools", cmd)
        tools_idx = cmd.index("--tools")
        tools_value = cmd[tools_idx + 1]
        self.assertEqual(tools_value, "read,grep,find,ls")
        # Assert no write/edit/bash in allowlist
        for forbidden in ("bash", "edit", "write"):
            self.assertNotIn(forbidden, tools_value.split(","))
        # Assert no dangerous flags
        self.assertNotIn("--no-tools", cmd)
        self.assertNotIn("--approve", cmd)

    def test_build_command_metadata_does_not_override_tools(self) -> None:
        """Metadata full_tools/tools keys are ignored — allowlist is locked."""
        for meta in (
            {"full_tools": True},
            {"tools": "read,ls,bash"},
            {"full_tools": True, "tools": "bash"},
        ):
            task = TaskInput(
                task_id="test-locked",
                prompt="Review",
                repo_root="/tmp",
                target_paths=["."],
                metadata=meta,
            )
            cmd = self.adapter._build_command(task)
            self.assertIn("--tools", cmd, f"metadata={meta} removed --tools")
            tools_idx = cmd.index("--tools")
            tools_value = cmd[tools_idx + 1]
            self.assertEqual(tools_value, "read,grep,find,ls",
                             f"metadata={meta} changed allowlist to {tools_value}")

    def test_build_command_with_model(self) -> None:
        task = TaskInput(
            task_id="test-2",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"model": "gpt-5.4"},
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("--model", cmd)
        self.assertIn("gpt-5.4", cmd)

    def test_build_command_with_provider(self) -> None:
        task = TaskInput(
            task_id="test-3",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"provider": "openai-codex"},
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("--provider", cmd)
        self.assertIn("openai-codex", cmd)

    def test_build_command_ignores_empty_metadata(self) -> None:
        task = TaskInput(
            task_id="test-4",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"model": "", "provider": "  "},
        )
        cmd = self.adapter._build_command(task)
        self.assertNotIn("--model", cmd)
        self.assertNotIn("--provider", cmd)


class TestPiAdapterIsSuccess(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = PiAdapter()

    def test_success_with_agent_end(self) -> None:
        jsonl = '{"type":"agent_end","messages":[]}'
        self.assertTrue(
            self.adapter._is_success(0, jsonl, "")
        )

    def test_failure_no_agent_end(self) -> None:
        self.assertFalse(
            self.adapter._is_success(0, "some text", "")
        )

    def test_failure_non_zero_exit(self) -> None:
        self.assertFalse(
            self.adapter._is_success(1, '{"type":"agent_end"}', "")
        )

    def test_failure_empty_output(self) -> None:
        self.assertFalse(
            self.adapter._is_success(0, "", "")
        )


class TestPiAdapterExtractText(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = PiAdapter()

    def test_extract_from_text_deltas(self) -> None:
        jsonl = (
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Hello"}}\n'
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":" World"}}\n'
            '{"type":"agent_end"}\n'
        )
        result = self.adapter._extract_final_text_from_jsonl(jsonl)
        self.assertEqual(result, "Hello World")

    def test_extract_ignores_non_text_delta(self) -> None:
        jsonl = (
            '{"type":"message_update","assistantMessageEvent":{"type":"thinking_delta","delta":"Hmm"}}\n'
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"Result"}}\n'
        )
        result = self.adapter._extract_final_text_from_jsonl(jsonl)
        self.assertEqual(result, "Result")

    def test_extract_empty_jsonl(self) -> None:
        self.assertEqual(self.adapter._extract_final_text_from_jsonl(""), "")

    def test_extract_invalid_json_lines(self) -> None:
        jsonl = "not json\n{'type':'text_delta'}\n"
        result = self.adapter._extract_final_text_from_jsonl(jsonl)
        self.assertEqual(result, "")

    def test_extract_from_agent_end(self) -> None:
        jsonl = (
            '{"type":"agent_end","messages":['
            '{"role":"user","content":[]},'
            '{"role":"assistant","content":[{"type":"text","text":"Final answer"}]}'
            ']}'
        )
        result = self.adapter._extract_from_agent_end(jsonl)
        self.assertEqual(result, "Final answer")

    def test_extract_from_agent_end_no_assistant(self) -> None:
        jsonl = '{"type":"agent_end","messages":[{"role":"user","content":[]}]}'
        result = self.adapter._extract_from_agent_end(jsonl)
        self.assertEqual(result, "")

    def test_extract_from_agent_end_empty(self) -> None:
        self.assertEqual(self.adapter._extract_from_agent_end(""), "")


class TestPiAdapterNormalize(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = PiAdapter()

    def test_normalize_from_text_deltas(self) -> None:
        raw = (
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"[{\\"severity\\":\\"high\\",\\"category\\":\\"bug\\",\\"title\\":\\"X\\",\\"evidence\\":{\\"file\\":\\"a.py\\",\\"line\\":1,\\"snippet\\":\\"x\\"},\\"recommendation\\":\\"fix\\",\\"confidence\\":0.9}]"}}\n'
            '{"type":"agent_end"}\n'
        )
        ctx = NormalizeContext(task_id="t1", provider="pi", repo_root="/tmp", raw_ref="raw")
        findings = self.adapter.normalize(raw, ctx)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].provider, "pi")
        self.assertEqual(findings[0].severity, "high")

    def test_normalize_from_agent_end_fallback(self) -> None:
        raw = (
            '{"type":"agent_end","messages":['
            '{"role":"assistant","content":[{"type":"text","text":"[{\\"severity\\":\\"medium\\",\\"category\\":\\"maintainability\\",\\"title\\":\\"Style\\",\\"evidence\\":{\\"file\\":\\"b.py\\",\\"line\\":5,\\"snippet\\":\\"y\\"},\\"recommendation\\":\\"cleanup\\",\\"confidence\\":0.7}]"}]}'
            ']}'
        )
        ctx = NormalizeContext(task_id="t2", provider="pi", repo_root="/tmp", raw_ref="raw")
        findings = self.adapter.normalize(raw, ctx)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].severity, "medium")

    def test_normalize_empty(self) -> None:
        ctx = NormalizeContext(task_id="t3", provider="pi", repo_root="/tmp", raw_ref="raw")
        findings = self.adapter.normalize("", ctx)
        self.assertEqual(findings, [])

    def test_normalize_no_findings(self) -> None:
        raw = (
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"No issues found."}}\n'
            '{"type":"agent_end"}\n'
        )
        ctx = NormalizeContext(task_id="t4", provider="pi", repo_root="/tmp", raw_ref="raw")
        findings = self.adapter.normalize(raw, ctx)
        self.assertEqual(findings, [])


class TestPiAdapterDetect(unittest.TestCase):
    @patch("shutil.which", return_value="/usr/local/bin/pi")
    @patch("subprocess.run")
    def test_detect_found(self, mock_run, mock_which) -> None:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "0.80.2\n"
        adapter = PiAdapter()
        presence = adapter.detect()
        self.assertTrue(presence.detected)
        self.assertTrue(presence.auth_ok)
        self.assertEqual(presence.binary_path, "/usr/local/bin/pi")
        self.assertIn("0.80.2", presence.version or "")

    @patch("shutil.which", return_value=None)
    def test_detect_not_found(self, mock_which) -> None:
        adapter = PiAdapter()
        presence = adapter.detect()
        self.assertFalse(presence.detected)
        self.assertEqual(presence.reason, "binary_not_found")

    @patch("shutil.which", return_value="/usr/local/bin/pi")
    @patch("subprocess.run")
    def test_detect_auth_failed(self, mock_run, mock_which) -> None:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "unauthorized"
        adapter = PiAdapter()
        presence = adapter.detect()
        self.assertTrue(presence.detected)
        self.assertFalse(presence.auth_ok)
        self.assertEqual(presence.reason, "auth_check_failed")


class TestPiAdapterCapabilities(unittest.TestCase):
    def test_capability_tiers(self) -> None:
        adapter = PiAdapter()
        caps = adapter.capabilities()
        self.assertIn("C0", caps.tiers)
        self.assertIn("C1", caps.tiers)
        self.assertIn("C2", caps.tiers)
        self.assertIn("C3", caps.tiers)
        self.assertFalse(caps.supports_native_async)
        self.assertFalse(caps.supports_schema_enforcement)


if __name__ == "__main__":
    unittest.main()