from __future__ import annotations

import tempfile
import time
import unittest
from unittest.mock import patch

from runtime.adapters.copilot import CopilotAdapter
from runtime.contracts import NormalizeContext, TaskInput


class TestCopilotAdapterBuildCommand(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CopilotAdapter()

    def test_build_command_one_shot_autonomous_flags(self) -> None:
        """One-shot run must be non-interactive and never block on prompts."""
        task = TaskInput(
            task_id="test-1",
            prompt="Review for bugs",
            repo_root="/tmp",
            target_paths=["."],
        )
        cmd = self.adapter._build_command(task)
        self.assertEqual(cmd[0], "copilot")
        self.assertIn("-p", cmd)
        self.assertEqual(cmd[cmd.index("-p") + 1], "Review for bugs")
        self.assertIn("-s", cmd)
        self.assertIn("--allow-all-tools", cmd)
        self.assertIn("--no-ask-user", cmd)
        self.assertNotIn("--model", cmd)

    def test_build_command_with_model(self) -> None:
        task = TaskInput(
            task_id="test-2",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"model": "claude-sonnet-4.5"},
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("--model", cmd)
        self.assertEqual(cmd[cmd.index("--model") + 1], "claude-sonnet-4.5")

    def test_build_command_ignores_empty_model(self) -> None:
        task = TaskInput(
            task_id="test-3",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"model": "   "},
        )
        cmd = self.adapter._build_command(task)
        self.assertNotIn("--model", cmd)

    def test_supported_model_keys(self) -> None:
        self.assertEqual(self.adapter.supported_model_keys(), ["model"])

    def test_build_command_for_record_is_redacted(self) -> None:
        record = self.adapter._build_command_for_record()
        self.assertIn("<prompt>", record)
        self.assertIn("--allow-all-tools", record)
        self.assertIn("--no-ask-user", record)


class TestCopilotAdapterIsSuccess(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CopilotAdapter()

    def test_success_with_output(self) -> None:
        self.assertTrue(self.adapter._is_success(0, "Some final answer", ""))

    def test_failure_non_zero_exit(self) -> None:
        self.assertFalse(self.adapter._is_success(1, "Some output", "error"))

    def test_failure_empty_output(self) -> None:
        self.assertFalse(self.adapter._is_success(0, "", ""))

    def test_failure_whitespace_only(self) -> None:
        self.assertFalse(self.adapter._is_success(0, "   \n  ", ""))


class TestCopilotAdapterDetect(unittest.TestCase):
    @patch("shutil.which", return_value="/usr/local/bin/copilot")
    @patch("subprocess.run")
    def test_detect_found(self, mock_run, mock_which) -> None:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "OK\n"
        mock_run.return_value.stderr = ""
        adapter = CopilotAdapter()
        presence = adapter.detect()
        self.assertTrue(presence.detected)
        self.assertTrue(presence.auth_ok)
        self.assertEqual(presence.binary_path, "/usr/local/bin/copilot")

    @patch("shutil.which", return_value=None)
    def test_detect_not_found(self, mock_which) -> None:
        adapter = CopilotAdapter()
        presence = adapter.detect()
        self.assertFalse(presence.detected)
        self.assertEqual(presence.reason, "binary_not_found")

    @patch("shutil.which", return_value="/usr/local/bin/copilot")
    @patch("subprocess.run")
    def test_detect_auth_failed(self, mock_run, mock_which) -> None:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "not logged in"
        adapter = CopilotAdapter()
        presence = adapter.detect()
        self.assertTrue(presence.detected)
        self.assertFalse(presence.auth_ok)
        self.assertEqual(presence.reason, "auth_check_failed")


class TestCopilotAdapterNormalize(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = CopilotAdapter()

    def test_normalize_valid_json(self) -> None:
        raw = '''
        [
            {
                "severity": "high",
                "category": "bug",
                "title": "Null pointer",
                "evidence": {"file": "a.py", "line": 10, "snippet": "x.foo()"},
                "recommendation": "Add null check",
                "confidence": 0.9
            }
        ]
        '''
        ctx = NormalizeContext(task_id="t1", provider="copilot", repo_root="/tmp", raw_ref="raw")
        findings = self.adapter.normalize(raw, ctx)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].provider, "copilot")
        self.assertEqual(findings[0].severity, "high")

    def test_normalize_empty(self) -> None:
        ctx = NormalizeContext(task_id="t1", provider="copilot", repo_root="/tmp", raw_ref="raw")
        self.assertEqual(self.adapter.normalize("", ctx), [])

    def test_normalize_invalid_json(self) -> None:
        ctx = NormalizeContext(task_id="t1", provider="copilot", repo_root="/tmp", raw_ref="raw")
        self.assertEqual(self.adapter.normalize("This is just some text", ctx), [])


class TestCopilotAdapterCapabilities(unittest.TestCase):
    def test_capability_tiers(self) -> None:
        caps = CopilotAdapter().capabilities()
        self.assertIn("C0", caps.tiers)
        self.assertIn("C1", caps.tiers)
        self.assertIn("C2", caps.tiers)
        self.assertTrue(caps.supports_resume_after_restart)
        self.assertFalse(caps.supports_schema_enforcement)


class TestCopilotAdapterRunPollNormalize(unittest.TestCase):
    def _wait_terminal(self, adapter: object, ref: object, timeout_seconds: float = 5.0) -> object:
        start = time.time()
        while time.time() - start < timeout_seconds:
            status = adapter.poll(ref)  # type: ignore[attr-defined]
            if status.completed:
                return status
            time.sleep(0.05)
        self.fail("adapter run did not reach terminal state")

    def test_run_poll_normalize(self) -> None:
        adapter = CopilotAdapter()
        with tempfile.TemporaryDirectory() as tmpdir:
            task = TaskInput(
                task_id="task-copilot-contract",
                prompt="ignored in contract test",
                repo_root=tmpdir,
                target_paths=["."],
                metadata={
                    "artifact_root": tmpdir,
                    "command_override": [
                        "python3",
                        "-c",
                        'print(\'{"findings":[{"finding_id":"c1","severity":"high","category":"security","title":"c","evidence":{"file":"c.py","line":4,"snippet":"w"},"recommendation":"rc","confidence":0.9,"fingerprint":"cfp"}]}\')',
                    ],
                },
            )
            ref = adapter.run(task)
            status = self._wait_terminal(adapter, ref)
            self.assertEqual(status.attempt_state, "SUCCEEDED")
            with open(f"{tmpdir}/{task.task_id}/raw/copilot.stdout.log", "r", encoding="utf-8") as fh:
                raw = fh.read()
            findings = adapter.normalize(
                raw,
                NormalizeContext(task_id=task.task_id, provider="copilot", repo_root=tmpdir, raw_ref="raw/copilot.stdout.log"),
            )
            self.assertEqual(len(findings), 1)
            self.assertEqual(findings[0].provider, "copilot")


if __name__ == "__main__":
    unittest.main()
