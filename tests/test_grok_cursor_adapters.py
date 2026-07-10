from __future__ import annotations

import unittest

from runtime.adapters.cursor import CursorAdapter
from runtime.adapters.grok import GrokAdapter
from runtime.contracts import TaskInput


def _task(provider_permissions=None, model="") -> TaskInput:
    metadata = {"provider_permissions": provider_permissions or {}}
    if model:
        metadata["model"] = model
    return TaskInput(
        task_id="test",
        prompt="Review this repository.",
        repo_root="/tmp",
        target_paths=["."],
        timeout_seconds=60,
        metadata=metadata,
    )


class GrokAdapterTests(unittest.TestCase):
    def test_auth_check_uses_model_catalog_without_paid_inference(self) -> None:
        self.assertEqual(GrokAdapter()._auth_check_command("grok"), ["grok", "models"])

    def test_default_command_is_headless_without_approval_bypass(self) -> None:
        command = GrokAdapter()._build_command(_task())
        self.assertEqual(command[:4], ["grok", "--no-auto-update", "-p", "Review this repository."])
        self.assertIn("plain", command)
        self.assertNotIn("--always-approve", command)

    def test_command_applies_model_and_approval_override(self) -> None:
        command = GrokAdapter()._build_command(
            _task({"approval_mode": "always-approve"}, model="grok-4.5"),
        )
        self.assertIn("--always-approve", command)
        self.assertIn("grok-4.5", command)

    def test_unknown_approval_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            GrokAdapter()._build_command(_task({"approval_mode": "unsafe"}))


class CursorAdapterTests(unittest.TestCase):
    def test_auth_check_uses_official_status_command(self) -> None:
        self.assertEqual(CursorAdapter()._auth_check_command("agent"), ["agent", "status"])

    def test_default_command_is_headless_read_only_ask_mode(self) -> None:
        command = CursorAdapter()._build_command(_task())
        self.assertEqual(command[:3], ["agent", "-p", "Review this repository."])
        self.assertIn("--mode", command)
        self.assertEqual(command[command.index("--mode") + 1], "ask")
        self.assertNotIn("--force", command)

    def test_command_applies_model_and_mode_override(self) -> None:
        command = CursorAdapter()._build_command(
            _task({"mode": "agent"}, model="gpt-5"),
        )
        self.assertNotIn("--mode", command)
        self.assertIn("gpt-5", command)

    def test_force_override_adds_official_approval_bypass_flag(self) -> None:
        command = CursorAdapter()._build_command(
            _task({"mode": "agent", "force": "true"}),
        )
        self.assertIn("--force", command)

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            CursorAdapter()._build_command(_task({"mode": "unsafe"}))


if __name__ == "__main__":
    unittest.main()
