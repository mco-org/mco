from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional, Set

from .config import ReviewPolicy
from .contracts import ProviderAdapter


@dataclass(frozen=True)
class ExecutionPreviewRequest:
    repo_root: str
    prompt: str
    providers: List[str]
    artifact_base: str
    policy: ReviewPolicy
    task_id: Optional[str] = None
    target_paths: Optional[List[str]] = None


def _supported_keys(adapter: ProviderAdapter, name: str) -> Set[str]:
    fn = getattr(adapter, name, None)
    if not callable(fn):
        return set()
    try:
        keys = fn()
    except (TypeError, AttributeError):
        return set()
    if not isinstance(keys, list):
        return set()
    return {str(item).strip() for item in keys if str(item).strip()}


def provider_policy_preview(provider: str, adapter: ProviderAdapter, policy: ReviewPolicy) -> Dict[str, object]:
    requested_permissions = policy.provider_permissions.get(provider, {})
    requested_permissions = requested_permissions if isinstance(requested_permissions, dict) else {}
    supported_permissions = _supported_keys(adapter, "supported_permission_keys")
    unknown_permission_keys = sorted(
        key for key in requested_permissions if str(key).strip() and key not in supported_permissions
    )
    effective_permissions = {
        str(key): str(value)
        for key, value in requested_permissions.items()
        if str(key).strip() in supported_permissions
    }

    requested_model = policy.provider_models.get(provider, {})
    requested_model = requested_model if isinstance(requested_model, dict) else {}
    supported_models = _supported_keys(adapter, "supported_model_keys")
    unknown_model_keys = sorted(key for key in requested_model if str(key).strip() and key not in supported_models)
    effective_model = {
        str(key): str(value)
        for key, value in requested_model.items()
        if str(key).strip() in supported_models and str(value).strip()
    }

    requested_context = policy.provider_context.get(provider, {})
    requested_context = requested_context if isinstance(requested_context, dict) else {}
    supported_context = _supported_keys(adapter, "supported_context_keys")
    unknown_context_keys = sorted(
        key
        for key in requested_context
        if key not in supported_context and not (provider == "pi" and key == "extensions" and requested_context[key] is False)
    )
    effective_context = {str(key): value for key, value in requested_context.items() if key in supported_context}

    incompatible_context_keys: List[str] = []
    dropped_context_keys = list(unknown_context_keys)
    if provider == "hermes":
        skills = effective_context.get("skills")
        has_skills = skills == "ambient" or (isinstance(skills, list) and bool(skills))
        if has_skills and effective_context.get("context_files") is False:
            incompatible_context_keys.extend(["skills", "context_files"])
            if policy.enforcement_mode != "strict":
                effective_context.pop("skills", None)
                effective_context.pop("context_files", None)
                dropped_context_keys.extend(incompatible_context_keys)

    dropped_context_keys = sorted(set(dropped_context_keys))
    incompatible_context_keys = sorted(set(incompatible_context_keys))
    failure_reason = ""
    if policy.enforcement_mode == "strict":
        if unknown_permission_keys:
            failure_reason = "permission_enforcement_failed"
        elif unknown_model_keys:
            failure_reason = "model_selection_failed"
        elif unknown_context_keys or incompatible_context_keys:
            failure_reason = "context_policy_enforcement_failed"

    return {
        "enforcement_mode": policy.enforcement_mode,
        "requested_permissions": requested_permissions,
        "applied_permissions": effective_permissions,
        "supported_permission_keys": sorted(supported_permissions),
        "unknown_permission_keys": unknown_permission_keys,
        "requested_model": dict(requested_model),
        "applied_model": dict(effective_model),
        "supported_model_keys": sorted(supported_models),
        "unknown_model_keys": unknown_model_keys,
        "requested_context": dict(requested_context),
        "applied_context": dict(effective_context),
        "supported_context_keys": sorted(supported_context),
        "unknown_context_keys": unknown_context_keys,
        "incompatible_context_keys": incompatible_context_keys,
        "dropped_context_keys": dropped_context_keys,
        "would_fail_strict": bool(failure_reason),
        "failure_reason": failure_reason,
    }
