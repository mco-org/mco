from __future__ import annotations

import contextlib
import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.cli import main
from runtime.contracts import CapabilitySet, ProviderPresence, TaskInput, TaskRunRef, TaskStatus


class DeterministicFakeAdapter:
    id = "pi"

    def __init__(self) -> None:
        self.inputs: list[TaskInput] = []

    def detect(self) -> ProviderPresence:
        return ProviderPresence(provider="pi", detected=True, binary_path="/bin/fake", version="1", auth_ok=True)

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet([], False, False, False, False, "1", ["macos"])

    def supported_permission_keys(self) -> list[str]:
        return ["tool_profile"]

    def supported_model_keys(self) -> list[str]:
        return ["model"]

    def run(self, input_task: TaskInput) -> TaskRunRef:
        self.inputs.append(input_task)
        root = Path(input_task.metadata["artifact_root"]) / input_task.task_id
        raw = root / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "pi.stdout.log").write_text("answer for " + input_task.metadata.get("model", "default"), encoding="utf-8")
        (raw / "pi.stderr.log").write_text("", encoding="utf-8")
        return TaskRunRef(input_task.task_id, "pi", input_task.task_id, str(root), "2026-07-11T00:00:00Z")

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        return TaskStatus(ref.task_id, "pi", ref.run_id, "SUCCEEDED", True, None, None, exit_code=0)

    def cancel(self, ref: TaskRunRef) -> None:
        raise AssertionError("successful fake invocation must not be cancelled")

    def normalize(self, raw: object, ctx: object) -> list[object]:
        raise AssertionError("invocation runtime must not parse findings")


class InvocationRuntimeCliTests(unittest.TestCase):
    def test_cli_runs_multiple_models_for_one_provider_and_returns_raw_answers(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "compare", "--json",
                    "--agent", "fast=pi:fast-model",
                    "--agent", "careful=pi:careful-model",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual([task.metadata["model"] for task in adapter.inputs], ["fast-model", "careful-model"])
        self.assertEqual([task.metadata["invocation_id"] for task in adapter.inputs], ["fast", "careful"])
        self.assertEqual([task.metadata["allow_paths"] for task in adapter.inputs], [["."], ["."]])
        self.assertEqual(stdout.getvalue().strip(), '{"status": "complete", "outputs": [{"invocation_id": "fast", "provider": "pi", "model": "fast-model", "output": "answer for fast-model"}, {"invocation_id": "careful", "provider": "pi", "model": "careful-model", "output": "answer for careful-model"}]}')

    def test_cli_rejects_duplicate_alias_before_starting_an_invocation(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "compare",
                    "--agent", "same=pi:first", "--agent", "same=pi:second",
                ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(adapter.inputs, [])

    def test_cli_rejects_scope_outside_the_repo_before_starting_an_invocation(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "compare", "--target-paths", "../outside",
                    "--agent", "pi:fast-model",
                ])

        self.assertEqual(exit_code, 2)
        self.assertEqual(adapter.inputs, [])

    def test_complete_discovery_rejects_unknown_model_before_starting(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": True, "models": [{"id": "known"}]}):
                exit_code = main(["run", "--repo", repo, "--prompt", "compare", "--agent", "pi:unknown"])

        self.assertEqual(exit_code, 2)
        self.assertEqual(adapter.inputs, [])


if __name__ == "__main__":
    unittest.main()
