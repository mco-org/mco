from __future__ import annotations

import subprocess
import unittest
from unittest.mock import patch

from runtime.adapters.agy import AgyAdapter
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


class AgyAdapterTests(unittest.TestCase):
    def test_detect_rejects_an_installed_but_unauthenticated_cli(self) -> None:
        def run(command, **kwargs):
            if command[1] == "--version":
                return subprocess.CompletedProcess(command, 0, "1.2.10", "")
            self.assertEqual(command, ["agy", "models"])
            return subprocess.CompletedProcess(command, 1, "", "not logged in")

        with patch.object(AgyAdapter, "_resolve_binary", return_value="agy"), \
                patch("runtime.adapters.shim.subprocess.run", side_effect=run):
            presence = AgyAdapter().detect()
        self.assertTrue(presence.detected)
        self.assertFalse(presence.auth_ok)
        self.assertEqual(presence.reason, "auth_check_failed")

    def test_default_command_is_headless_read_only_and_sandboxed(self) -> None:
        command = AgyAdapter()._build_command(_task())
        self.assertEqual(
            command,
            [
                "agy", "--mode", "plan", "--output-format", "text",
                "--sandbox", "--print", "Review this repository.",
            ],
        )

    def test_write_mode_and_model_are_applied(self) -> None:
        command = AgyAdapter()._build_command(
            _task({"mode": "accept-edits", "sandbox": "true"}, model="gemini-2.5-pro"),
        )
        self.assertIn("accept-edits", command)
        self.assertIn("--sandbox", command)
        self.assertEqual(command[command.index("--model") + 1], "gemini-2.5-pro")

    def test_unrestricted_mode_requires_explicit_bypass(self) -> None:
        command = AgyAdapter()._build_command(
            _task({"mode": "accept-edits", "dangerously_skip_permissions": "true"}),
        )
        self.assertIn("--dangerously-skip-permissions", command)
        self.assertNotIn("--sandbox", command)

    def test_unknown_mode_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AgyAdapter()._build_command(_task({"mode": "unsafe"}))

    def test_unknown_bypass_value_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            AgyAdapter()._build_command(_task({"dangerously_skip_permissions": "yes"}))


if __name__ == "__main__":
    unittest.main()
