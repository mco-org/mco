from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.adapters.hermes import HermesAdapter
from runtime.contracts import NormalizeContext, TaskInput


class TestHermesAdapterBuildCommand(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = HermesAdapter()

    def test_build_command_safe_default(self) -> None:
        """Default command must NOT include dangerous auto-approval flags."""
        task = TaskInput(
            task_id="test-1",
            prompt="Review for bugs",
            repo_root="/tmp",
            target_paths=["."],
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("hermes", cmd)
        self.assertIn("-z", cmd)
        self.assertIn("Review for bugs", cmd)
        self.assertNotIn("--yolo", cmd)
        self.assertNotIn("--ignore-rules", cmd)
        self.assertNotIn("--accept-hooks", cmd)

    def test_build_command_yolo_opt_in(self) -> None:
        """--yolo only added when metadata['yolo'] is True."""
        task = TaskInput(
            task_id="test-2",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"yolo": True},
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("--yolo", cmd)
        self.assertNotIn("--ignore-rules", cmd)
        self.assertNotIn("--accept-hooks", cmd)

    def test_build_command_accept_hooks_opt_in(self) -> None:
        """--accept-hooks only when metadata['accept_hooks'] is True."""
        task = TaskInput(
            task_id="test-3",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"accept_hooks": True},
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("--accept-hooks", cmd)
        self.assertNotIn("--yolo", cmd)

    def test_build_command_ignore_rules_opt_in(self) -> None:
        """--ignore-rules only when metadata['ignore_rules'] is True."""
        task = TaskInput(
            task_id="test-4",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"ignore_rules": True},
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("--ignore-rules", cmd)
        self.assertNotIn("--yolo", cmd)

    def test_build_command_all_dangerous_flags_opt_in(self) -> None:
        """When all three metadata keys are True, all three flags appear."""
        task = TaskInput(
            task_id="test-5",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"yolo": True, "accept_hooks": True, "ignore_rules": True},
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("--yolo", cmd)
        self.assertIn("--accept-hooks", cmd)
        self.assertIn("--ignore-rules", cmd)

    def test_build_command_falsy_metadata_ignored(self) -> None:
        """Falsy metadata values (0, False, None) are NOT treated as opt-in."""
        for falsy in (0, False, None, "", "false"):
            task = TaskInput(
                task_id="test-falsy",
                prompt="Review",
                repo_root="/tmp",
                target_paths=["."],
                metadata={"yolo": falsy},
            )
            cmd = self.adapter._build_command(task)
            self.assertNotIn("--yolo", cmd, f"yolo={falsy!r} should not add --yolo")

    def test_build_command_with_model(self) -> None:
        task = TaskInput(
            task_id="test-6",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"model": "gpt-4"},
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("--model", cmd)
        self.assertIn("gpt-4", cmd)

    def test_build_command_with_provider(self) -> None:
        task = TaskInput(
            task_id="test-7",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"provider": "openrouter"},
        )
        cmd = self.adapter._build_command(task)
        self.assertIn("--provider", cmd)
        self.assertIn("openrouter", cmd)

    def test_build_command_ignores_empty_metadata(self) -> None:
        task = TaskInput(
            task_id="test-8",
            prompt="Review",
            repo_root="/tmp",
            target_paths=["."],
            metadata={"model": "", "provider": "  "},
        )
        cmd = self.adapter._build_command(task)
        self.assertNotIn("--model", cmd)
        self.assertNotIn("--provider", cmd)


class TestHermesAdapterIsSuccess(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = HermesAdapter()

    def test_success_with_output(self) -> None:
        self.assertTrue(
            self.adapter._is_success(0, "Some output text", "")
        )

    def test_failure_non_zero_exit(self) -> None:
        self.assertFalse(
            self.adapter._is_success(1, "Some output", "error")
        )

    def test_failure_empty_output(self) -> None:
        self.assertFalse(
            self.adapter._is_success(0, "", "")
        )

    def test_failure_whitespace_only(self) -> None:
        self.assertFalse(
            self.adapter._is_success(0, "   \n  ", "")
        )


class TestHermesAdapterDetect(unittest.TestCase):
    @patch("shutil.which", return_value="/usr/local/bin/hermes")
    @patch("subprocess.run")
    def test_detect_found(self, mock_run, mock_which) -> None:
        mock_run.return_value.returncode = 0
        mock_run.return_value.stdout = "Hermes Agent v0.17.0\n"
        adapter = HermesAdapter()
        presence = adapter.detect()
        self.assertTrue(presence.detected)
        self.assertTrue(presence.auth_ok)
        self.assertEqual(presence.binary_path, "/usr/local/bin/hermes")
        self.assertIn("0.17.0", presence.version or "")

    @patch("shutil.which", return_value=None)
    def test_detect_not_found(self, mock_which) -> None:
        adapter = HermesAdapter()
        presence = adapter.detect()
        self.assertFalse(presence.detected)
        self.assertEqual(presence.reason, "binary_not_found")

    @patch("shutil.which", return_value="/usr/local/bin/hermes")
    @patch("subprocess.run")
    def test_detect_auth_failed(self, mock_run, mock_which) -> None:
        mock_run.return_value.returncode = 1
        mock_run.return_value.stdout = ""
        mock_run.return_value.stderr = "not logged in"
        adapter = HermesAdapter()
        presence = adapter.detect()
        self.assertTrue(presence.detected)
        self.assertFalse(presence.auth_ok)
        self.assertEqual(presence.reason, "auth_check_failed")


class TestHermesAdapterNormalize(unittest.TestCase):
    def setUp(self) -> None:
        self.adapter = HermesAdapter()

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
        ctx = NormalizeContext(task_id="t1", provider="hermes", repo_root="/tmp", raw_ref="raw")
        findings = self.adapter.normalize(raw, ctx)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0].provider, "hermes")
        self.assertEqual(findings[0].severity, "high")

    def test_normalize_empty(self) -> None:
        ctx = NormalizeContext(task_id="t1", provider="hermes", repo_root="/tmp", raw_ref="raw")
        findings = self.adapter.normalize("", ctx)
        self.assertEqual(findings, [])

    def test_normalize_invalid_json(self) -> None:
        ctx = NormalizeContext(task_id="t1", provider="hermes", repo_root="/tmp", raw_ref="raw")
        findings = self.adapter.normalize("This is just some text", ctx)
        self.assertEqual(findings, [])


class TestHermesAdapterCapabilities(unittest.TestCase):
    def test_capability_tiers(self) -> None:
        adapter = HermesAdapter()
        caps = adapter.capabilities()
        self.assertIn("C0", caps.tiers)
        self.assertIn("C1", caps.tiers)
        self.assertIn("C2", caps.tiers)
        self.assertFalse(caps.supports_native_async)
        self.assertFalse(caps.supports_schema_enforcement)


if __name__ == "__main__":
    unittest.main()