from __future__ import annotations

import re
import tempfile
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Sequence

from .contracts import ProviderAdapter, TaskInput


_INVOCATION_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]*$")


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


def run_invocations(
    *,
    invocations: Sequence[AgentInvocation],
    adapters: Mapping[str, ProviderAdapter],
    repo_root: str,
    prompt: str,
    timeout_seconds: int,
    provider_permissions: Mapping[str, Mapping[str, str]],
    allow_paths: Sequence[str],
) -> dict[str, object]:
    outputs: list[dict[str, str]] = []
    with tempfile.TemporaryDirectory(prefix="mco-invocations-") as artifact_base:
        for invocation in invocations:
            adapter = adapters[invocation.provider]
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
            run_ref = adapter.run(task)
            deadline = time.monotonic() + timeout_seconds
            while True:
                status = adapter.poll(run_ref)
                if status.completed:
                    break
                if time.monotonic() >= deadline:
                    adapter.cancel(run_ref)
                    raise RuntimeError("invocation '{}' timed out".format(invocation.invocation_id))
                time.sleep(0.05)
            if status.attempt_state != "SUCCEEDED":
                raise RuntimeError("invocation '{}' failed: {}".format(invocation.invocation_id, status.message))
            output_path = Path(run_ref.artifact_path) / "raw" / "{}.stdout.log".format(invocation.provider)
            output = output_path.read_text(encoding="utf-8") if output_path.exists() else ""
            outputs.append({
                "invocation_id": invocation.invocation_id,
                "provider": invocation.provider,
                "model": invocation.model,
                "output": output,
            })
    return {"status": "complete", "outputs": outputs}
