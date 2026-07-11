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
from runtime.invocation_runtime import parse_invocations, run_invocation_workflow, run_invocations
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

    def supported_context_keys(self) -> list[str]:
        return ["context_files"]

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


class DebateFailureFakeAdapter(DeterministicFakeAdapter):
    def poll(self, ref: TaskRunRef) -> TaskStatus:
        if ref.task_id.startswith("debate-"):
            return TaskStatus(ref.task_id, "pi", ref.run_id, "FAILED", True, None, None, exit_code=9, message="debate failed")
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


class ContextReadingFakeAdapter(DeterministicFakeAdapter):
    def __init__(self, *, reject_context: bool = False) -> None:
        super().__init__()
        self.context_reads: list[str] = []
        self.reject_context = reject_context

    def run(self, input_task: TaskInput) -> TaskRunRef:
        context_manifest = input_task.metadata.get("context_manifest")
        if context_manifest:
            if self.reject_context:
                raise RuntimeError("context_file_unsupported")
            from runtime.acp.handlers import handle_fs_read

            allow_paths = input_task.metadata["allow_paths"]
            manifest = json.loads(handle_fs_read(
                {"path": str(context_manifest)},
                cwd=input_task.repo_root,
                allow_paths=allow_paths,
            )["content"])
            for entry in manifest["inputs"]:
                answer = handle_fs_read(
                    {"path": entry["path"]},
                    cwd=input_task.repo_root,
                    allow_paths=allow_paths,
                )["content"]
                self.context_reads.append(answer)
            input_task.metadata["context_read"] = True
        ref = super().run(input_task)
        output_path = Path(ref.artifact_path) / "raw" / "pi.stdout.log"
        if self.context_reads:
            output_path.write_text("read: " + " | ".join(self.context_reads), encoding="utf-8")
        return ref


class ContextUnsupportedFakeAdapter(DeterministicFakeAdapter):
    def supported_context_keys(self) -> list[str]:
        return []


class TeeFailureFakeAdapter(StreamingFakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.cancelled: list[str] = []

    def cancel(self, ref: TaskRunRef) -> None:
        self.cancelled.append(ref.task_id)


class BlockingRunFakeAdapter(DeterministicFakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.started = threading.Event()
        self.release = threading.Event()

    def run(self, input_task: TaskInput) -> TaskRunRef:
        self.started.set()
        self.release.wait(5)
        return super().run(input_task)


class DelayedStartFakeAdapter(DeterministicFakeAdapter):
    def __init__(self, delay_seconds: float) -> None:
        super().__init__()
        self.delay_seconds = delay_seconds

    def run(self, input_task: TaskInput) -> TaskRunRef:
        time.sleep(self.delay_seconds)
        return super().run(input_task)


class ConcurrencyFakeAdapter(DeterministicFakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self._lock = threading.Lock()
        self.active = 0
        self.max_active = 0

    def run(self, input_task: TaskInput) -> TaskRunRef:
        with self._lock:
            self.active += 1
            self.max_active = max(self.max_active, self.active)
        try:
            time.sleep(0.05)
            return super().run(input_task)
        finally:
            with self._lock:
                self.active -= 1


class PollingFakeAdapter(DeterministicFakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.poll_times: list[float] = []

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        self.poll_times.append(time.monotonic())
        if len(self.poll_times) < 3:
            return TaskStatus(ref.task_id, "pi", ref.run_id, "STARTED", False, None, None, message="running")
        return super().poll(ref)


class ProgressingFakeAdapter(DeterministicFakeAdapter):
    def __init__(self) -> None:
        super().__init__()
        self.poll_counts: dict[str, int] = {}

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        count = self.poll_counts.get(ref.run_id, 0) + 1
        self.poll_counts[ref.run_id] = count
        output_path = Path(ref.artifact_path) / "raw" / "pi.stdout.log"
        output_path.write_text("progress {}".format(count), encoding="utf-8")
        if count < 6:
            return TaskStatus(ref.task_id, "pi", ref.run_id, "STARTED", False, None, None, message="running")
        return super().poll(ref)


class UsageProtocolFakeAdapter(ProtocolFakeAdapter):
    def run(self, input_task: TaskInput) -> TaskRunRef:
        ref = super().run(input_task)
        output_path = Path(ref.artifact_path) / "raw" / "pi.stdout.log"
        output_path.write_text(
            '{"type":"message_update","assistantMessageEvent":{"type":"text_delta","delta":"official answer"}}\n'
            '{"type":"agent_end","usage":{"input_tokens":3,"output_tokens":5}}\n',
            encoding="utf-8",
        )
        return ref


class InvocationRuntimeCliTests(unittest.TestCase):
    def test_global_timeout_does_not_wait_for_blocking_adapter_start(self) -> None:
        adapter = BlockingRunFakeAdapter()
        started_at = time.monotonic()
        try:
            with tempfile.TemporaryDirectory() as repo:
                payload = run_invocations(
                    invocations=parse_invocations(["pi:model"], ["."]),
                    adapters={"pi": adapter},
                    repo_root=repo,
                    prompt="timeout",
                    timeout_seconds=10,
                    provider_permissions={},
                    allow_paths=["."],
                    global_timeout_seconds=0.05,
                )
        finally:
            adapter.release.set()

        self.assertLess(time.monotonic() - started_at, 1.0)
        self.assertEqual(payload["status"], "failed")
        self.assertEqual(payload["outputs"][0]["status"], "timeout")

    def test_global_timeout_marks_queued_invocations_as_timeouts(self) -> None:
        adapter = BlockingRunFakeAdapter()
        try:
            with tempfile.TemporaryDirectory() as repo:
                payload = run_invocations(
                    invocations=parse_invocations(["first=pi:first", "second=pi:second"], ["."]),
                    adapters={"pi": adapter},
                    repo_root=repo,
                    prompt="timeout",
                    timeout_seconds=10,
                    provider_permissions={},
                    allow_paths=["."],
                    global_timeout_seconds=0.05,
                    max_provider_parallelism=1,
                )
        finally:
            adapter.release.set()

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(
            [(item["invocation_id"], item["status"]) for item in payload["outputs"]],
            [("first", "timeout"), ("second", "timeout")],
        )

    def test_global_hard_timeout_uses_one_deadline_across_stages(self) -> None:
        adapter = DelayedStartFakeAdapter(0.15)
        started_at = time.monotonic()
        with tempfile.TemporaryDirectory() as repo:
            payload = run_invocation_workflow(
                invocations=parse_invocations(["pi:model"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="deadline",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                global_timeout_seconds=0.2,
                debate=True,
                synthesize=True,
                synthesis_provider="pi",
            )

        self.assertLess(time.monotonic() - started_at, 0.55)
        self.assertEqual(payload["status"], "partial")
        self.assertEqual(
            [(item["stage"], item["status"]) for item in payload["outputs"]],
            [("run", "success"), ("debate", "timeout"), ("synthesis", "timeout")],
        )

    def test_cli_rejects_artifact_task_id_traversal_as_task_failure(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "save", "--agent", "pi:model",
                    "--task-id", "../outside", "--json",
                ])

        self.assertEqual(exit_code, 2)
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "failed")
        self.assertIn("task_id", payload["error"]["message"])

    def test_artifact_tee_failure_cancels_active_invocation(self) -> None:
        adapter = TeeFailureFakeAdapter()
        original_open = Path.open

        def fail_answer_append(path: Path, mode: str = "r", *args: object, **kwargs: object):
            if mode == "a" and path.suffix == ".md":
                raise OSError("artifact disk full")
            return original_open(path, mode, *args, **kwargs)

        with tempfile.TemporaryDirectory() as repo, patch.object(Path, "open", new=fail_answer_append):
            payload = run_invocations(
                invocations=parse_invocations(["pi:model"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="tee",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
            )

        self.assertEqual(payload["status"], "failed")
        self.assertEqual(adapter.cancelled, ["invocation-pi-model"])

    def test_persistent_artifact_task_id_cannot_escape_artifact_base(self) -> None:
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            with self.assertRaisesRegex(ValueError, "task_id"):
                run_invocations(
                    invocations=parse_invocations(["pi:model"], ["."]),
                    adapters={"pi": DeterministicFakeAdapter()},
                    repo_root=repo,
                    prompt="save",
                    timeout_seconds=10,
                    provider_permissions={},
                    allow_paths=["."],
                    artifact_base=artifacts,
                    task_id="../outside",
                    persist_artifacts=True,
                )

    def test_reusing_persistent_task_id_clears_old_invocation_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            run_invocations(
                invocations=parse_invocations(["old=pi:model"], ["."]),
                adapters={"pi": DeterministicFakeAdapter()},
                repo_root=repo,
                prompt="first",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="reused",
                persist_artifacts=True,
            )
            run_invocations(
                invocations=parse_invocations(["new=pi:model"], ["."]),
                adapters={"pi": DeterministicFakeAdapter()},
                repo_root=repo,
                prompt="second",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="reused",
                persist_artifacts=True,
            )

            invocation_dir = Path(artifacts) / "reused" / "stages" / "run" / "invocations"
            self.assertFalse((invocation_dir / "old.md").exists())
            self.assertTrue((invocation_dir / "new.md").exists())

    def test_chain_passes_complete_markdown_context_by_manifest_path(self) -> None:
        adapter = ContextReadingFakeAdapter()
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            payload = run_invocation_workflow(
                invocations=parse_invocations(["first=pi:first", "second=pi:second"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="review this",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="chain-run",
                persist_artifacts=True,
                chain=True,
            )

            second = adapter.inputs[1]
            manifest_path = Path(str(second.metadata["context_manifest"]))
            from runtime.acp.handlers import handle_fs_read

            manifest = json.loads(handle_fs_read(
                {"path": str(manifest_path)},
                cwd=repo,
                allow_paths=second.metadata["allow_paths"],
            )["content"])
            self.assertEqual(payload["status"], "complete")
            self.assertIn("answer for first", adapter.context_reads)
            self.assertIn(str(manifest_path), second.prompt)
            self.assertNotIn("answer for first", second.prompt)
            self.assertIn(str(manifest_path), second.target_paths)
            self.assertEqual(second.metadata["context_read_only_paths"], [str(manifest_path.parent)])
            self.assertIn(str(manifest_path.parent), second.metadata["allow_paths"])
            self.assertTrue(all(Path(entry["path"]).parent == manifest_path.parent for entry in manifest["inputs"] if entry["path"]))
            self.assertEqual(manifest["inputs"][0]["stage"], "chain-00")
            self.assertEqual(manifest["inputs"][0]["invocation_id"], "first")

    def test_chain_context_unsupported_is_explicit_and_dependent_stage_fails(self) -> None:
        adapter = ContextReadingFakeAdapter(reject_context=True)
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            payload = run_invocation_workflow(
                invocations=parse_invocations(["first=pi:first", "second=pi:second"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="review this",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="chain-unsupported",
                persist_artifacts=True,
                chain=True,
            )

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["outputs"][1]["status"], "failed")
        self.assertEqual(payload["outputs"][1]["error"], "context_file_unsupported")

    def test_chain_rejects_adapter_without_context_file_capability_before_launch(self) -> None:
        adapter = ContextUnsupportedFakeAdapter()
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            payload = run_invocation_workflow(
                invocations=parse_invocations(["first=pi:first", "second=pi:second"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="review this",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="chain-unsupported-capability",
                persist_artifacts=True,
                chain=True,
            )

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(payload["outputs"][1]["error"], "context_file_unsupported")
        self.assertEqual([task.metadata["invocation_id"] for task in adapter.inputs], ["first"])

    def test_debate_and_synthesis_are_raw_file_backed_stages(self) -> None:
        adapter = ContextReadingFakeAdapter()
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            payload = run_invocation_workflow(
                invocations=parse_invocations(["first=pi:first", "second=pi:second"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="review this",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="debate-run",
                persist_artifacts=True,
                debate=True,
                synthesize=True,
                synthesis_provider="pi",
            )

            self.assertEqual(payload["status"], "complete")
            self.assertTrue(any(task.metadata.get("stage") == "debate" for task in adapter.inputs))
            self.assertTrue(any(task.metadata.get("stage") == "synthesis" for task in adapter.inputs))
            self.assertGreaterEqual(len(adapter.context_reads), 2)
            self.assertEqual(
                next(task for task in adapter.inputs if task.metadata.get("stage") == "debate").metadata["provider_permissions"],
                {"tool_profile": "read_only"},
            )
            self.assertIn("stage", payload["outputs"][-1])
            artifact_root = Path(str(payload["artifact_root"]))
            self.assertTrue((artifact_root / "stages" / "debate" / "context" / "manifest.json").is_file())
            self.assertTrue((artifact_root / "stages" / "debate" / "result.md").is_file())
            self.assertTrue((artifact_root / "stages" / "synthesis" / "result.md").is_file())

    def test_workflow_forwards_provider_runtime_policy_to_every_stage(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            payload = run_invocation_workflow(
                invocations=parse_invocations(["first=pi:first", "second=pi:second"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="review this",
                timeout_seconds=10,
                provider_permissions={},
                provider_context={"pi": {"context_files": True}},
                provider_timeouts={"pi": 7},
                max_provider_parallelism=1,
                poll_interval_seconds=0.01,
                include_token_usage=True,
                allow_paths=["."],
                debate=True,
                synthesize=True,
                synthesis_provider="pi",
            )

        self.assertEqual(payload["status"], "complete")
        self.assertTrue(adapter.inputs)
        self.assertTrue(all(task.timeout_seconds == 7 for task in adapter.inputs))
        self.assertTrue(all(task.metadata["provider_context"] == {"context_files": True} for task in adapter.inputs))

    def test_synthesis_manifest_keeps_run_and_debate_successes_and_failures(self) -> None:
        adapter = PartialFakeAdapter()
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            payload = run_invocation_workflow(
                invocations=parse_invocations(["first=pi:first", "bad=pi:bad"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="review this",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="synthesis-manifest",
                persist_artifacts=True,
                debate=True,
                synthesize=True,
                synthesis_provider="pi",
            )

            root = Path(str(payload["artifact_root"]))
            manifest = json.loads((root / "stages" / "synthesis" / "context" / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(payload["status"], "partial")
        self.assertEqual(
            [(entry["stage"], entry["invocation_id"], entry["status"]) for entry in manifest["inputs"]],
            [
                ("run", "first", "success"),
                ("run", "bad", "failed"),
                ("debate", "first", "success"),
                ("debate", "bad", "failed"),
            ],
        )
        self.assertFalse(any(entry["stage"] == "synthesis" for entry in manifest["inputs"]))

    def test_synthesis_uses_a_valid_run_answer_when_debate_fails(self) -> None:
        adapter = DebateFailureFakeAdapter()
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            payload = run_invocation_workflow(
                invocations=parse_invocations(["first=pi:first", "second=pi:second"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="review this",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="synthesis-after-debate-failure",
                persist_artifacts=True,
                debate=True,
                synthesize=True,
                synthesis_provider="pi",
            )

            root = Path(str(payload["artifact_root"]))
            manifest_path = root / "stages" / "synthesis" / "context" / "manifest.json"
            self.assertEqual(payload["status"], "partial")
            self.assertTrue(any(task.metadata.get("stage") == "synthesis" for task in adapter.inputs))
            self.assertTrue(manifest_path.is_file())
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            self.assertEqual(
                [(entry["stage"], entry["status"]) for entry in manifest["inputs"]],
                [("run", "success"), ("run", "success"), ("debate", "failed"), ("debate", "failed")],
            )

    def test_synthesis_manifest_marks_an_omitted_run_invocation_missing(self) -> None:
        def incomplete_stage(**kwargs: object) -> dict[str, object]:
            stage = str(kwargs["stage"])
            if stage == "run":
                return {
                    "outputs": [{
                        "stage": "run",
                        "invocation_id": "first",
                        "provider": "pi",
                        "model": "first",
                        "status": "success",
                        "output": "first answer",
                        "error": None,
                        "exit_code": 0,
                        "artifact_path": None,
                    }],
                }
            return {
                "outputs": [{
                    "stage": "synthesis",
                    "invocation_id": "first",
                    "provider": "pi",
                    "model": "first",
                    "status": "success",
                    "output": "synthesis answer",
                    "error": None,
                    "exit_code": 0,
                    "artifact_path": None,
                }],
            }

        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            with patch("runtime.invocation_runtime.run_invocations", side_effect=incomplete_stage):
                payload = run_invocation_workflow(
                    invocations=parse_invocations(["first=pi:first", "second=pi:second"], ["."]),
                    adapters={"pi": DeterministicFakeAdapter()},
                    repo_root=repo,
                    prompt="review this",
                    timeout_seconds=10,
                    provider_permissions={},
                    allow_paths=["."],
                    artifact_base=artifacts,
                    task_id="missing-synthesis-input",
                    persist_artifacts=True,
                    synthesize=True,
                    synthesis_provider="pi",
                )

            root = Path(str(payload["artifact_root"]))
            manifest = json.loads((root / "stages" / "synthesis" / "context" / "manifest.json").read_text(encoding="utf-8"))

        self.assertEqual(
            [(entry["invocation_id"], entry["status"]) for entry in manifest["inputs"]],
            [("first", "success"), ("second", "missing")],
        )

    def test_root_result_groups_stages_and_prioritizes_synthesis_without_rewriting_answers(self) -> None:
        adapter = PartialFakeAdapter()
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            payload = run_invocation_workflow(
                invocations=parse_invocations(["first=pi:first", "bad=pi:bad"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="review this",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="grouped-result",
                persist_artifacts=True,
                debate=True,
                synthesize=True,
                synthesis_provider="pi",
            )

            root = Path(str(payload["artifact_root"]))
            result = (root / "result.md").read_text(encoding="utf-8")
            run_answer = (root / "stages" / "run" / "invocations" / "first.md").read_text(encoding="utf-8")

        self.assertEqual(payload["status"], "partial")
        self.assertIn("## Stage: synthesis", result)
        self.assertLess(result.index("## Stage: synthesis"), result.index("## Stage: run"))
        self.assertLess(result.index("## Stage: run"), result.index("## Stage: debate"))
        run_section = result[result.index("## Stage: run"):result.index("## Stage: debate")]
        debate_section = result[result.index("## Stage: debate"):]
        self.assertLess(run_section.index("### Invocation: first"), run_section.index("### Invocation: bad"))
        self.assertLess(debate_section.index("### Invocation: first"), debate_section.index("### Invocation: bad"))
        self.assertEqual(result.count("status: failed"), 2)
        self.assertIn(run_answer, result)

    def test_reusing_persistent_workflow_task_id_clears_stale_stages(self) -> None:
        with tempfile.TemporaryDirectory() as repo, tempfile.TemporaryDirectory() as artifacts:
            adapter = ContextReadingFakeAdapter()
            run_invocation_workflow(
                invocations=parse_invocations(["pi:model"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="first",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="reused-workflow",
                persist_artifacts=True,
                debate=True,
            )
            run_invocation_workflow(
                invocations=parse_invocations(["pi:model"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="second",
                timeout_seconds=10,
                provider_permissions={},
                allow_paths=["."],
                artifact_base=artifacts,
                task_id="reused-workflow",
                persist_artifacts=True,
            )

            root = Path(artifacts) / "reused-workflow"
            self.assertFalse((root / "stages" / "debate").exists())
            self.assertTrue((root / "result.md").is_file())

    def test_cli_chain_uses_context_reading_fake_agent(self) -> None:
        adapter = ContextReadingFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "chain",
                    "--agent", "first=pi:first", "--agent", "second=pi:second", "--chain", "--json",
                ])

        self.assertEqual(exit_code, 0)
        self.assertIn("answer for first", adapter.context_reads)

    def test_review_uses_invocation_runtime_and_preserves_explicit_prompt(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "review", "--repo", repo, "--prompt", "plain review", "--providers", "pi", "--json",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(adapter.inputs[0].prompt, "plain review")
        payload = json.loads(stdout.getvalue())
        self.assertEqual(payload["status"], "complete")
        self.assertNotIn("findings", payload["outputs"][0]["output"])

    def test_review_without_prompt_uses_natural_language_default(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), patch("sys.stdin", io.StringIO("")), contextlib.redirect_stdout(stdout):
                exit_code = main(["review", "--repo", repo, "--providers", "pi", "--json"])

        self.assertEqual(exit_code, 0)
        self.assertIn("review", adapter.inputs[0].prompt.lower())
        self.assertNotIn("json", adapter.inputs[0].prompt.lower())

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
        self.assertNotIn("usage", output)

    def test_cli_passes_effective_provider_context_to_invocation_metadata(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "context", "--json",
                    "--agent", "pi:model",
                    "--provider-context-json", '{"pi":{"context_files":true}}',
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(adapter.inputs[0].metadata["provider_context"], {"context_files": True})

    def test_cli_applies_provider_timeout_to_each_invocation(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "timeout",
                    "--agent", "pi:model", "--stall-timeout", "90", "--provider-timeouts", "pi=7",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(adapter.inputs[0].timeout_seconds, 7)

    def test_cli_limits_max_provider_parallelism(self) -> None:
        adapter = ConcurrencyFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "parallel",
                    "--max-provider-parallelism", "1",
                    "--agent", "one=pi:one", "--agent", "two=pi:two", "--agent", "three=pi:three",
                ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(adapter.max_active, 1)

    def test_cli_uses_configured_poll_interval(self) -> None:
        adapter = PollingFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "poll",
                    "--poll-interval", "0.12", "--agent", "pi:model",
                ])

        self.assertEqual(exit_code, 0)
        gaps = [later - earlier for earlier, later in zip(adapter.poll_times, adapter.poll_times[1:])]
        self.assertTrue(all(gap >= 0.09 for gap in gaps), gaps)

    def test_stall_deadline_refreshes_when_output_progresses(self) -> None:
        adapter = ProgressingFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            payload = run_invocations(
                invocations=parse_invocations(["pi:model"], ["."]),
                adapters={"pi": adapter},
                repo_root=repo,
                prompt="progress",
                timeout_seconds=1,
                provider_permissions={},
                allow_paths=["."],
                poll_interval_seconds=0.3,
            )

        self.assertEqual(payload["status"], "complete")
        self.assertEqual(payload["outputs"][0]["output"], "progress 6")

    def test_usage_is_omitted_from_json_and_run_metadata_by_default(self) -> None:
        adapter = UsageProtocolFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "usage", "--json", "--result-mode", "artifact",
                    "--artifact-base", str(Path(repo) / "reports"), "--task-id", "usage-off", "--agent", "pi:model",
                ])

            payload = json.loads(stdout.getvalue())
            run_metadata = json.loads((Path(str(payload["artifact_root"])) / "run.json").read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertNotIn("usage", payload["outputs"][0])
        self.assertNotIn("usage", run_metadata["outputs"][0])

    def test_usage_is_retained_in_json_jsonl_and_run_metadata_when_requested(self) -> None:
        adapter = UsageProtocolFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "run", "--repo", repo, "--prompt", "usage", "--json", "--result-mode", "artifact",
                    "--artifact-base", str(Path(repo) / "reports"), "--task-id", "usage-on", "--include-token-usage", "--agent", "pi:model",
                ])

            payload = json.loads(stdout.getvalue())
            run_metadata = json.loads((Path(str(payload["artifact_root"])) / "run.json").read_text(encoding="utf-8"))
            stream_stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": UsageProtocolFakeAdapter()}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stream_stdout):
                stream_exit_code = main([
                    "run", "--repo", repo, "--prompt", "usage", "--stream", "jsonl",
                    "--include-token-usage", "--agent", "pi:model",
                ])

        events = [json.loads(line) for line in stream_stdout.getvalue().splitlines()]
        finished = next(event for event in events if event["type"] == "invocation_finished")
        expected_usage = {"prompt_tokens": 3, "completion_tokens": 5, "total_tokens": 8}
        self.assertEqual(exit_code, 0)
        self.assertEqual(stream_exit_code, 0)
        self.assertEqual(payload["outputs"][0]["usage"], expected_usage)
        self.assertEqual(run_metadata["outputs"][0]["usage"], expected_usage)
        self.assertEqual(finished["usage"], expected_usage)

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
        self.assertEqual(sorted(task.metadata["model"] for task in adapter.inputs), ["careful-model", "fast-model"])
        self.assertEqual(sorted(task.metadata["invocation_id"] for task in adapter.inputs), ["careful", "fast"])
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

    def test_review_perspectives_and_file_division_are_explicit_without_rewriting_answers(self) -> None:
        adapter = DeterministicFakeAdapter()
        with tempfile.TemporaryDirectory() as repo:
            for name in ("a.py", "b.py", "c.py"):
                Path(repo, name).write_text(name, encoding="utf-8")
            stdout = io.StringIO()
            with patch("runtime.cli._doctor_adapter_registry", return_value={"pi": adapter}), patch("runtime.cli.discover_models", return_value={"ok": False, "models": []}), contextlib.redirect_stdout(stdout):
                exit_code = main([
                    "review", "--repo", repo, "--prompt", "Inspect assigned files.", "--json",
                    "--agent", "first=pi:one", "--agent", "second=pi:two",
                    "--perspectives-json", '{"pi":"Focus on security boundaries."}',
                    "--divide", "files",
                ])

        self.assertEqual(exit_code, 0)
        tasks = {task.metadata["invocation_id"]: task for task in adapter.inputs}
        self.assertEqual(tasks["first"].target_paths, ["a.py", "c.py"])
        self.assertEqual(tasks["second"].target_paths, ["b.py"])
        self.assertIn("Focus on security boundaries.", tasks["first"].prompt)
        self.assertIn("Assigned files (non-overlapping):", tasks["second"].prompt)
        self.assertTrue(set(tasks["first"].target_paths).isdisjoint(tasks["second"].target_paths))
        payload = json.loads(stdout.getvalue())
        self.assertEqual([item["output"] for item in payload["outputs"]], ["answer for one", "answer for two"])


if __name__ == "__main__":
    unittest.main()
