from __future__ import annotations

import tempfile
import unittest

from runtime.orchestrator import OrchestratorRuntime, TaskStateMachine
from runtime.retry import RetryPolicy
from runtime.types import AttemptResult, ErrorKind, TaskState, WarningKind


class RetrySemanticsTests(unittest.TestCase):
    def test_retry_then_success(self) -> None:
        slept: list[float] = []
        runtime = OrchestratorRuntime(
            RetryPolicy(max_retries=2, base_delay_seconds=1.0, backoff_multiplier=2.0),
            sleep_fn=slept.append,
        )

        def runner(attempt: int) -> AttemptResult:
            if attempt == 1:
                return AttemptResult(success=False, error_kind=ErrorKind.RETRYABLE_TIMEOUT)
            return AttemptResult(success=True, output={"ok": True})

        result = runtime.run_with_retry("task-1", "claude", "dispatch-1", runner)
        self.assertTrue(result.success)
        self.assertEqual(result.attempts, 2)
        self.assertEqual(result.delays_seconds, [1.0])
        self.assertEqual(slept, [1.0])

    def test_retry_exhaustion(self) -> None:
        slept: list[float] = []
        runtime = OrchestratorRuntime(
            RetryPolicy(max_retries=2, base_delay_seconds=1.0, backoff_multiplier=2.0),
            sleep_fn=slept.append,
        )

        def runner(_attempt: int) -> AttemptResult:
            return AttemptResult(success=False, error_kind=ErrorKind.RETRYABLE_RATE_LIMIT)

        result = runtime.run_with_retry("task-2", "codex", "dispatch-2", runner)
        self.assertFalse(result.success)
        self.assertEqual(result.attempts, 3)
        self.assertEqual(result.final_error, ErrorKind.RETRYABLE_RATE_LIMIT)
        self.assertEqual(result.delays_seconds, [1.0, 2.0])
        self.assertEqual(slept, [1.0, 2.0])

    def test_non_retryable_no_retry(self) -> None:
        runtime = OrchestratorRuntime()

        def runner(_attempt: int) -> AttemptResult:
            return AttemptResult(success=False, error_kind=ErrorKind.NON_RETRYABLE_AUTH)

        result = runtime.run_with_retry("task-3", "qwen", "dispatch-3", runner)
        self.assertFalse(result.success)
        self.assertEqual(result.attempts, 1)
        self.assertEqual(result.delays_seconds, [])

    def test_dispatch_always_executes(self) -> None:
        runtime = OrchestratorRuntime()
        calls = {"n": 0}

        def runner(_attempt: int) -> AttemptResult:
            calls["n"] += 1
            return AttemptResult(success=True, output={"ok": True}, warnings=[WarningKind.PROVIDER_WARNING_MCP_STARTUP])

        first = runtime.run_with_retry("task-4", "opencode", "dispatch-4", runner)
        second = runtime.run_with_retry("task-4", "opencode", "dispatch-4", runner)
        self.assertEqual(calls["n"], 2)
        self.assertFalse(first.deduped_dispatch)
        self.assertFalse(second.deduped_dispatch)
        self.assertEqual(second.warnings, [WarningKind.PROVIDER_WARNING_MCP_STARTUP])

    def test_notification_dedupe(self) -> None:
        runtime = OrchestratorRuntime()
        sent_first = runtime.send_terminal_notification("task-5", TaskState.COMPLETED, "slack")
        sent_second = runtime.send_terminal_notification("task-5", TaskState.COMPLETED, "slack")
        self.assertTrue(sent_first)
        self.assertFalse(sent_second)

    def test_submit_always_creates_new_task(self) -> None:
        runtime = OrchestratorRuntime()
        created_a, task_a = runtime.submit("task-6", "key-1")
        created_b, task_b = runtime.submit("task-6b", "key-1")
        self.assertTrue(created_a)
        self.assertTrue(created_b)
        self.assertEqual(task_a, "task-6")
        self.assertEqual(task_b, "task-6b")

    def test_terminal_state_evaluation(self) -> None:
        runtime = OrchestratorRuntime()
        self.assertEqual(runtime.evaluate_terminal_state({"claude": True, "codex": True}), TaskState.COMPLETED)
        self.assertEqual(runtime.evaluate_terminal_state({"claude": True, "codex": False}), TaskState.PARTIAL_SUCCESS)
        self.assertEqual(runtime.evaluate_terminal_state({"claude": False, "codex": False}), TaskState.FAILED)

    def test_expire_trigger(self) -> None:
        self.assertTrue(
            OrchestratorRuntime.should_expire(
                elapsed_seconds=650,
                timeout_seconds=600,
                grace_seconds=30,
                heartbeat_age_seconds=10,
                heartbeat_ttl_seconds=60,
            )
        )
        self.assertTrue(
            OrchestratorRuntime.should_expire(
                elapsed_seconds=120,
                timeout_seconds=600,
                grace_seconds=30,
                heartbeat_age_seconds=90,
                heartbeat_ttl_seconds=60,
            )
        )


class StateMachineTests(unittest.TestCase):
    def test_valid_state_flow(self) -> None:
        sm = TaskStateMachine()
        sm.transition(TaskState.QUEUED)
        sm.transition(TaskState.DISPATCHED)
        sm.transition(TaskState.RUNNING)
        sm.transition(TaskState.AGGREGATING)
        sm.transition(TaskState.COMPLETED)
        self.assertEqual(sm.state, TaskState.COMPLETED)

    def test_illegal_transition_raises(self) -> None:
        sm = TaskStateMachine()
        with self.assertRaises(ValueError):
            sm.transition(TaskState.RUNNING)


class RestartRecoveryTests(unittest.TestCase):
    def test_submit_always_creates_new_task_after_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/runtime-state.json"
            runtime_a = OrchestratorRuntime(state_file=state_file)
            created_a, task_a = runtime_a.submit("task-r1", "idem-r1")
            self.assertTrue(created_a)
            self.assertEqual(task_a, "task-r1")

            runtime_b = OrchestratorRuntime(state_file=state_file)
            created_b, task_b = runtime_b.submit("task-r1-other", "idem-r1")
            self.assertTrue(created_b)
            self.assertEqual(task_b, "task-r1-other")

    def test_dispatch_cache_disabled_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/runtime-state.json"
            runtime_a = OrchestratorRuntime(state_file=state_file)
            calls_a = {"n": 0}

            def runner_a(_attempt: int) -> AttemptResult:
                calls_a["n"] += 1
                return AttemptResult(success=True, output={"ok": True})

            first = runtime_a.run_with_retry("task-r2", "codex", "dispatch-r2", runner_a)
            self.assertEqual(calls_a["n"], 1)
            self.assertFalse(first.deduped_dispatch)

            runtime_b = OrchestratorRuntime(state_file=state_file)
            calls_b = {"n": 0}

            def runner_b(_attempt: int) -> AttemptResult:
                calls_b["n"] += 1
                return AttemptResult(success=True, output={"ok": False})

            second = runtime_b.run_with_retry("task-r2", "codex", "dispatch-r2", runner_b)
            self.assertEqual(calls_b["n"], 1)
            self.assertFalse(second.deduped_dispatch)
            self.assertTrue(second.success)
            self.assertEqual(second.output, {"ok": False})

    def test_notification_dedupe_survives_restart(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            state_file = f"{tmpdir}/runtime-state.json"
            runtime_a = OrchestratorRuntime(state_file=state_file)
            sent_first = runtime_a.send_terminal_notification("task-r3", TaskState.PARTIAL_SUCCESS, "slack")
            self.assertTrue(sent_first)

            runtime_b = OrchestratorRuntime(state_file=state_file)
            sent_second = runtime_b.send_terminal_notification("task-r3", TaskState.PARTIAL_SUCCESS, "slack")
            self.assertFalse(sent_second)


if __name__ == "__main__":
    unittest.main()
