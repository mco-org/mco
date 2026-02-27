from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Set

from .retry import RetryPolicy
from .types import AttemptResult, ErrorKind, RunResult, TaskState


RETRYABLE_ERRORS = {
    ErrorKind.RETRYABLE_TIMEOUT,
    ErrorKind.RETRYABLE_RATE_LIMIT,
    ErrorKind.RETRYABLE_TRANSIENT_NETWORK,
}


VALID_TRANSITIONS: Dict[TaskState, Set[TaskState]] = {
    TaskState.DRAFT: {TaskState.QUEUED},
    TaskState.QUEUED: {TaskState.DISPATCHED, TaskState.CANCELLED, TaskState.EXPIRED},
    TaskState.DISPATCHED: {TaskState.RUNNING, TaskState.CANCELLED, TaskState.EXPIRED},
    TaskState.RUNNING: {
        TaskState.RETRYING,
        TaskState.AGGREGATING,
        TaskState.FAILED,
        TaskState.CANCELLED,
        TaskState.EXPIRED,
        TaskState.PARTIAL_SUCCESS,
    },
    TaskState.RETRYING: {TaskState.RUNNING, TaskState.FAILED, TaskState.EXPIRED},
    TaskState.AGGREGATING: {TaskState.COMPLETED, TaskState.PARTIAL_SUCCESS, TaskState.FAILED},
    TaskState.COMPLETED: set(),
    TaskState.PARTIAL_SUCCESS: set(),
    TaskState.FAILED: set(),
    TaskState.CANCELLED: set(),
    TaskState.EXPIRED: set(),
}


@dataclass
class TaskStateMachine:
    state: TaskState = TaskState.DRAFT

    def transition(self, next_state: TaskState) -> None:
        if next_state not in VALID_TRANSITIONS[self.state]:
            raise ValueError(f"illegal transition {self.state} -> {next_state}")
        self.state = next_state


class OrchestratorRuntime:
    def __init__(
        self,
        retry_policy: Optional[RetryPolicy] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.retry_policy = retry_policy or RetryPolicy()
        self.sleep_fn = sleep_fn or time.sleep

    def run_with_retry(
        self,
        task_id: str,
        provider: str,
        runner: Callable[[int], AttemptResult],
    ) -> RunResult:
        attempts = 0
        delays: List[float] = []
        all_warnings = []
        final_error: Optional[ErrorKind] = None
        output = None

        while True:
            attempts += 1
            result = runner(attempts)
            all_warnings.extend(result.warnings)

            if result.success:
                output = result.output
                final = RunResult(
                    task_id=task_id,
                    provider=provider,
                    success=True,
                    attempts=attempts,
                    delays_seconds=delays,
                    output=output,
                    final_error=None,
                    warnings=all_warnings,
                )
                return final

            final_error = result.error_kind or ErrorKind.NORMALIZATION_ERROR
            should_retry = final_error in RETRYABLE_ERRORS and attempts <= self.retry_policy.max_retries
            if not should_retry:
                final = RunResult(
                    task_id=task_id,
                    provider=provider,
                    success=False,
                    attempts=attempts,
                    delays_seconds=delays,
                    output=result.output,
                    final_error=final_error,
                    warnings=all_warnings,
                )
                return final

            retry_index = attempts
            delay_seconds = self.retry_policy.compute_delay(retry_index)
            delays.append(delay_seconds)
            self.sleep_fn(delay_seconds)

    def evaluate_terminal_state(self, required_provider_success: Dict[str, bool]) -> TaskState:
        if not required_provider_success:
            return TaskState.FAILED
        successes = sum(1 for ok in required_provider_success.values() if ok)
        if successes == 0:
            return TaskState.FAILED
        if successes == len(required_provider_success):
            return TaskState.COMPLETED
        return TaskState.PARTIAL_SUCCESS

    @staticmethod
    def should_expire(
        elapsed_seconds: float,
        timeout_seconds: float,
        grace_seconds: float,
        heartbeat_age_seconds: float,
        heartbeat_ttl_seconds: float,
    ) -> bool:
        if elapsed_seconds > (timeout_seconds + grace_seconds):
            return True
        if heartbeat_age_seconds > heartbeat_ttl_seconds:
            return True
        return False
