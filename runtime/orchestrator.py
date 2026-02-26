from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

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
        state_file: Optional[str] = None,
        sleep_fn: Optional[Callable[[float], None]] = None,
    ) -> None:
        self.retry_policy = retry_policy or RetryPolicy()
        self.sleep_fn = sleep_fn or time.sleep
        # Dispatch/task idempotency caching is intentionally disabled so each invocation
        # executes against providers and returns fresh model output.
        self.dispatch_cache: Dict[str, RunResult] = {}
        self.idempotency_index: Dict[str, str] = {}
        self.sent_notifications: Set[Tuple[str, str, str]] = set()
        self.state_file = Path(state_file) if state_file else None
        self._lock = threading.RLock()
        if self.state_file:
            self._load_state()

    def _load_state(self) -> None:
        with self._lock:
            if not self.state_file:
                return
            if not self.state_file.exists():
                return
            data = json.loads(self.state_file.read_text(encoding="utf-8"))
            self.sent_notifications = {
                (item["task_id"], item["state"], item["channel"]) for item in data.get("sent_notifications", [])
            }
            # Legacy keys (idempotency_index/dispatch_cache) are ignored by design.

    def _persist_state(self) -> None:
        with self._lock:
            if not self.state_file:
                return
            if not self.state_file.parent.exists():
                self.state_file.parent.mkdir(parents=True, exist_ok=True)

            payload = {
                "sent_notifications": [
                    {"task_id": task_id, "state": state, "channel": channel}
                    for task_id, state, channel in sorted(self.sent_notifications)
                ],
            }

            tmp = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
            tmp.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
            tmp.replace(self.state_file)

    def submit(self, task_id: str, idempotency_key: str) -> Tuple[bool, str]:
        """Returns (created_new, task_id)."""
        _ = idempotency_key
        return (True, task_id)

    def run_with_retry(
        self,
        task_id: str,
        provider: str,
        dispatch_key: str,
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
                    dispatch_key=dispatch_key,
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
                    dispatch_key=dispatch_key,
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

    def send_terminal_notification(self, task_id: str, state: TaskState, channel: str) -> bool:
        with self._lock:
            key = (task_id, state.value, channel)
            if key in self.sent_notifications:
                return False
            self.sent_notifications.add(key)
            self._persist_state()
            return True

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
