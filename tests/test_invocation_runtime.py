from __future__ import annotations

import contextlib
import json
import io
import threading
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.answer_transport import AnswerTransport, decode_pi_events
from runtime.cli import main
from runtime.invocation_runtime import parse_invocations, run_invocations
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


class ProtocolFakeAdapter(DeterministicFakeAdapter):
    def run(self, input_task: TaskInput) -> TaskRunRef:
        self.inputs.append(input_task)
        root = Path(input_task.metadata["artifact_root"]) / input_task.task_id
        raw = root / "raw"
        raw.mkdir(parents=True, exist_ok=True)
        (raw / "pi.stdout.log").write_text(
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"official answer"}}\n'
            '{"type":"agent_end"}\n',
            encoding="utf-8",
        )
        (raw / "pi.stderr.log").write_text("protocol log", encoding="utf-8")
        return TaskRunRef(input_task.task_id, "pi", input_task.task_id, str(root), "2026-07-11T00:00:00Z")

    def decode_transport(self, raw: str) -> AnswerTransport:
        return decode_pi_events(raw)


class PartialFakeAdapter(DeterministicFakeAdapter):
    def poll(self, ref: TaskRunRef) -> TaskStatus:
        if ref.task_id.endswith("bad"):
            return TaskStatus(ref.task_id, "pi", ref.run_id, "FAILED", True, None, None, exit_code=9, message="child failed")
        return super().poll(ref)


class StallFakeAdapter(PartialFakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled: list[str] = []

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        if ref.task_id.endswith("stall"):
            return TaskStatus(ref.task_id, "pi", ref.run_id, "STARTED", False, None, None, message="running")
        return super().poll(ref)

    def cancel(self, ref: TaskRunRef) -> None:
        self.cancelled.append(ref.task_id)


class StreamingFakeAdapter(DeterministicFakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.poll_counts: dict[str, int] = {}
        self.first_output = threading.Event()

    def run(self, input_task: TaskInput) -> TaskRunRef:
        ref = super().run(input_task)
        output_path = Path(ref.artifact_path) / "raw" / "pi.stdout.log"
        output_path.write_text("", encoding="utf-8")
        return ref

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        count = self.poll_counts.get(ref.run_id, 0) + 1
        self.poll_counts[ref.run_id] = count
        output_path = Path(ref.artifact_path) / "raw" / "pi.stdout.log"
        if count == 1:
            output_path.write_text("first", encoding="utf-8")
            self.first_output.set()
            return TaskStatus(ref.task_id, "pi", ref.run_id, "STARTED", False, None, None, message="running")
        if count == 2:
            output_path.write_text("first answer", encoding="utf-8")
            return TaskStatus(ref.task_id, "pi", ref.run_id, "STARTED", False, None, None, message="running")
        return super().poll(ref)


class InvocationRuntimeCliTests(unittest.TestCase):
    def test_event_callback_failure_does_not_break_invocation_cleanup(self) -> None:
        adapter = DeterministicFakeAdapter()

        def broken_callback(_event: dict[str, object]) -> None:
            raise RuntimeError("renderer failed")

        with tempfile.TemporaryDirectory() as repo:
            result = run_invocations(
                invocations=parse_invocations(["pi:model"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="callback",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                event_callback=broken_callback,
            )

        self.assertEqual(result["status"], "complete")
        self.assertFalse(Path(adapter.inputs[0].metadata["artifact_root"]).exists())

    def test_persistent_artifacts_preserve_raw_answers_and_deterministic_run_record(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            with tempfile.TemporaryDirectory() as artifacts:
                payload = run_invocations(
                    invocations=parse_invocations(["fast=pi:fast-model", "careful=pi:careful-model"], ["."]),
                    adapters={"pi": adapter},
                    repo_root=repo,
                    prompt="save",
                    timeout_seconds=10,
                    provider_permissions={},
                    allow_paths=["."],
                    artifact_base=artifacts,
                    task_id="saved-run",
                    persist_artifacts=True,
                )

                artifact_root = Path(payload["artifact_root"])
                self.assertEqual(payload["artifact_root"], str(artifact_root))
                self.assertEqual((artifact_root / "stages" / "run" / "invocations" / "fast.md").read_text(encoding="utf-8"), "answer for fast-model")
                self.assertEqual((artifact_root / "stages" / "run" / "invocations" / "careful.md").read_text(encoding="utf-8"), "answer for careful-model")
                result_text = (artifact_root / "result.md").read_text(encoding="utf-8")
                self.assertLess(result_text.index("fast"), result_text.index("careful"))
                self.assertIn("answer for fast-model", result_text)
                run_json = json.loads((artifact_root / "run.json").read_text(encoding="utf-8"))
                self.assertEqual(run_json["status"], "complete")
                self.assertEqual(run_json["stage"], "run")
                self.assertNotIn("findings", run_json)

    def test_temporary_execution_cleans_context_and_returns_null_artifact_root(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            result = run_invocations(
                invocations=parse_invocations(["pi:model"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="temporary",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
            )
            artifact_base = Path(adapter.inputs[0].metadata["artifact_root"])

        self.assertIsNone(result["artifact_root"])
        self.assertFalse(artifact_base.exists())

    def test_cli_save_artifacts_returns_persistent_artifact_root(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "save", "--json",
                    "--artifact-base", str(Path(repo) / "reports"), "--task-id", "saved",
                    "--result-mode", "artifact", "--agent", "pi:model",
                ])

            payload = json.loads(stdout.getvalue())
            artifact_root = Path(payload["artifact_root"])
            self.assertEqual(exit_code, 0)
            self.assertTrue(artifact_root.is_dir())
            self.assertTrue((artifact_root / "result.md").is_file())
            self.assertTrue((artifact_root / "run.json").is_file())

    def test_output_delta_is_emitted_before_delayed_invocation_completes(self) -> None:
        adapter = StreamingFakeAdapter()
        events: list[dict[str, object]] = []
        result: list[dict[str, object]] = []
        with tempfile.TemporaryDirectory() as repo:
            worker = threading.Thread(
                target=lambda: result.append(run_invocations(
                    invocations=parse_invocations(["slow=pi:model"], ["."]),
                    adapters={"pi": adapter},
                    repo_root=repo,
                    prompt="stream",
                    timeout_seconds=10,
                    provider_permissions={},
                    allow_paths=["."],
                    event_callback=events.append,
                ))
            )
            worker.start()
            self.assertTrue(adapter.first_output.wait(1))
            for _ in range(50):
                if any(event["type"] == "output_delta" for event in events):
                    break
                time.sleep(0.01)
            self.assertEqual([event["delta"] for event in events if event["type"] == "output_delta"], ["first"])
            self.assertTrue(worker.is_alive())
            worker.join(timeout=2)

        self.assertFalse(worker.is_alive())
        self.assertEqual(result[0]["status"], "complete")

    def test_jsonl_stream_reconstructs_each_invocation_answer(self) -> None:
        adapter = StreamingFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "stream", "--stream", "jsonl",
                    "--agent", "slow=pi:model",
                ])

        events = [json.loads(line) for line in stdout.getvalue().splitlines()]
        deltas = [event["delta"] for event in events if event["type"] == "output_delta"]
        self.assertEqual(exit_code, 0)
        self.assertEqual("".join(deltas), "first answer")
        self.assertEqual(events[-1]["type"], "task_finished")

    def test_default_text_mode_streams_single_answer_without_decorations(self) -> None:
        adapter = StreamingFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "stream",
                    "--agent", "pi:model",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stdout.getvalue(), "first answer")

    def test_text_mode_keeps_failure_diagnostics_on_stderr(self) -> None:
        adapter = PartialFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            stderr = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout), contextlib.redirect_stderr(stderr):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "compare",
                    "--agent", "good=pi:good-model", "--agent", "bad=pi:bad-model",
                ])

        self.assertEqual(exit_code, 1)
        self.assertIn("answer for good-model", stdout.getvalue())
        self.assertNotIn("child failed", stdout.getvalue())
        self.assertIn("child failed", stderr.getvalue())

    def test_multi_invocation_text_mode_adds_source_heading_on_source_switch(self) -> None:
        adapter = StreamingFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "stream",
                    "--agent", "one=pi:one", "--agent", "two=pi:two",
                ])

        text = stdout.getvalue()
        self.assertEqual(exit_code, 0)
        self.assertIn("── one (pi:one) ──", text)
        self.assertIn("── two (pi:two) ──", text)
        self.assertEqual(text.count("first"), 2)
        self.assertEqual(text.count("answer"), 2)
    def test_pre_cancelled_task_does_not_start_any_invocation(self) -> None:
        adapter = DeterministicFakeAdapter()
        cancel_event = threading.Event()
        cancel_event.set()
        with tempfile.TemporaryDirectory() as repo:
            payload = run_invocations(
                invocations=parse_invocations(["one=pi:model"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="cancel",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                cancel_event=cancel_event,
            )

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["outputs"][0]["status"], "cancelled")
        self.assertEqual(adapter.inputs, [])

    def test_global_hard_timeout_cancels_remaining_invocations(self) -> None:
        adapter = StallFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            payload = run_invocations(
                invocations=parse_invocations(["stall=pi:stall", "good=pi:good"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="compare",
                timeout_seconds=900,
                provider_permissions={},
                allow_paths=["."],
                global_timeout_seconds=0.1,
            )

        self.assertEqual(payload["status"], "partial")
        stalled = next(item for item in payload["outputs"] if item["invocation_id"] == "stall")
        self.assertEqual(stalled["status"], "timeout")
        self.assertEqual(stalled["output"], "answer for stall")
        self.assertEqual(adapter.cancelled, ["invocation-stall"])

    def test_timeout_isolated_to_stalled_invocation(self) -> None:
        adapter = StallFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "compare", "--json", "--stall-timeout", "0",
                    "--agent", "stall=pi:stall", "--agent", "good=pi:good",
                ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(next(item for item in payload["outputs"] if item["invocation_id"] == "stall")["status"], "timeout")
        self.assertEqual(next(item for item in payload["outputs"] if item["invocation_id"] == "good")["status"], "success")
        self.assertEqual(adapter.cancelled, ["invocation-stall"])

    def test_no_successful_invocation_reports_failed_with_distinct_exit_code(self) -> None:
        adapter = PartialFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "compare", "--json",
                    "--agent", "bad=pi:bad-model", "--agent", "also-bad=pi:bad-model-2",
                ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 2)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["exit_code"], 2)
        self.assertTrue(all(item["status"] == "failed" for item in payload["outputs"]))

    def test_failed_invocation_isolated_and_successful_answer_is_returned(self) -> None:
        adapter = PartialFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "compare", "--json",
                    "--agent", "good=pi:good-model", "--agent", "bad=pi:bad-model",
                ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 1)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual({item["invocation_id"]: item["status"] for item in payload["outputs"]}, {"good": "success", "bad": "failed"})
        self.assertEqual(next(item for item in payload["outputs"] if item["invocation_id"] == "good")["output"], "answer for good-model")

    def test_cli_returns_decoded_protocol_answer_instead_of_event_json(self) -> None:
        adapter = ProtocolFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "compare", "--json",
                    "--agent", "pi:protocol-model",
                ])

        self.assertEqual(exit_code, 0)
        self.assertIn('"output": "official answer"', stdout.getvalue())
        self.assertNotIn("message_update", stdout.getvalue())

    def test_cli_preserves_transport_metadata_for_a_decoded_answer(self) -> None:
        adapter = ProtocolFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "compare", "--json",
                    "--agent", "pi:protocol-model",
                ])

        payload = json.loads(stdout.getvalue())
        self.assertEqual(exit_code, 0)
        output = payload["outputs"][0]
        self.assertEqual(output["deltas"], ["official answer"])
        self.assertEqual(output["transport_status"], "succeeded")
        self.assertIsNone(output["usage"])

    def test_providers_shorthand_uses_invocation_runtime_with_default_model(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "compare", "--json", "--providers", "pi",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual([task.metadata["invocation_id"] for task in adapter.inputs], ["pi-default"])
        self.assertNotIn("model", adapter.inputs[0].metadata)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["stage"], "run")
        self.assertTrue(payload["task_id"].startswith("run-"))
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["exit_code"], 0)
        self.assertIsNone(payload["artifact_root"])
        self.assertEqual(payload["outputs"][0], {
            "invocation_id": "pi-default",
            "provider": "pi",
            "model": "default",
            "status": "success",
            "output": "answer for default",
            "error": None,
            "exit_code": 0,
            "deltas": ["answer for default"],
            "transport_status": "succeeded",
            "usage": None,
            "stage": "run",
            "artifact_path": None,
        })

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
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["exit_code"], 0)
        self.assertEqual([item["invocation_id"] for item in payload["outputs"]], ["fast", "careful"])
        self.assertTrue(all(item["status"] == "success" for item in payload["outputs"]))

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
