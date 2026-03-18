from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from runtime.config import ReviewPolicy
from runtime.review_engine import (
    ReviewRequest,
    _assign_division_dimensions,
    _distribute_files_round_robin,
    _discover_review_files,
    run_review,
)


class DivideAlgorithmTests(unittest.TestCase):
    def test_distribute_files_balances_large_files_first(self) -> None:
        files_with_sizes = [
            ("large.py", 100),
            ("medium.py", 50),
            ("small.py", 10),
            ("tiny.py", 1),
        ]
        assigned = _distribute_files_round_robin(["claude", "codex"], files_with_sizes)
        self.assertEqual(assigned["claude"], ["large.py", "small.py"])
        self.assertEqual(assigned["codex"], ["medium.py", "tiny.py"])

    def test_distribute_files_handles_fewer_files_than_providers(self) -> None:
        files_with_sizes = [("a.py", 10)]
        assigned = _distribute_files_round_robin(["claude", "codex", "gemini"], files_with_sizes)
        self.assertEqual(assigned["claude"], ["a.py"])
        self.assertEqual(assigned["codex"], [])
        self.assertEqual(assigned["gemini"], [])

    def test_assign_dimensions_uses_builtin_order_then_falls_back_to_full_review(self) -> None:
        assigned = _assign_division_dimensions(
            ["claude", "codex", "gemini", "qwen", "opencode", "extra"]
        )
        self.assertEqual(assigned["claude"]["dimension"], "security")
        self.assertEqual(assigned["codex"]["dimension"], "performance")
        self.assertEqual(assigned["gemini"]["dimension"], "maintainability")
        self.assertEqual(assigned["qwen"]["dimension"], "correctness")
        self.assertEqual(assigned["opencode"]["dimension"], "error-handling")
        self.assertEqual(assigned["extra"]["dimension"], "full-review")
        self.assertEqual(assigned["extra"]["perspective"], "")

    def test_assign_dimensions_with_single_provider_uses_first_dimension(self) -> None:
        assigned = _assign_division_dimensions(["claude"])
        self.assertEqual(assigned["claude"]["dimension"], "security")
        self.assertIn("security", assigned["claude"]["perspective"].lower())

    def test_discover_review_files_recurses_under_target_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "a.py").write_text("print('a')\n", encoding="utf-8")
            (root / "src" / "b.py").write_text("print('bb')\n", encoding="utf-8")
            files = _discover_review_files(tmpdir, ["src"])
            self.assertEqual(files, [("src/b.py", 12), ("src/a.py", 11)])

    def test_discover_review_files_excludes_generated_and_cache_paths(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "keep.py").write_text("print('keep')\n", encoding="utf-8")
            (root / "reports").mkdir()
            (root / "reports" / "generated.py").write_text("print('generated')\n", encoding="utf-8")
            (root / ".golutra").mkdir()
            (root / ".golutra" / "state.json").write_text("{}", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "dep.js").write_text("module.exports = 1;\n", encoding="utf-8")
            (root / "__pycache__").mkdir()
            (root / "__pycache__" / "keep.cpython-312.pyc").write_bytes(b"pyc")
            (root / "build").mkdir()
            (root / "build" / "bundle.js").write_text("console.log('bundle')\n", encoding="utf-8")
            (root / "dist").mkdir()
            (root / "dist" / "app.js").write_text("console.log('dist')\n", encoding="utf-8")
            (root / "src" / "skip.pyo").write_bytes(b"pyo")

            files = _discover_review_files(tmpdir, ["."])

            self.assertEqual(files, [("src/keep.py", 14)])


class DivideRuntimeTests(unittest.TestCase):
    def test_files_division_with_empty_directory_returns_noop_result(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "empty").mkdir()
            events: list[dict] = []
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude", "codex"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, require_non_empty_findings=False, divide="files"),
                target_paths=["empty"],
                stream_callback=events.append,
            )
            result = run_review(req, adapters={}, write_artifacts=False)
            self.assertEqual(result.decision, "PASS")
            self.assertEqual(result.division_strategy, "files")
            self.assertEqual(result.findings_count, 0)
            self.assertEqual(result.provider_results, {})
            self.assertEqual([event["type"] for event in events], ["run_started", "result"])

    def test_files_division_assigns_provider_scopes_and_target_paths(self) -> None:
        from runtime.contracts import CapabilitySet, NormalizeContext, ProviderPresence, TaskInput, TaskRunRef, TaskStatus

        captured_inputs: dict[str, TaskInput] = {}

        class _CapturingAdapter:
            def __init__(self, provider: str) -> None:
                self.id = provider

            def detect(self):
                return ProviderPresence(provider=self.id, detected=True, binary_path="/bin/true", version="1", auth_ok=True)

            def capabilities(self):
                return CapabilitySet(
                    tiers=["C0"],
                    supports_native_async=False,
                    supports_poll_endpoint=False,
                    supports_resume_after_restart=False,
                    supports_schema_enforcement=False,
                    min_supported_version="0.1",
                    tested_os=["macos"],
                )

            def run(self, task_input: TaskInput):
                captured_inputs[self.id] = task_input
                artifact_root = Path(task_input.metadata["artifact_root"]) / task_input.task_id
                raw_dir = artifact_root / "raw"
                providers_dir = artifact_root / "providers"
                raw_dir.mkdir(parents=True, exist_ok=True)
                providers_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{self.id}.stdout.log").write_text('{"findings":[]}', encoding="utf-8")
                (raw_dir / f"{self.id}.stderr.log").write_text("", encoding="utf-8")
                return TaskRunRef(task_id=task_input.task_id, provider=self.id, run_id="r1", artifact_path=str(artifact_root), started_at="now")

            def poll(self, ref):
                return TaskStatus(
                    task_id=ref.task_id,
                    provider=ref.provider,
                    run_id=ref.run_id,
                    attempt_state="SUCCEEDED",
                    completed=True,
                    heartbeat_at="now",
                    output_path=None,
                )

            def cancel(self, ref):
                pass

            def normalize(self, raw: object, ctx: NormalizeContext):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "big.py").write_text("x" * 100, encoding="utf-8")
            (root / "src" / "small.py").write_text("x" * 5, encoding="utf-8")
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude", "codex"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, require_non_empty_findings=False, divide="files"),
                target_paths=["src"],
            )
            result = run_review(req, adapters={"claude": _CapturingAdapter("claude"), "codex": _CapturingAdapter("codex")})
            self.assertEqual(result.division_strategy, "files")
            self.assertEqual(captured_inputs["claude"].target_paths, ["src/big.py"])
            self.assertEqual(captured_inputs["codex"].target_paths, ["src/small.py"])
            self.assertEqual(result.provider_results["claude"]["assigned_scope"]["mode"], "files")
            self.assertEqual(result.provider_results["codex"]["assigned_scope"]["paths"], ["src/small.py"])

    def test_dimensions_division_populates_provider_perspectives_and_scope(self) -> None:
        from runtime.contracts import CapabilitySet, NormalizeContext, ProviderPresence, TaskInput, TaskRunRef, TaskStatus

        captured_inputs: dict[str, TaskInput] = {}

        class _CapturingAdapter:
            def __init__(self, provider: str) -> None:
                self.id = provider

            def detect(self):
                return ProviderPresence(provider=self.id, detected=True, binary_path="/bin/true", version="1", auth_ok=True)

            def capabilities(self):
                return CapabilitySet(
                    tiers=["C0"],
                    supports_native_async=False,
                    supports_poll_endpoint=False,
                    supports_resume_after_restart=False,
                    supports_schema_enforcement=False,
                    min_supported_version="0.1",
                    tested_os=["macos"],
                )

            def run(self, task_input: TaskInput):
                captured_inputs[self.id] = task_input
                artifact_root = Path(task_input.metadata["artifact_root"]) / task_input.task_id
                raw_dir = artifact_root / "raw"
                providers_dir = artifact_root / "providers"
                raw_dir.mkdir(parents=True, exist_ok=True)
                providers_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{self.id}.stdout.log").write_text('{"findings":[]}', encoding="utf-8")
                (raw_dir / f"{self.id}.stderr.log").write_text("", encoding="utf-8")
                return TaskRunRef(task_id=task_input.task_id, provider=self.id, run_id="r1", artifact_path=str(artifact_root), started_at="now")

            def poll(self, ref):
                return TaskStatus(
                    task_id=ref.task_id,
                    provider=ref.provider,
                    run_id=ref.run_id,
                    attempt_state="SUCCEEDED",
                    completed=True,
                    heartbeat_at="now",
                    output_path=None,
                )

            def cancel(self, ref):
                pass

            def normalize(self, raw: object, ctx: NormalizeContext):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude", "codex", "gemini"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    require_non_empty_findings=False,
                    divide="dimensions",
                    perspectives={"claude": "Focus on security", "codex": "Focus on performance", "gemini": "Focus on maintainability"},
                ),
                target_paths=["."],
            )
            adapters = {provider: _CapturingAdapter(provider) for provider in ["claude", "codex", "gemini"]}
            result = run_review(req, adapters=adapters)
            self.assertEqual(result.division_strategy, "dimensions")
            self.assertIn("Focus on security", captured_inputs["claude"].prompt)
            self.assertIn("Focus on performance", captured_inputs["codex"].prompt)
            self.assertEqual(result.provider_results["gemini"]["assigned_scope"]["dimension"], "maintainability")

    def test_dimensions_division_with_single_provider_assigns_single_dimension(self) -> None:
        from runtime.contracts import CapabilitySet, NormalizeContext, ProviderPresence, TaskInput, TaskRunRef, TaskStatus

        captured_inputs: dict[str, TaskInput] = {}

        class _CapturingAdapter:
            def __init__(self, provider: str) -> None:
                self.id = provider

            def detect(self):
                return ProviderPresence(provider=self.id, detected=True, binary_path="/bin/true", version="1", auth_ok=True)

            def capabilities(self):
                return CapabilitySet(
                    tiers=["C0"],
                    supports_native_async=False,
                    supports_poll_endpoint=False,
                    supports_resume_after_restart=False,
                    supports_schema_enforcement=False,
                    min_supported_version="0.1",
                    tested_os=["macos"],
                )

            def run(self, task_input: TaskInput):
                captured_inputs[self.id] = task_input
                artifact_root = Path(task_input.metadata["artifact_root"]) / task_input.task_id
                raw_dir = artifact_root / "raw"
                providers_dir = artifact_root / "providers"
                raw_dir.mkdir(parents=True, exist_ok=True)
                providers_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{self.id}.stdout.log").write_text('{"findings":[]}', encoding="utf-8")
                (raw_dir / f"{self.id}.stderr.log").write_text("", encoding="utf-8")
                return TaskRunRef(task_id=task_input.task_id, provider=self.id, run_id="r1", artifact_path=str(artifact_root), started_at="now")

            def poll(self, ref):
                return TaskStatus(
                    task_id=ref.task_id,
                    provider=ref.provider,
                    run_id=ref.run_id,
                    attempt_state="SUCCEEDED",
                    completed=True,
                    heartbeat_at="now",
                    output_path=None,
                )

            def cancel(self, ref):
                pass

            def normalize(self, raw: object, ctx: NormalizeContext):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    require_non_empty_findings=False,
                    divide="dimensions",
                    perspectives={"claude": "Focus on security"},
                ),
                target_paths=["."],
            )
            result = run_review(req, adapters={"claude": _CapturingAdapter("claude")})
            self.assertEqual(result.division_strategy, "dimensions")
            self.assertIn("Focus on security", captured_inputs["claude"].prompt)
            self.assertEqual(result.provider_results["claude"]["assigned_scope"]["dimension"], "security")

    def test_dimensions_division_assigns_for_filtered_provider_order_without_perspective_misalignment(self) -> None:
        from runtime.contracts import CapabilitySet, NormalizeContext, ProviderPresence, TaskInput, TaskRunRef, TaskStatus

        captured_inputs: dict[str, TaskInput] = {}

        class _CapturingAdapter:
            def __init__(self, provider: str) -> None:
                self.id = provider

            def detect(self):
                return ProviderPresence(provider=self.id, detected=True, binary_path="/bin/true", version="1", auth_ok=True)

            def capabilities(self):
                return CapabilitySet(
                    tiers=["C0"],
                    supports_native_async=False,
                    supports_poll_endpoint=False,
                    supports_resume_after_restart=False,
                    supports_schema_enforcement=False,
                    min_supported_version="0.1",
                    tested_os=["macos"],
                )

            def run(self, task_input: TaskInput):
                captured_inputs[self.id] = task_input
                artifact_root = Path(task_input.metadata["artifact_root"]) / task_input.task_id
                raw_dir = artifact_root / "raw"
                providers_dir = artifact_root / "providers"
                raw_dir.mkdir(parents=True, exist_ok=True)
                providers_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{self.id}.stdout.log").write_text('{"findings":[]}', encoding="utf-8")
                (raw_dir / f"{self.id}.stderr.log").write_text("", encoding="utf-8")
                return TaskRunRef(task_id=task_input.task_id, provider=self.id, run_id="r1", artifact_path=str(artifact_root), started_at="now")

            def poll(self, ref):
                return TaskStatus(
                    task_id=ref.task_id,
                    provider=ref.provider,
                    run_id=ref.run_id,
                    attempt_state="SUCCEEDED",
                    completed=True,
                    heartbeat_at="now",
                    output_path=None,
                )

            def cancel(self, ref):
                pass

            def normalize(self, raw: object, ctx: NormalizeContext):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude", "codex"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    timeout_seconds=3,
                    max_retries=0,
                    require_non_empty_findings=False,
                    divide="dimensions",
                    perspectives={},
                ),
                target_paths=["."],
            )
            result = run_review(
                req,
                adapters={
                    "claude": _CapturingAdapter("claude"),
                    "codex": _CapturingAdapter("codex"),
                },
            )
            self.assertEqual(result.division_strategy, "dimensions")
            self.assertEqual(req.policy.perspectives, {})
            self.assertIn("Focus this review on security concerns", captured_inputs["claude"].prompt)
            self.assertIn("Focus this review on performance concerns", captured_inputs["codex"].prompt)

    def test_files_division_skips_unassigned_providers(self) -> None:
        from runtime.contracts import CapabilitySet, Evidence, NormalizeContext, NormalizedFinding, ProviderPresence, TaskInput, TaskRunRef, TaskStatus

        captured_inputs: dict[str, TaskInput] = {}
        run_counts: dict[str, int] = {"claude": 0, "codex": 0}
        events: list[dict] = []

        class _CapturingAdapter:
            def __init__(self, provider: str) -> None:
                self.id = provider

            def detect(self):
                return ProviderPresence(provider=self.id, detected=True, binary_path="/bin/true", version="1", auth_ok=True)

            def capabilities(self):
                return CapabilitySet(
                    tiers=["C0"],
                    supports_native_async=False,
                    supports_poll_endpoint=False,
                    supports_resume_after_restart=False,
                    supports_schema_enforcement=False,
                    min_supported_version="0.1",
                    tested_os=["macos"],
                )

            def run(self, task_input: TaskInput):
                run_counts[self.id] += 1
                captured_inputs[self.id] = task_input
                artifact_root = Path(task_input.metadata["artifact_root"]) / task_input.task_id
                raw_dir = artifact_root / "raw"
                providers_dir = artifact_root / "providers"
                raw_dir.mkdir(parents=True, exist_ok=True)
                providers_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{self.id}.stdout.log").write_text(
                    '{"findings":[{"finding_id":"F-1","severity":"medium","category":"bug","title":"Only finding","evidence":{"file":"src/only.py","line":1,"symbol":null,"snippet":"x = 1"},"recommendation":"Fix it","confidence":0.8,"fingerprint":"fp-1"}]}',
                    encoding="utf-8",
                )
                (raw_dir / f"{self.id}.stderr.log").write_text("", encoding="utf-8")
                return TaskRunRef(task_id=task_input.task_id, provider=self.id, run_id="r1", artifact_path=str(artifact_root), started_at="now")

            def poll(self, ref):
                return TaskStatus(
                    task_id=ref.task_id,
                    provider=ref.provider,
                    run_id=ref.run_id,
                    attempt_state="SUCCEEDED",
                    completed=True,
                    heartbeat_at="now",
                    output_path=None,
                )

            def cancel(self, ref):
                pass

            def normalize(self, raw: object, ctx: NormalizeContext):
                return [
                    NormalizedFinding(
                        task_id=ctx.task_id,
                        provider=self.id,
                        finding_id="F-1",
                        severity="medium",
                        category="bug",
                        title="Only finding",
                        evidence=Evidence(file="src/only.py", line=1, snippet="x = 1"),
                        recommendation="Fix it",
                        confidence=0.8,
                        fingerprint="fp-1",
                        raw_ref=ctx.raw_ref,
                    )
                ]

        with tempfile.TemporaryDirectory() as tmpdir:
            root = Path(tmpdir)
            (root / "src").mkdir()
            (root / "src" / "only.py").write_text("x = 1\n", encoding="utf-8")
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude", "codex"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, require_non_empty_findings=False, divide="files"),
                target_paths=["src"],
                stream_callback=events.append,
            )
            adapters = {"claude": _CapturingAdapter("claude"), "codex": _CapturingAdapter("codex")}

            result = run_review(req, adapters=adapters)

            self.assertEqual(run_counts["claude"], 1)
            self.assertEqual(run_counts["codex"], 0)
            self.assertNotIn("codex", captured_inputs)
            self.assertTrue(result.provider_results["codex"]["skipped"])
            self.assertEqual(result.provider_results["codex"]["reason"], "no_files_assigned")
            self.assertEqual(result.provider_results["codex"]["findings_count"], 0)
            self.assertEqual(result.terminal_state, "COMPLETED")
            self.assertEqual(result.parse_success_count, 1)
            self.assertEqual(result.parse_failure_count, 0)
            self.assertEqual(result.findings[0]["consensus_score"], 0.8)
            consensus_event = next(event for event in events if event["type"] == "consensus")
            self.assertEqual(consensus_event["provider_count"], 1)
            self.assertEqual(consensus_event["division_strategy"], "files")
            skipped_event = next(
                event
                for event in events
                if event["type"] == "provider_finished" and event["provider"] == "codex"
            )
            self.assertTrue(skipped_event["skipped"])
            self.assertEqual(skipped_event["reason"], "no_files_assigned")

    def test_dimensions_division_stream_events_include_division_strategy(self) -> None:
        from runtime.contracts import CapabilitySet, NormalizeContext, ProviderPresence, TaskInput, TaskRunRef, TaskStatus

        events: list[dict] = []

        class _CapturingAdapter:
            def __init__(self, provider: str) -> None:
                self.id = provider

            def detect(self):
                return ProviderPresence(provider=self.id, detected=True, binary_path="/bin/true", version="1", auth_ok=True)

            def capabilities(self):
                return CapabilitySet(
                    tiers=["C0"],
                    supports_native_async=False,
                    supports_poll_endpoint=False,
                    supports_resume_after_restart=False,
                    supports_schema_enforcement=False,
                    min_supported_version="0.1",
                    tested_os=["macos"],
                )

            def run(self, task_input: TaskInput):
                artifact_root = Path(task_input.metadata["artifact_root"]) / task_input.task_id
                raw_dir = artifact_root / "raw"
                providers_dir = artifact_root / "providers"
                raw_dir.mkdir(parents=True, exist_ok=True)
                providers_dir.mkdir(parents=True, exist_ok=True)
                (raw_dir / f"{self.id}.stdout.log").write_text('{"findings":[]}', encoding="utf-8")
                (raw_dir / f"{self.id}.stderr.log").write_text("", encoding="utf-8")
                return TaskRunRef(task_id=task_input.task_id, provider=self.id, run_id="r1", artifact_path=str(artifact_root), started_at="now")

            def poll(self, ref):
                return TaskStatus(
                    task_id=ref.task_id,
                    provider=ref.provider,
                    run_id=ref.run_id,
                    attempt_state="SUCCEEDED",
                    completed=True,
                    heartbeat_at="now",
                    output_path=None,
                )

            def cancel(self, ref):
                pass

            def normalize(self, raw: object, ctx: NormalizeContext):
                return []

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review",
                providers=["claude", "codex"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(timeout_seconds=3, max_retries=0, require_non_empty_findings=False, divide="dimensions"),
                target_paths=["."],
                stream_callback=events.append,
            )
            result = run_review(
                req,
                adapters={"claude": _CapturingAdapter("claude"), "codex": _CapturingAdapter("codex")},
                write_artifacts=False,
            )
            self.assertEqual(result.division_strategy, "dimensions")
            run_started = next(event for event in events if event["type"] == "run_started")
            consensus_event = next(event for event in events if event["type"] == "consensus")
            result_event = next(event for event in events if event["type"] == "result")
            self.assertEqual(run_started["division_strategy"], "dimensions")
            self.assertEqual(consensus_event["division_strategy"], "dimensions")
            self.assertEqual(result_event["division_strategy"], "dimensions")
