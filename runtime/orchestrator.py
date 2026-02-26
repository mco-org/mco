from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Dict, List, Optional, Set, Tuple

from .retry import RetryPolicy
from .types import AttemptResult, ErrorKind, RunResult, TaskState, WarningKind


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
            self.idempotency_index = dict(data.get("idempotency_index", {}))
            self.sent_notifications = {
                (item["task_id"], item["state"], item["channel"]) for item in data.get("sent_notifications", [])
            }

            self.dispatch_cache = {}
            for key, value in data.get("dispatch_cache", {}).items():
                warnings = [WarningKind(w) for w in value.get("warnings", [])]
                final_error = value.get("final_error")
                self.dispatch_cache[key] = RunResult(
                    task_id=value["task_id"],
                    provider=value["provider"],
                    dispatch_key=value["dispatch_key"],
                    success=value["success"],
                    attempts=value["attempts"],
                    delays_seconds=value.get("delays_seconds", []),
                    output=value.get("output"),
                    final_error=ErrorKind(final_error) if final_error else None,
                    warnings=warnings,
                    deduped_dispatch=False,
                )

    def _persist_state(self) -> None:
        with self._lock:
            if not self.state_file:
                return
            if not self.state_file.parent.exists():
                self.state_file.parent.mkdir(parents=True, exist_ok=True)

            dispatch_cache = {}
            for key, value in self.dispatch_cache.items():
                dispatch_cache[key] = {
                    "task_id": value.task_id,
                    "provider": value.provider,
                    "dispatch_key": value.dispatch_key,
                    "success": value.success,
                    "attempts": value.attempts,
                    "delays_seconds": value.delays_seconds,
                    "output": value.output,
                    "final_error": value.final_error.value if value.final_error else None,
                    "warnings": [w.value for w in value.warnings],
                }

            payload = {
                "idempotency_index": self.idempotency_index,
                "dispatch_cache": dispatch_cache,
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
        with self._lock:
            existing = self.idempotency_index.get(idempotency_key)
            if existing:
                return (False, existing)
            self.idempotency_index[idempotency_key] = task_id
            self._persist_state()
            return (True, task_id)

    def run_with_retry(
        self,
        task_id: str,
        provider: str,
        dispatch_key: str,
        runner: Callable[[int], AttemptResult],
    ) -> RunResult:
        with self._lock:
            if dispatch_key in self.dispatch_cache:
                cached = self.dispatch_cache[dispatch_key]
                return RunResult(
                    task_id=cached.task_id,
                    provider=cached.provider,
                    dispatch_key=cached.dispatch_key,
                    success=cached.success,
                    attempts=cached.attempts,
                    delays_seconds=list(cached.delays_seconds),
                    output=cached.output,
                    final_error=cached.final_error,
                    warnings=list(cached.warnings),
                    deduped_dispatch=True,
                )

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
                with self._lock:
                    self.dispatch_cache[dispatch_key] = final
                    self._persist_state()
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
                with self._lock:
                    self.dispatch_cache[dispatch_key] = final
                    self._persist_state()
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
