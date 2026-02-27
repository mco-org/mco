from __future__ import annotations

import hashlib
import json
import tempfile
import time
import unittest
from dataclasses import dataclass
from pathlib import Path

from runtime.adapters.parsing import normalize_findings_from_text
from runtime.config import ReviewPolicy
from runtime.contracts import CapabilitySet, NormalizeContext, ProviderPresence, TaskInput, TaskRunRef, TaskStatus
from runtime.review_engine import ReviewRequest, run_review


@dataclass
class _RunState:
    task_id: str
    artifact_root: str
    provider: str


class FakeAdapter:
    def __init__(self, provider: str, raw_stdout: str) -> None:
        self.id = provider
        self._raw_stdout = raw_stdout
        self.runs = 0
        self._run_state: _RunState | None = None

    def detect(self) -> ProviderPresence:
        return ProviderPresence(provider=self.id, detected=True, binary_path="/bin/fake", version="1.0", auth_ok=True)

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            tiers=["C0", "C1", "C2"],
            supports_native_async=False,
            supports_poll_endpoint=False,
            supports_resume_after_restart=False,
            supports_schema_enforcement=False,
            min_supported_version="1.0",
            tested_os=["macos"],
        )

    def run(self, input_task: TaskInput) -> TaskRunRef:
        self.runs += 1
        artifact_root = Path(input_task.metadata["artifact_root"]) / input_task.task_id
        raw_dir = artifact_root / "raw"
        providers_dir = artifact_root / "providers"
        raw_dir.mkdir(parents=True, exist_ok=True)
        providers_dir.mkdir(parents=True, exist_ok=True)

        (raw_dir / f"{self.id}.stdout.log").write_text(self._raw_stdout, encoding="utf-8")
        (raw_dir / f"{self.id}.stderr.log").write_text("", encoding="utf-8")
        (providers_dir / f"{self.id}.json").write_text(json.dumps({"provider": self.id, "ok": True}), encoding="utf-8")
        self._run_state = _RunState(task_id=input_task.task_id, artifact_root=str(artifact_root), provider=self.id)
        return TaskRunRef(
            task_id=input_task.task_id,
            provider=self.id,  # type: ignore[arg-type]
            run_id=f"{self.id}-run-1",
            artifact_path=str(artifact_root),
            started_at="2026-02-26T00:00:00Z",
            pid=1234,
        )

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        return TaskStatus(
            task_id=ref.task_id,
            provider=ref.provider,
            run_id=ref.run_id,
            attempt_state="SUCCEEDED",
            completed=True,
            heartbeat_at="2026-02-26T00:00:01Z",
            output_path=f"{ref.artifact_path}/providers/{self.id}.json",
            error_kind=None,
            exit_code=0,
            message="completed",
        )

    def cancel(self, ref: TaskRunRef) -> None:
        _ = ref

    def normalize(self, raw: object, ctx: NormalizeContext):
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, self.id)  # type: ignore[arg-type]


class TimedFakeAdapter(FakeAdapter):
    def __init__(self, provider: str, raw_stdout: str, complete_after_seconds: float) -> None:
        super().__init__(provider, raw_stdout)
        self.complete_after_seconds = complete_after_seconds
        self.run_started_at = 0.0
        self.cancel_calls = 0

    def run(self, input_task: TaskInput) -> TaskRunRef:
        ref = super().run(input_task)
        self.run_started_at = time.time()
        return ref

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        if (time.time() - self.run_started_at) < self.complete_after_seconds:
            return TaskStatus(
                task_id=ref.task_id,
                provider=ref.provider,
                run_id=ref.run_id,
                attempt_state="STARTED",
                completed=False,
                heartbeat_at="2026-02-26T00:00:00Z",
                output_path=f"{ref.artifact_path}/providers/{self.id}.json",
                error_kind=None,
                exit_code=None,
                message="running",
            )
        return super().poll(ref)

    def cancel(self, ref: TaskRunRef) -> None:
        _ = ref
        self.cancel_calls += 1


class ProgressTimedFakeAdapter(TimedFakeAdapter):
    def __init__(
        self,
        provider: str,
        raw_stdout: str,
        complete_after_seconds: float,
        progress_chunk: str = ".",
    ) -> None:
        super().__init__(provider, raw_stdout, complete_after_seconds)
        self.progress_chunk = progress_chunk

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        status = super().poll(ref)
        if not status.completed:
            stdout_path = Path(ref.artifact_path) / "raw" / f"{self.id}.stdout.log"
            stdout_path.parent.mkdir(parents=True, exist_ok=True)
            with stdout_path.open("a", encoding="utf-8") as fh:
                fh.write(self.progress_chunk)
        return status


class PermissionAwareFakeAdapter(FakeAdapter):
    def __init__(self, provider: str, raw_stdout: str, supported_keys: list[str]) -> None:
        super().__init__(provider, raw_stdout)
        self._supported_keys = supported_keys
        self.last_provider_permissions = None

    def supported_permission_keys(self) -> list[str]:
        return list(self._supported_keys)

    def run(self, input_task: TaskInput) -> TaskRunRef:
        self.last_provider_permissions = input_task.metadata.get("provider_permissions")
        return super().run(input_task)


class ReviewEngineTests(unittest.TestCase):
    def test_review_with_findings_pass(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter(
                "claude",
                '{"findings":[{"finding_id":"f1","severity":"high","category":"bug","title":"Bug","evidence":{"file":"a.py","line":1,"snippet":"x"},"recommendation":"fix","confidence":0.8,"fingerprint":"fp"}]}',
            )
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, high_escalation_threshold=2, require_non_empty_findings=True),
            )
            result = run_review(req, adapters={"claude": adapter})
            self.assertEqual(result.decision, "PASS")
            self.assertEqual(result.findings_count, 1)
            self.assertEqual(result.parse_success_count, 1)

    def test_review_no_findings_is_inconclusive_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter("claude", '{"findings":[]}')
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    require_non_empty_findings=True,
                    enforce_findings_contract=True,
                ),
            )
            result = run_review(req, adapters={"claude": adapter})
            self.assertEqual(result.decision, "INCONCLUSIVE")
            self.assertEqual(result.findings_count, 0)
            self.assertEqual(result.parse_success_count, 1)

    def test_plain_text_output_fails_structured_parse_in_strict_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter("claude", "the word findings appears here but not as structured json")
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    require_non_empty_findings=True,
                    enforce_findings_contract=True,
                ),
            )
            result = run_review(req, adapters={"claude": adapter})
            self.assertEqual(result.decision, "INCONCLUSIVE")
            self.assertEqual(result.parse_success_count, 0)
            self.assertEqual(result.parse_failure_count, 1)

    def test_plain_text_output_is_allowed_without_strict_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter("claude", "plain text output without structured findings payload")
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    require_non_empty_findings=True,
                    enforce_findings_contract=False,
                ),
            )
            result = run_review(req, adapters={"claude": adapter})
            self.assertEqual(result.decision, "PASS")
            self.assertEqual(result.terminal_state, "COMPLETED")
            self.assertEqual(result.parse_success_count, 0)
            self.assertEqual(result.parse_failure_count, 1)

    def test_repeat_submission_executes_each_time(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter(
                "claude",
                '{"findings":[{"finding_id":"f1","severity":"low","category":"maintainability","title":"n","evidence":{"file":"a.py","line":1,"snippet":"x"},"recommendation":"fix","confidence":0.3,"fingerprint":"fp"}]}',
            )
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, require_non_empty_findings=True),
                task_id="task-repeat",
            )
            first = run_review(req, adapters={"claude": adapter})
            second = run_review(req, adapters={"claude": adapter})
            self.assertEqual(adapter.runs, 2)

    def test_run_and_review_each_execute_once(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter("claude", '{"findings":[]}')
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="same-prompt",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, require_non_empty_findings=False),
            )
            review_result = run_review(req, adapters={"claude": adapter}, review_mode=True)
            run_result = run_review(req, adapters={"claude": adapter}, review_mode=False)
            self.assertEqual(review_result.task_id, run_result.task_id)
            self.assertEqual(adapter.runs, 2)

    def test_each_run_executes_without_dispatch_cache_reuse(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter("claude", "raw output")
            req_a = ReviewRequest(
                repo_root=tmpdir,
                prompt="same-prompt",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                task_id="task-fixed-dispatch",
                target_paths=["runtime"],
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    require_non_empty_findings=False,
                    allow_paths=["."],
                ),
            )
            req_b = ReviewRequest(
                repo_root=tmpdir,
                prompt="same-prompt",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                task_id="task-fixed-dispatch",
                target_paths=["runtime"],
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    require_non_empty_findings=False,
                    allow_paths=["runtime"],
                ),
            )
            first = run_review(req_a, adapters={"claude": adapter}, review_mode=False)
            second = run_review(req_b, adapters={"claude": adapter}, review_mode=False)
            self.assertEqual(adapter.runs, 2)
            self.assertEqual(first.provider_results["claude"].get("success"), True)
            self.assertEqual(second.provider_results["claude"].get("success"), True)

    def test_run_mode_provider_result_includes_full_output(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            raw = "line-1\nline-2\nline-3"
            adapter = FakeAdapter("qwen", raw)
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="summarize",
                providers=["qwen"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, require_non_empty_findings=False),
            )
            result = run_review(req, adapters={"qwen": adapter}, review_mode=False)
            details = result.provider_results["qwen"]
            self.assertEqual(details.get("output_text"), raw)

    def test_wait_all_keeps_fast_provider_when_other_times_out(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fast = FakeAdapter(
                "claude",
                '{"findings":[{"finding_id":"f1","severity":"low","category":"maintainability","title":"ok","evidence":{"file":"a.py","line":1,"snippet":"x"},"recommendation":"fix","confidence":0.6,"fingerprint":"fp1"}]}',
            )
            slow = TimedFakeAdapter(
                "codex",
                '{"findings":[{"finding_id":"f2","severity":"low","category":"maintainability","title":"slow","evidence":{"file":"b.py","line":2,"snippet":"y"},"recommendation":"fix","confidence":0.6,"fingerprint":"fp2"}]}',
                complete_after_seconds=5.0,
            )
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude", "codex"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=1,
                    stall_timeout_seconds=1,
                    max_retries=0,
                    require_non_empty_findings=True,
                    max_provider_parallelism=2,
                    provider_timeouts={},
                ),
            )
            result = run_review(req, adapters={"claude": fast, "codex": slow})
            self.assertEqual(result.terminal_state, "PARTIAL_SUCCESS")
            self.assertEqual(result.parse_success_count, 1)
            self.assertEqual(result.parse_failure_count, 1)
            self.assertEqual(result.decision, "PARTIAL")
            self.assertGreaterEqual(slow.cancel_calls, 1)

    def test_progress_output_prevents_stall_timeout_in_run_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            progressive = ProgressTimedFakeAdapter(
                "claude",
                "raw output",
                complete_after_seconds=2.0,
            )
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="run",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=1,
                    stall_timeout_seconds=1,
                    poll_interval_seconds=0.1,
                    max_retries=0,
                    require_non_empty_findings=False,
                ),
            )
            result = run_review(req, adapters={"claude": progressive}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")
            provider_result = result.provider_results["claude"]
            self.assertEqual(provider_result.get("cancel_reason"), "")

    def test_review_hard_timeout_cancels_even_with_progress(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            progressive = ProgressTimedFakeAdapter(
                "claude",
                '{"findings":[]}',
                complete_after_seconds=5.0,
            )
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=1,
                    stall_timeout_seconds=10,
                    review_hard_timeout_seconds=1,
                    poll_interval_seconds=0.1,
                    max_retries=0,
                    require_non_empty_findings=True,
                ),
            )
            result = run_review(req, adapters={"claude": progressive}, review_mode=True)
            self.assertEqual(result.terminal_state, "FAILED")
            provider_result = result.provider_results["claude"]
            self.assertEqual(provider_result.get("final_error"), "retryable_timeout")
            self.assertEqual(provider_result.get("cancel_reason"), "hard_deadline_exceeded")
            self.assertGreaterEqual(progressive.cancel_calls, 1)

    def test_provider_timeout_override_allows_slow_provider_to_succeed(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            fast = FakeAdapter(
                "claude",
                '{"findings":[{"finding_id":"f1","severity":"low","category":"maintainability","title":"ok","evidence":{"file":"a.py","line":1,"snippet":"x"},"recommendation":"fix","confidence":0.6,"fingerprint":"fp1"}]}',
            )
            slow = TimedFakeAdapter(
                "codex",
                '{"findings":[{"finding_id":"f2","severity":"low","category":"maintainability","title":"slow","evidence":{"file":"b.py","line":2,"snippet":"y"},"recommendation":"fix","confidence":0.6,"fingerprint":"fp2"}]}',
                complete_after_seconds=1.2,
            )
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude", "codex"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=1,
                    max_retries=0,
                    require_non_empty_findings=True,
                    max_provider_parallelism=2,
                    provider_timeouts={"claude": 1, "codex": 2},
                ),
            )
            result = run_review(req, adapters={"claude": fast, "codex": slow})
            self.assertEqual(result.terminal_state, "COMPLETED")
            self.assertEqual(result.parse_success_count, 2)
            self.assertEqual(result.parse_failure_count, 0)

    def test_parallel_run_json_provider_order_is_sorted(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            codex = TimedFakeAdapter(
                "codex",
                '{"findings":[{"finding_id":"f2","severity":"low","category":"maintainability","title":"codex","evidence":{"file":"b.py","line":2,"snippet":"y"},"recommendation":"fix","confidence":0.6,"fingerprint":"fp2"}]}',
                complete_after_seconds=0.6,
            )
            claude = FakeAdapter(
                "claude",
                '{"findings":[{"finding_id":"f1","severity":"low","category":"maintainability","title":"claude","evidence":{"file":"a.py","line":1,"snippet":"x"},"recommendation":"fix","confidence":0.6,"fingerprint":"fp1"}]}',
            )
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["codex", "claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, require_non_empty_findings=True, max_provider_parallelism=2),
            )
            result = run_review(req, adapters={"codex": codex, "claude": claude})
            run_payload = json.loads(Path(result.artifact_root, "run.json").read_text(encoding="utf-8"))
            keys = list(run_payload["provider_results"].keys())
            self.assertEqual(keys, sorted(keys))
            self.assertEqual(run_payload["effective_cwd"], str(Path(tmpdir).resolve()))
            expected_allow_hash = hashlib.sha256(
                json.dumps(run_payload["allow_paths"], ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode(
                    "utf-8"
                )
            ).hexdigest()
            self.assertEqual(run_payload["allow_paths_hash"], expected_allow_hash)
            expected_permissions_hash = hashlib.sha256(
                json.dumps(
                    run_payload["provider_permissions"], ensure_ascii=True, sort_keys=True, separators=(",", ":")
                ).encode("utf-8")
            ).hexdigest()
            self.assertEqual(run_payload["permissions_hash"], expected_permissions_hash)

    def test_run_mode_accepts_plain_text_without_review_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter("claude", "plain text without findings schema")
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="run task",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, require_non_empty_findings=True),
            )
            result = run_review(req, adapters={"claude": adapter}, review_mode=False)
            self.assertEqual(result.decision, "PASS")
            self.assertEqual(result.terminal_state, "COMPLETED")
            self.assertEqual(result.parse_success_count, 0)
            self.assertEqual(result.parse_failure_count, 0)

    def test_allow_paths_rejects_target_escape(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter("claude", '{"findings":[]}')
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    require_non_empty_findings=True,
                    allow_paths=["."],
                ),
                target_paths=["../outside"],
            )
            with self.assertRaises(ValueError):
                run_review(req, adapters={"claude": adapter}, review_mode=False)

    def test_strict_permission_enforcement_blocks_unsupported_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter("gemini", "raw output")
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="run task",
                providers=["gemini"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    enforcement_mode="strict",
                    provider_permissions={"gemini": {"sandbox": "workspace-write"}},
                ),
            )
            result = run_review(req, adapters={"gemini": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "FAILED")
            provider_result = result.provider_results["gemini"]
            self.assertEqual(provider_result.get("reason"), "permission_enforcement_failed")

    def test_best_effort_drops_unsupported_permission_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = PermissionAwareFakeAdapter("gemini", "raw output", supported_keys=[])
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="run task",
                providers=["gemini"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    enforcement_mode="best_effort",
                    provider_permissions={"gemini": {"sandbox": "workspace-write"}},
                ),
            )
            result = run_review(req, adapters={"gemini": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")
            self.assertEqual(adapter.last_provider_permissions, {})

    def test_supported_provider_permission_is_applied(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = PermissionAwareFakeAdapter("codex", "raw output", supported_keys=["sandbox"])
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="run task",
                providers=["codex"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    enforcement_mode="strict",
                    provider_permissions={"codex": {"sandbox": "read-only"}},
                ),
            )
            result = run_review(req, adapters={"codex": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")
            self.assertEqual(adapter.last_provider_permissions, {"sandbox": "read-only"})

    def test_stdout_mode_skips_user_artifact_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = FakeAdapter("claude", '{"findings":[]}')
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude"],  # type: ignore[list-item]
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    enforce_findings_contract=False,
                    require_non_empty_findings=True,
                ),
            )
            result = run_review(req, adapters={"claude": adapter}, review_mode=True, write_artifacts=False)
            self.assertIsNone(result.artifact_root)
            self.assertFalse(Path(tmpdir, "artifacts").exists())


if __name__ == "__main__":
    unittest.main()
