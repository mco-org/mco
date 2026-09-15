from __future__ import annotations

import unittest

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


if __name__ == "__main__":
    unittest.main()
