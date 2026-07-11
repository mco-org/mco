from __future__ import annotations

import re
import tempfile
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Mapping, Optional, Sequence
from uuid import uuid4

from .contracts import ProviderAdapter, TaskInput
from .invocation_artifacts import InvocationArtifactWriter


_INVOCATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")
COMPLETE_EXIT_CODE = 0
PARTIAL_EXIT_CODE = 1
FAILED_EXIT_CODE = 2
_EVENT_CALLBACK_LOCK = threading.RLock()


def _notify(event_callback: Optional[Callable[[dict[str, object]], None]], event: dict[str, object]) -> None:
    if event_callback is None:
        return
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    try:
        with _EVENT_CALLBACK_LOCK:
            event_callback(event)
    except Exception:
        pass


@dataclass(frozen=True)
class AgentInvocation:
    invocation_id: str
    provider: str
    model: str
    declaration_order: int
    execution_scope: tuple[str, ...]


def parse_invocations(raw_agents: Sequence[str], execution_scope: Sequence[str]) -> list[AgentInvocation]:
    invocations: list[AgentInvocation] = []
    seen_ids: set[str] = set()
    seen_provider_models: set[tuple[str, str]] = set()
    for order, raw in enumerate(raw_agents):
        alias, separator, provider_model = raw.partition("=")
        if not separator:
            provider_model = alias
            alias = ""
        provider, colon, model = provider_model.partition(":")
        provider = provider.strip()
        model = model.strip()
        if not colon or not provider or not model or any(char.isspace() for char in provider_model):
            raise ValueError("invalid agent invocation '{}'; expected [alias=]provider:model".format(raw))
        invocation_id = alias.strip() or re.sub(r"[^A-Za-z0-9_-]+", "-", "{}-{}".format(provider, model))
        if not _INVOCATION_ID.fullmatch(invocation_id):
            raise ValueError("invalid invocation alias '{}'".format(invocation_id))
        if invocation_id in seen_ids:
            raise ValueError("duplicate invocation alias '{}'".format(invocation_id))
        provider_model_key = (provider, model)
        if provider_model_key in seen_provider_models and not alias.strip():
            raise ValueError("repeated {}:{} requires distinct aliases".format(provider, model))
        seen_ids.add(invocation_id)
        seen_provider_models.add(provider_model_key)
        invocations.append(AgentInvocation(invocation_id, provider, model, order, tuple(execution_scope)))
    return invocations


def default_invocations(
    providers: Sequence[str],
    execution_scope: Sequence[str],
    provider_models: Mapping[str, Mapping[str, str]],
) -> list[AgentInvocation]:
    raw_agents = []
    for provider in providers:
        model_config = provider_models.get(provider, {})
        model = model_config.get("model", "default") if isinstance(model_config, Mapping) else "default"
        raw_agents.append("{}:{}".format(provider, model or "default"))
    return parse_invocations(raw_agents, execution_scope)


def validate_execution_scope(repo_root: str, target_paths: Sequence[str], allow_paths: Sequence[str]) -> list[str]:
    root = Path(repo_root).resolve()
    allowed = [(root / path).resolve() for path in allow_paths]
    normalized: list[str] = []
    for raw_path in target_paths:
        candidate = (root / raw_path).resolve()
        try:
            relative = candidate.relative_to(root)
        except ValueError as exc:
            raise ValueError("path_outside_repo: {}".format(raw_path)) from exc
        if not any(candidate == allowed_path or allowed_path in candidate.parents for allowed_path in allowed):
            raise ValueError("target_path_outside_allow_paths: {}".format(raw_path))
        normalized.append(str(relative) or ".")
    return normalized


def _run_one_invocation(
    *,
    invocation: AgentInvocation,
    adapter: ProviderAdapter,
    artifact_base: str,
    repo_root: str,
    prompt: str,
    timeout_seconds: int,
    provider_permissions: Mapping[str, Mapping[str, str]],
    allow_paths: Sequence[str],
    cancel_event: threading.Event,
    cancel_state: Mapping[str, str],
    event_callback: Optional[Callable[[dict[str, object]], None]],
    answer_path: Optional[Path],
) -> dict[str, object]:
    task_id = "invocation-{}".format(invocation.invocation_id)
    task = TaskInput(
        task_id=task_id,
        prompt=prompt,
        repo_root=repo_root,
        target_paths=list(invocation.execution_scope),
        timeout_seconds=timeout_seconds,
        metadata={
            "artifact_root": artifact_base,
            "invocation_id": invocation.invocation_id,
            "allow_paths": list(allow_paths),
            "provider_permissions": dict(provider_permissions.get(invocation.provider, {})),
        },
    )
    if invocation.model != "default":
        task.metadata["model"] = invocation.model

    if cancel_event.is_set():
        return {
            "invocation_id": invocation.invocation_id,
            "provider": invocation.provider,
            "model": invocation.model,
            "status": cancel_state.get("reason", "cancelled"),
            "output": None,
            "error": "task stopped before invocation started",
            "exit_code": None,
        }

    try:
        run_ref = adapter.run(task)
    except Exception as exc:
        return {
            "invocation_id": invocation.invocation_id,
            "provider": invocation.provider,
            "model": invocation.model,
            "status": "failed",
            "output": None,
            "error": str(exc),
            "exit_code": None,
        }

    deadline = time.monotonic() + timeout_seconds
    emitted_answer = ""
    emitted_deltas: list[str] = []

    def completed_result(
        invocation_status: str,
        error: Optional[str],
        exit_code: Optional[int],
        output: Optional[str] = None,
        transport: Any = None,
    ) -> dict[str, object]:
        stderr_path = Path(run_ref.artifact_path) / "raw" / "{}.stderr.log".format(invocation.provider)
        try:
            stderr = stderr_path.read_text(encoding="utf-8") if stderr_path.exists() else ""
        except OSError as exc:
            stderr = "failed to read provider diagnostics: {}".format(exc)
        return {
            "invocation_id": invocation.invocation_id,
            "provider": invocation.provider,
            "model": invocation.model,
            "status": invocation_status,
            "output": output if output is not None else (emitted_answer or None),
            "error": error,
            "exit_code": exit_code,
            "deltas": [delta.text for delta in transport.deltas] if transport is not None else list(emitted_deltas),
            "transport_status": transport.status if transport is not None else ("succeeded" if invocation_status == "success" else invocation_status),
            "usage": transport.usage if transport is not None else None,
            "stderr": stderr,
            "artifact_path": str(answer_path) if answer_path is not None else None,
        }

    while True:
        if cancel_event.is_set():
            try:
                adapter.cancel(run_ref)
            except Exception:
                pass
            return completed_result(
                cancel_state.get("reason", "cancelled"),
                "task stopped while invocation was running",
                None,
            )
        try:
            status = adapter.poll(run_ref)
        except Exception as exc:
            try:
                adapter.cancel(run_ref)
            except Exception:
                pass
            return completed_result("failed", str(exc), None)
        output_path = Path(run_ref.artifact_path) / "raw" / "{}.stdout.log".format(invocation.provider)
        try:
            raw_output = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
        except OSError as exc:
            return completed_result("failed", "failed to read provider output: {}".format(exc), status.exit_code)
        try:
            decode_transport = getattr(adapter, "decode_transport", None)
            transport_snapshot = decode_transport(raw_output) if callable(decode_transport) else None
            streamed_answer = (
                "".join(delta.text for delta in transport_snapshot.deltas)
                if transport_snapshot is not None
                else raw_output
            )
        except Exception:
            transport_snapshot = None
            streamed_answer = ""
        if streamed_answer:
            delta = streamed_answer[len(emitted_answer):] if streamed_answer.startswith(emitted_answer) else streamed_answer
            if delta:
                _notify(event_callback, {
                    "type": "output_delta",
                    "stage": "run",
                    "invocation_id": invocation.invocation_id,
                    "provider": invocation.provider,
                    "model": invocation.model,
                    "delta": delta,
                })
                emitted_deltas.append(delta)
                if answer_path is not None:
                    with answer_path.open("a", encoding="utf-8") as handle:
                        handle.write(delta)
                        handle.flush()
                emitted_answer = streamed_answer
        if status.completed:
            if status.attempt_state == "SUCCEEDED":
                decode_transport = getattr(adapter, "decode_transport", None)
                try:
                    transport = decode_transport(raw_output) if callable(decode_transport) else None
                    output = transport.final_answer if transport is not None else raw_output
                except Exception as exc:
                    return completed_result("failed", "transport decode failed: {}".format(exc), status.exit_code)
                if transport is not None and transport.status == "failed":
                    return completed_result("failed", "provider transport reported failure", status.exit_code, transport=transport)
                return completed_result(
                    "success",
                    None,
                    status.exit_code if status.exit_code is not None else 0,
                    output=output,
                    transport=transport,
                )
            if status.attempt_state == "CANCELLED":
                invocation_status = "cancelled"
            else:
                invocation_status = "failed"
            return completed_result(invocation_status, status.message or status.attempt_state.lower(), status.exit_code)
        if time.monotonic() >= deadline:
            try:
                adapter.cancel(run_ref)
            except Exception:
                pass
            return completed_result("timeout", "invocation '{}' timed out".format(invocation.invocation_id), None)
        time.sleep(0.05)


def run_invocations(
    *,
    invocations: Sequence[AgentInvocation],
    adapters: Mapping[str, ProviderAdapter],
    repo_root: str,
    prompt: str,
    timeout_seconds: int,
    provider_permissions: Mapping[str, Mapping[str, str]],
    allow_paths: Sequence[str],
    artifact_base: Optional[str] = None,
    task_id: str = "",
    persist_artifacts: bool = False,
    global_timeout_seconds: Optional[float] = None,
    cancel_event: Optional[threading.Event] = None,
    event_callback: Optional[Callable[[dict[str, object]], None]] = None,
) -> dict[str, object]:
    outputs: list[Optional[dict[str, object]]] = [None] * len(invocations)
    stop_event = cancel_event or threading.Event()
    stop_state = {"reason": "cancelled"}
    resolved_task_id = task_id or "run-{}".format(uuid4().hex[:8])
    temp_directory = None
    if persist_artifacts:
        artifact_root_path = (Path(artifact_base or "reports/review").resolve() / resolved_task_id)
        artifact_root_path.mkdir(parents=True, exist_ok=True)
    else:
        temp_directory = tempfile.TemporaryDirectory(prefix="mco-invocations-")
        artifact_root_path = Path(temp_directory.name)
    provider_artifact_base = artifact_root_path / "provider-runs"
    provider_artifact_base.mkdir(parents=True, exist_ok=True)
    artifact_writer = InvocationArtifactWriter(artifact_root_path)
    answer_paths = {
        invocation.invocation_id: artifact_writer.start(invocation.invocation_id)
        for invocation in invocations
    }
    try:
        with ThreadPoolExecutor(max_workers=max(1, len(invocations))) as executor:
            for invocation in invocations:
                _notify(event_callback, {
                    "type": "invocation_started",
                    "stage": "run",
                    "invocation_id": invocation.invocation_id,
                    "provider": invocation.provider,
                    "model": invocation.model,
                })
            futures = {
                executor.submit(
                    _run_one_invocation,
                    invocation=invocation,
                    adapter=adapters[invocation.provider],
                    artifact_base=str(provider_artifact_base),
                    repo_root=repo_root,
                    prompt=prompt,
                    timeout_seconds=timeout_seconds,
                    provider_permissions=provider_permissions,
                    allow_paths=allow_paths,
                    cancel_event=stop_event,
                    cancel_state=stop_state,
                    event_callback=event_callback,
                    answer_path=answer_paths[invocation.invocation_id],
                ): index
                for index, invocation in enumerate(invocations)
            }
            pending = set(futures)
            deadline = (
                time.monotonic() + global_timeout_seconds
                if global_timeout_seconds is not None and global_timeout_seconds > 0
                else None
            )
            while pending:
                wait_timeout = 0.05
                if deadline is not None:
                    wait_timeout = min(wait_timeout, max(0.0, deadline - time.monotonic()))
                done, pending = wait(pending, timeout=wait_timeout, return_when=FIRST_COMPLETED)
                for future in done:
                    index = futures[future]
                    try:
                        result = future.result()
                    except Exception as exc:
                        invocation = invocations[index]
                        result = {
                            "invocation_id": invocation.invocation_id,
                            "provider": invocation.provider,
                            "model": invocation.model,
                            "status": "failed",
                            "output": None,
                            "error": str(exc),
                            "exit_code": None,
                            "stderr": "",
                        }
                    result.setdefault("artifact_path", str(answer_paths[invocations[index].invocation_id]))
                    outputs[index] = result
                    _notify(event_callback, {
                        "type": "invocation_finished",
                        "stage": "run",
                        "invocation_id": result["invocation_id"],
                        "provider": result["provider"],
                        "model": result["model"],
                        "status": result["status"],
                        "error": result.get("error"),
                        "exit_code": result.get("exit_code"),
                        "stderr": result.get("stderr", ""),
                    })
                if deadline is not None and pending and time.monotonic() >= deadline:
                    stop_state["reason"] = "timeout"
                    stop_event.set()
                if stop_event.is_set():
                    for future in pending:
                        future.cancel()

        resolved_outputs = [item for item in outputs if item is not None]
        for item in resolved_outputs:
            item.setdefault("stage", "run")
        successes = sum(1 for item in resolved_outputs if item["status"] == "success")
        if successes == len(resolved_outputs):
            task_status = "complete"
            exit_code = COMPLETE_EXIT_CODE
        elif successes > 0:
            task_status = "partial"
            exit_code = PARTIAL_EXIT_CODE
        else:
            task_status = "failed"
            exit_code = FAILED_EXIT_CODE
        artifact_root_value = str(artifact_root_path) if persist_artifacts else None
        if persist_artifacts:
            artifact_writer.write_run(
                task_id=resolved_task_id,
                status=task_status,
                exit_code=exit_code,
                outputs=resolved_outputs,
            )
        else:
            for item in resolved_outputs:
                item["artifact_path"] = None
        payload = {
            "stage": "run",
            "task_id": resolved_task_id,
            "status": task_status,
            "outputs": resolved_outputs,
            "exit_code": exit_code,
            "artifact_root": artifact_root_value,
        }
        _notify(event_callback, {
            "type": "task_finished",
            "stage": "run",
            "status": task_status,
            "exit_code": exit_code,
            "artifact_root": artifact_root_value,
        })
        return payload
    finally:
        if temp_directory is not None:
            temp_directory.cleanup()
