from __future__ import annotations

import argparse
import hashlib
import json
import signal
import sys
import threading
from pathlib import Path
from typing import Any, Callable, Dict, List, Mapping, Optional

from .adapters import adapter_registry
from .config import ReviewConfig, ReviewPolicy, load_agent_registrations
from .contracts import ProviderPresence, TaskInput
from .execution_modes import EXECUTION_MODES, execution_permissions
from .invocation_runtime import default_invocations, parse_invocations, run_invocation_workflow, validate_execution_scope
from .models import discover_models
from .provider_risk import effective_provider_risk, provider_risk
from .skill_health import check_skill_health
from .skill_manager import read_bundled_skill, skill_status, sync_bundled_skill
from . import __version__
from .policy import ExecutionPreviewRequest, provider_policy_preview

SUPPORTED_PROVIDERS = ("claude", "codex", "copilot", "cursor", "gemini", "grok", "hermes", "opencode", "pi", "qwen")
SUPPORTED_PROVIDER_LIST = ",".join(SUPPORTED_PROVIDERS)
DEFAULT_DOCTOR_PROVIDERS = SUPPORTED_PROVIDERS
DEFAULT_CONFIG = ReviewConfig()
DEFAULT_POLICY = DEFAULT_CONFIG.policy


_ERROR_DETAILS = {
    "parse_error": ("input", "Check command syntax with `mco <command> --help`."),
    "input_error": ("input", "Correct the input and retry the command."),
    "provider_selection_required": ("input", "Ask the user which agents to use, then retry with --providers."),
    "invalid_providers": ("input", "Select providers shown by `mco agent list --json`."),
    "config_error": ("configuration", "Correct the project/global configuration and retry."),
    "invalid_config": ("configuration", "Remove the incompatible flags or configuration values and retry."),
    "agent_selection_required": ("configuration", "Choose one or more calling agents for the mco-cli Skill."),
    "removed_surface": ("input", "Use the invocation-native raw text, JSON, JSONL, or artifact output instead."),
    "runtime_error": ("runtime", "Inspect provider results and logs before retrying."),
}


def _error_envelope(
    subtype: str,
    message: str,
    *,
    provider: Optional[str] = None,
    retryable: bool = False,
    exit_code: int = 2,
) -> Dict[str, object]:
    category, hint = _ERROR_DETAILS.get(
        subtype,
        ("runtime", "Inspect the error message and retry only after correcting the cause."),
    )
    return {
        "ok": False,
        "error": {
            "category": category,
            "subtype": subtype,
            "message": message,
            "hint": hint,
            "provider": provider,
            "retryable": retryable,
            "exit_code": exit_code,
        },
    }


def _stream_error_event(subtype: str, message: str) -> Dict[str, object]:
    from datetime import datetime, timezone

    envelope = _error_envelope(subtype, message)
    return {
        "type": "error",
        "code": subtype,
        "message": message,
        "error": envelope["error"],
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
    }


class _HelpFormatter(argparse.RawTextHelpFormatter):
    def _get_help_string(self, action: argparse.Action) -> str:
        help_text = action.help or ""
        default = action.default
        if default not in (None, "", False, argparse.SUPPRESS) and "%(default)" not in help_text:
            help_text += " (default: %(default)s)"
        return help_text


class _StreamSafeParser(argparse.ArgumentParser):
    def __init__(self, *args: object, **kwargs: object) -> None:
        super().__init__(*args, **kwargs)
        self._stream_error_handler: Optional[Callable[[str], None]] = None

    def set_stream_error_handler(self, handler: Optional[Callable[[str], None]]) -> None:
        self._stream_error_handler = handler
        for action in self._actions:
            if isinstance(action, argparse._SubParsersAction):
                for subparser in action.choices.values():
                    if isinstance(subparser, _StreamSafeParser):
                        subparser.set_stream_error_handler(handler)

    def error(self, message: str) -> None:
        if self._stream_error_handler is not None:
            self._stream_error_handler(message)
            raise SystemExit(2)
        super().error(message)


TOP_LEVEL_DESCRIPTION = (
    "MCO - Orchestrate AI Coding Agents. Any Prompt. Any Agent. Any IDE.\n"
    "Use `run` for general tasks and `review` for a thin read-only raw-answer preset."
)

TOP_LEVEL_EPILOG = (
    "Examples:\n"
    "  mco doctor --json\n"
    "  mco run --repo . --prompt \"Summarize this repo.\" --providers claude,codex\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --providers claude,codex,qwen --json\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --debate\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --divide dimensions\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --stream live\n"
    "  mco agent list\n\n"
    "Use `mco doctor -h`, `mco run -h`, or `mco review -h` for full command options."
)

RUN_EPILOG = (
    "Examples:\n"
    "  mco run --repo . --prompt \"Summarize the architecture.\" --providers claude,codex\n"
    "  mco run --repo . --prompt \"List risky files.\" --providers claude,codex,qwen --json\n"
    "  mco run --repo . --prompt \"Compare provider outputs.\" --providers claude,codex,qwen --synthesize\n"
    "  mco run --repo . --prompt \"Analyze runtime.\" --save-artifacts --json\n\n"
    "Exit codes:\n"
    "  0 = complete (all invocations succeeded)\n"
    "  1 = partial (at least one invocation succeeded)\n"
    "  2 = failed or input/configuration error"
)

REVIEW_EPILOG = (
    "Examples:\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --providers claude,codex\n"
    "  mco review --repo . --prompt \"Review for security issues.\" --providers claude,codex,qwen --json\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --providers claude,codex,qwen --synthesize --synth-provider claude\n"
    "  mco review --repo . --prompt \"Review runtime/ only.\" --target-paths runtime --stream jsonl\n\n"
    "Exit codes:\n"
    "  0 = complete (all invocations succeeded)\n"
    "  1 = partial (at least one invocation succeeded)\n"
    "  2 = failed / input / config / runtime failure\n"
)

DOCTOR_EPILOG = (
    "Examples:\n"
    "  mco doctor\n"
    "  mco doctor --providers claude,codex --json\n"
    "  mco doctor --skill-health --json\n\n"
    "Exit codes:\n"
    "  0 = command completed (read overall_ok in output)\n"
    "  2 = invalid input"
)

def _doctor_adapter_registry(transport: str = "shim", extra_agents=None, configured_agents=None) -> Mapping[str, object]:
    return adapter_registry(transport=transport, extra_agents=extra_agents, configured_agents=configured_agents)


def _normalize_cli_agent_pairs(raw_agents: object) -> Dict[str, List[str]]:
    if raw_agents is None:
        return {}
    entries = raw_agents if isinstance(raw_agents, list) and raw_agents and isinstance(raw_agents[0], list) else [raw_agents]
    normalized: Dict[str, List[str]] = {}
    for entry in entries:
        if not isinstance(entry, list) or len(entry) != 2:
            continue
        name = str(entry[0]).strip()
        command = str(entry[1]).strip()
        if not name or not command:
            continue
        import shlex

        normalized[name] = shlex.split(command)
    return normalized


def _load_available_agents(repo_root: str, cli_agents: Optional[Dict[str, List[str]]] = None) -> List[Dict[str, object]]:
    available: List[Dict[str, object]] = []
    seen = set()
    for provider in SUPPORTED_PROVIDERS:
        available.append({"name": provider, "source": "builtin", "transport": "shim", "risk": provider_risk(provider)})
        seen.add(provider)
    for agent in load_agent_registrations(repo_root):
        name = str(agent.get("name", "")).strip()
        if not name or name in seen:
            continue
        available.append({
            "name": name,
            "source": "config",
            "transport": str(agent.get("transport", "shim")),
            "command": agent.get("command"),
            "model": agent.get("model"),
            "timeout": agent.get("timeout"),
            "permission_keys": agent.get("permission_keys", []),
            "risk": provider_risk(name),
        })
        seen.add(name)
    for name, command in (cli_agents or {}).items():
        if name in seen:
            continue
        available.append({
            "name": name,
            "source": "cli",
            "transport": "acp",
            "command": " ".join(command),
            "risk": provider_risk(name),
        })
        seen.add(name)
    return available


def _check_agent(repo_root: str, name: str, cli_agents: Optional[Dict[str, List[str]]] = None) -> Dict[str, object]:
    configured_agents = load_agent_registrations(repo_root)
    reg = adapter_registry(transport="shim", extra_agents=cli_agents, configured_agents=configured_agents)
    adapter = reg.get(name)
    if adapter is None:
        return {
            "name": name,
            "ready": False,
            "detected": False,
            "binary_path": None,
            "version": None,
            "transport": None,
            "reason": "unknown_agent",
            "risk": provider_risk(name),
        }
    probe = adapter.detect()
    return {
        "name": name,
        "ready": bool(probe.detected and probe.auth_ok),
        "detected": bool(probe.detected),
        "binary_path": probe.binary_path,
        "version": probe.version,
        "transport": "acp" if hasattr(adapter, "_acp_command") else "shim",
        "reason": probe.reason,
        "risk": provider_risk(name),
    }


def _stdout_is_tty() -> bool:
    isatty = getattr(sys.stdout, "isatty", None)
    return bool(callable(isatty) and isatty())


def _build_stream_callback(stream_mode: Optional[str], *, chain_mode: bool = False):
    if stream_mode == "jsonl":
        import threading as _threading

        _stream_lock = _threading.Lock()

        def _stream_emit(event: dict) -> None:
            line = json.dumps(event, ensure_ascii=True)
            with _stream_lock:
                print(line, flush=True)

        return _stream_emit, "jsonl", None

    if stream_mode == "live":
        if not _stdout_is_tty():
            return _build_stream_callback("jsonl", chain_mode=chain_mode)
        return None, "live", None

    return None, None, None


def _resolve_prompt(args: argparse.Namespace, default_prompt: str = "") -> str:
    """Resolve prompt from --prompt, --file, or piped stdin.

    Raises ValueError with a human-readable message on failure.
    """
    prompt = getattr(args, "prompt", "") or ""
    file_path = getattr(args, "file", "") or ""

    if prompt:
        return prompt

    if file_path:
        if file_path == "-":
            text = sys.stdin.read().strip()
            if not text:
                raise ValueError("Empty input from stdin.")
            return text
        path = Path(file_path)
        if not path.exists():
            raise ValueError("File not found: {}".format(file_path))
        text = path.read_text(encoding="utf-8").strip()
        if not text:
            raise ValueError("Empty prompt file: {}".format(file_path))
        return text

    # Check for piped stdin
    if not sys.stdin.isatty():
        text = sys.stdin.read().strip()
        if text:
            return text
        if default_prompt:
            return default_prompt
        raise ValueError("Empty input from stdin.")

    if default_prompt:
        return default_prompt

    raise ValueError("Either --prompt or --file is required.")


def _doctor_provider_presence(providers: List[str]) -> Dict[str, ProviderPresence]:
    adapters = _doctor_adapter_registry()
    presence: Dict[str, ProviderPresence] = {}
    for provider in providers:
        adapter = adapters.get(provider)
        if adapter is None:
            continue
        try:
            probe = adapter.detect()
        except Exception as exc:
            presence[provider] = ProviderPresence(
                provider=provider,  # type: ignore[arg-type]
                detected=False,
                binary_path=None,
                version=None,
                auth_ok=False,
                reason=f"probe_error:{exc.__class__.__name__}",
            )
            continue
        presence[provider] = probe
    return presence


def _doctor_payload(
    providers: List[str],
    presence_map: Dict[str, ProviderPresence],
    *,
    skill_health: Optional[Dict[str, object]] = None,
    skill_drift: Optional[Dict[str, object]] = None,
) -> Dict[str, object]:
    provider_payload: Dict[str, Dict[str, object]] = {}
    ready_count = 0
    for provider in providers:
        presence = presence_map.get(
            provider,
            ProviderPresence(  # type: ignore[arg-type]
                provider=provider, detected=False, binary_path=None, version=None, auth_ok=False, reason="not_checked"
            ),
        )
        ready = bool(presence.detected and presence.auth_ok)
        if ready:
            ready_count += 1
        provider_payload[provider] = {
            "detected": bool(presence.detected),
            "binary_path": presence.binary_path,
            "version": presence.version,
            "auth_ok": bool(presence.auth_ok),
            "reason": presence.reason,
            "ready": ready,
            "risk": provider_risk(provider),
        }
    payload: Dict[str, object] = {
        "command": "doctor",
        "overall_ok": ready_count == len(providers),
        "ready_count": ready_count,
        "provider_count": len(providers),
        "providers": provider_payload,
    }
    if skill_health is not None:
        payload["skill_health"] = skill_health
    if skill_drift is not None:
        payload["skill_drift"] = skill_drift
    return payload


def _render_doctor_report(payload: Dict[str, object]) -> str:
    lines: List[str] = ["Doctor Result", ""]
    lines.append(f"- overall_ok: {payload.get('overall_ok')}")
    lines.append(f"- ready/total: {payload.get('ready_count')}/{payload.get('provider_count')}")
    lines.append("")
    lines.append("Provider Checks")
    providers = payload.get("providers", {})
    if not isinstance(providers, dict):
        return "\n".join(lines)
    for provider in sorted(providers.keys()):
        details = providers.get(provider, {})
        if not isinstance(details, dict):
            continue
        status = "READY" if bool(details.get("ready")) else "NOT_READY"
        reason = str(details.get("reason") or "")
        lines.append(f"- {provider}: {status} (reason={reason})")
        lines.append(f"  detected={bool(details.get('detected'))} auth_ok={bool(details.get('auth_ok'))}")
        lines.append(f"  binary_path={details.get('binary_path')}")
        lines.append(f"  version={details.get('version')}")
        risk = details.get("risk", {})
        if isinstance(risk, dict):
            lines.append(f"  risk={risk.get('level')} ({risk.get('reason')})")
    if not payload.get("overall_ok"):
        ready_providers = sorted(
            provider
            for provider, details in providers.items()
            if isinstance(details, dict) and details.get("ready")
        )
        if ready_providers:
            ready_csv = ",".join(ready_providers)
            lines.extend([
                "",
                "Next Steps",
                f"- Ready providers: {ready_csv}",
                f"- Example: mco run --repo . --prompt \"<task>\" --providers {ready_csv} --dry-run --json",
                "- Tip: persist provider subset in .mcorc.json",
            ])
    skill_health = payload.get("skill_health")
    if isinstance(skill_health, dict) and skill_health.get("enabled"):
        lines.extend(["", "Skill Check"])
        lines.append(f"- status: {skill_health.get('status')} ({skill_health.get('reason')})")
        reference = skill_health.get("reference", {})
        if isinstance(reference, dict) and reference.get("path"):
            ref_sha = reference.get("sha256")
            sha_suffix = f", sha256={ref_sha[:12]}..." if isinstance(ref_sha, str) and ref_sha else ""
            lines.append(f"- reference: {reference.get('path')}{sha_suffix}")
        skill_drift = payload.get("skill_drift")
        if isinstance(skill_drift, dict):
            drifted = skill_drift.get("drifted") or []
            matched = skill_drift.get("matched") or []
            if drifted:
                lines.append(f"- drift: {', '.join(str(item) for item in drifted)}")
            if matched:
                lines.append(f"- matched: {', '.join(str(item) for item in matched)}")
    return "\n".join(lines)


def _dry_run_command_template(provider: str, adapter: object, req: ExecutionPreviewRequest, review_mode: bool, policy: Dict[str, object]) -> List[str]:
    metadata: Dict[str, object] = {
        "artifact_root": "<artifact_root>",
        "allow_paths": req.policy.allow_paths,
        "provider_permissions": policy.get("applied_permissions", {}),
        "enforcement_mode": req.policy.enforcement_mode,
    }
    applied_model = policy.get("applied_model", {})
    if isinstance(applied_model, dict):
        metadata.update(applied_model)
    applied_context = policy.get("applied_context", {})
    if provider in req.policy.provider_context:
        metadata["provider_context"] = dict(applied_context) if isinstance(applied_context, dict) else {}
    preview_command = getattr(adapter, "preview_command", None)
    if callable(preview_command):
        permissions = policy.get("applied_permissions", {})
        return list(preview_command(permissions if isinstance(permissions, dict) else {}))
    build_command = getattr(adapter, "_build_command", None)
    if callable(build_command):
        return list(build_command(TaskInput(
            task_id=req.task_id or "<task_id>",
            prompt="<prompt>",
            repo_root=req.repo_root,
            target_paths=req.target_paths or ["."],
            metadata=metadata,
        )))
    build_record = getattr(adapter, "_build_command_for_record", None)
    if callable(build_record):
        return list(build_record())
    return []


def _build_dry_run_payload(
    args: argparse.Namespace,
    req: ExecutionPreviewRequest,
    *,
    providers: List[str],
    adapters: Mapping[str, object],
    review_mode: bool,
    result_mode: str,
    write_artifacts: bool,
    transport: str,
    synthesize: bool,
    synth_provider: str,
) -> Dict[str, object]:
    provider_details: Dict[str, object] = {}
    for provider in providers:
        adapter = adapters.get(provider)
        if adapter is None:
            default_risk = provider_risk(provider, transport=transport)
            provider_details[provider] = {
                "default_risk": default_risk,
                "risk": default_risk,
                "policy": {"failure_reason": "adapter_not_implemented", "would_fail_strict": True},
                "command_template": [],
            }
            continue
        policy = dict(provider_policy_preview(provider, adapter, req.policy))
        default_risk = provider_risk(provider, transport=transport)
        applied_permissions = policy.get("applied_permissions", {})
        effective_risk = effective_provider_risk(
            provider,
            applied_permissions if isinstance(applied_permissions, dict) else {},
            transport=transport,
        )
        if (
            effective_risk["level"] == "unknown"
            and req.policy.enforcement_mode == "strict"
            and not policy.get("would_fail_strict")
        ):
            policy["would_fail_strict"] = True
            policy["failure_reason"] = "risk_classification_unknown"
        provider_details[provider] = {
            "default_risk": default_risk,
            "risk": effective_risk,
            "policy": policy,
            "command_template": _dry_run_command_template(provider, adapter, req, review_mode, policy),
        }
    return {
        "command": args.command,
        "dry_run": True,
        "would_execute": False,
        "review_mode": review_mode,
        "repo_root": req.repo_root,
        "providers": providers,
        "target_paths": req.target_paths or ["."],
        "transport": transport,
        "result_mode": result_mode,
        "write_artifacts": write_artifacts,
        "artifact_base": req.artifact_base,
        "task_id": req.task_id,
        "prompt": {
            "chars": len(req.prompt),
            "sha256": hashlib.sha256(req.prompt.encode("utf-8")).hexdigest(),
        },
        "policy": {
            "allow_paths": list(req.policy.allow_paths),
            "enforcement_mode": req.policy.enforcement_mode,
            "execution_mode": req.policy.execution_mode,
            "provider_permissions": req.policy.provider_permissions,
            "provider_models": req.policy.provider_models,
            "provider_context": req.policy.provider_context,
            "perspectives": req.policy.perspectives,
            "chain": req.policy.chain,
            "debate": req.policy.debate,
            "divide": req.policy.divide,
        },
        "providers_detail": provider_details,
        "execution_mode": req.policy.execution_mode,
        "synthesis": {"enabled": synthesize, "provider": synth_provider or None},
    }


def _render_dry_run_report(payload: Dict[str, object]) -> str:
    lines = ["Dry Run", ""]
    lines.append(f"- would_execute: {payload.get('would_execute')}")
    lines.append(f"- command: {payload.get('command')}")
    lines.append(f"- repo_root: {payload.get('repo_root')}")
    lines.append(f"- providers: {', '.join(str(item) for item in payload.get('providers', []))}")
    lines.append("")
    lines.append("Provider Preview")
    details = payload.get("providers_detail", {})
    if isinstance(details, dict):
        for provider in sorted(details.keys()):
            item = details.get(provider, {})
            if not isinstance(item, dict):
                continue
            risk = item.get("risk", {})
            policy = item.get("policy", {})
            risk_level = risk.get("level") if isinstance(risk, dict) else "unknown"
            failure = policy.get("failure_reason") if isinstance(policy, dict) else ""
            suffix = f" failure={failure}" if failure else ""
            lines.append(f"- {provider}: risk={risk_level}{suffix}")
            command = item.get("command_template", [])
            if isinstance(command, list) and command:
                lines.append("  command=" + " ".join(str(part) for part in command))
    return "\n".join(lines)


def _parse_providers(raw: str) -> List[str]:
    seen = set()
    providers: List[str] = []
    for item in raw.split(","):
        value = item.strip()
        if not value or value in seen:
            continue
        seen.add(value)
        providers.append(value)
    return providers


def _parse_provider_timeouts(raw: str) -> Dict[str, int]:
    result: Dict[str, int] = {}
    if not raw.strip():
        return result
    for chunk in raw.split(","):
        pair = chunk.strip()
        if not pair:
            continue
        if "=" not in pair:
            raise ValueError(f"invalid provider timeout entry: {pair}")
        provider, timeout_text = pair.split("=", 1)
        provider_name = provider.strip()
        if not provider_name:
            raise ValueError(f"invalid provider timeout entry: {pair}")
        try:
            timeout = int(timeout_text.strip())
        except Exception:
            raise ValueError(f"invalid timeout value for provider '{provider_name}': {timeout_text.strip()}") from None
        if timeout <= 0:
            raise ValueError(f"timeout must be > 0 for provider '{provider_name}'")
        result[provider_name] = timeout
    return result


def _parse_paths(raw: str) -> List[str]:
    paths = [item.strip() for item in raw.split(",") if item.strip()]
    return paths if paths else ["."]


def _parse_provider_permissions_json(raw: str) -> Dict[str, Dict[str, str]]:
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except Exception:
        raise ValueError("--provider-permissions-json must be valid JSON") from None
    if not isinstance(payload, dict):
        raise ValueError("--provider-permissions-json root must be an object")

    result: Dict[str, Dict[str, str]] = {}
    for provider, permissions in payload.items():
        provider_name = str(provider).strip()
        if not provider_name:
            raise ValueError("--provider-permissions-json contains empty provider name")
        if not isinstance(permissions, dict):
            raise ValueError(f"permissions for provider '{provider_name}' must be an object")
        normalized: Dict[str, str] = {}
        for key, value in permissions.items():
            key_name = str(key).strip()
            if not key_name:
                raise ValueError(f"provider '{provider_name}' contains empty permission key")
            normalized[key_name] = str(value)
        result[provider_name] = normalized
    return result


def _normalize_model_config_text(value: object, *, provider: str, key: str) -> str:
    if not isinstance(value, str):
        raise ValueError(
            "--provider-models-json value for provider '{}' key '{}' must be a string".format(provider, key)
        )
    text = value.strip()
    if not text:
        raise ValueError(
            "--provider-models-json value for provider '{}' key '{}' must not be empty".format(provider, key)
        )
    if "\x00" in text or any(ord(char) < 32 for char in text):
        raise ValueError(
            "--provider-models-json value for provider '{}' key '{}' contains control characters".format(
                provider, key
            )
        )
    return text


def _parse_provider_models_json(raw: str) -> Dict[str, Dict[str, str]]:
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("--provider-models-json must be valid JSON") from None
    if not isinstance(payload, dict):
        raise ValueError("--provider-models-json root must be an object")
    result: Dict[str, Dict[str, str]] = {}
    for provider, config in payload.items():
        provider_name = str(provider).strip()
        if not provider_name:
            raise ValueError("--provider-models-json contains empty provider name")
        if "\x00" in provider_name or any(ord(char) < 32 for char in provider_name):
            raise ValueError("--provider-models-json provider name contains control characters")
        normalized: Dict[str, str] = {}
        if isinstance(config, str):
            normalized["model"] = _normalize_model_config_text(config, provider=provider_name, key="model")
        elif isinstance(config, dict):
            for key, value in config.items():
                key_name = str(key).strip()
                if key_name not in ("model", "provider"):
                    raise ValueError(
                        "--provider-models-json only supports 'model' and 'provider' keys; got '{}' for provider '{}'".format(
                            key_name, provider_name
                        )
                    )
                if value is None:
                    continue
                normalized[key_name] = _normalize_model_config_text(value, provider=provider_name, key=key_name)
        else:
            raise ValueError(
                "--provider-models-json values must be strings or objects, got {} for provider '{}'".format(
                    type(config).__name__, provider_name
                )
            )
        result[provider_name] = normalized
    return result


def _merge_provider_models(
    base: Dict[str, Dict[str, str]],
    override: Dict[str, Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    merged: Dict[str, Dict[str, str]] = {provider: dict(values) for provider, values in base.items()}
    for provider, config in override.items():
        current = merged.get(provider, {})
        current.update(config)
        merged[provider] = current
    return merged


# Allowed context policy keys per the provider-context schema.
# Keys NOT in this set are still accepted by the parser (they may be
# provider-specific), but they are validated against each adapter's
# supported_context_keys() at execution time.
_BASE_CONTEXT_KEYS = {"skills", "context_files", "extensions"}
# Forbidden: keys that belong to other policy surfaces and must not
# leak into provider_context.
_FORBIDDEN_CONTEXT_KEYS = {"tools", "yolo", "accept_hooks", "ignore_rules", "permission_mode", "sandbox"}


def _normalize_context_value(value: object, *, provider: str, key: str) -> Any:
    """Normalize a single context policy value.

    skills: "disabled" | "ambient" | list of strings
    context_files: bool
    extensions: bool
    """
    if key == "context_files" or key == "extensions":
        if not isinstance(value, bool):
            raise ValueError(
                "--provider-context-json key '{}' for provider '{}' must be a boolean".format(key, provider)
            )
        return value
    if key == "skills":
        if isinstance(value, bool):
            raise ValueError(
                "--provider-context-json key 'skills' for provider '{}' must be 'disabled', 'ambient', or a list of skill names, not a boolean".format(provider)
            )
        if isinstance(value, str):
            text = value.strip()
            if text in ("disabled", "ambient"):
                return text
            raise ValueError(
                "--provider-context-json key 'skills' for provider '{}' must be 'disabled' or 'ambient', got '{}'".format(provider, text)
            )
        if isinstance(value, list):
            normalized: List[str] = []
            for item in value:
                if not isinstance(item, str):
                    raise ValueError(
                        "--provider-context-json skill names for provider '{}' must be strings".format(provider)
                    )
                item_text = item.strip()
                if not item_text:
                    raise ValueError(
                        "--provider-context-json skill names for provider '{}' must not be empty".format(provider)
                    )
                if "\x00" in item_text or any(ord(ch) < 32 for ch in item_text):
                    raise ValueError(
                        "--provider-context-json skill name for provider '{}' contains control characters".format(provider)
                    )
                if item_text.startswith("-"):
                    raise ValueError(
                        "--provider-context-json skill name for provider '{}' must not start with '-'".format(provider)
                    )
                normalized.append(item_text)
            return normalized
        raise ValueError(
            "--provider-context-json key 'skills' for provider '{}' must be 'disabled', 'ambient', or a list of strings".format(provider)
        )
    raise ValueError(
        "--provider-context-json unsupported key '{}' for provider '{}'".format(key, provider)
    )


def _parse_provider_context_json(raw: str) -> Dict[str, Dict[str, Any]]:
    """Parse --provider-context-json into a normalized provider context dict."""
    if not raw.strip():
        return {}
    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise ValueError("--provider-context-json must be valid JSON") from None
    if not isinstance(payload, dict):
        raise ValueError("--provider-context-json root must be an object")
    result: Dict[str, Dict[str, Any]] = {}
    for provider, config in payload.items():
        provider_name = str(provider).strip()
        if not provider_name:
            raise ValueError("--provider-context-json contains empty provider name")
        if "\x00" in provider_name or any(ord(ch) < 32 for ch in provider_name):
            raise ValueError("--provider-context-json provider name contains control characters")
        if not isinstance(config, dict):
            raise ValueError(
                "--provider-context-json value for provider '{}' must be an object".format(provider_name)
            )
        normalized: Dict[str, Any] = {}
        for key, value in config.items():
            key_name = str(key).strip()
            if key_name in _FORBIDDEN_CONTEXT_KEYS:
                raise ValueError(
                    "--provider-context-json key '{}' for provider '{}' is forbidden (belongs to a different policy surface)".format(
                        key_name, provider_name
                    )
                )
            if key_name in _BASE_CONTEXT_KEYS:
                normalized[key_name] = _normalize_context_value(value, provider=provider_name, key=key_name)
            else:
                # Provider-specific key: validate key name, then accept as-is
                if not key_name:
                    raise ValueError(
                        "--provider-context-json contains empty key for provider '{}'".format(provider_name)
                    )
                if "\x00" in key_name or any(ord(ch) < 32 for ch in key_name):
                    raise ValueError(
                        "--provider-context-json key '{}' for provider '{}' contains control characters".format(
                            key_name, provider_name
                        )
                    )
                if key_name.startswith("-"):
                    raise ValueError(
                        "--provider-context-json key '{}' for provider '{}' must not start with '-'".format(
                            key_name, provider_name
                        )
                    )
                if isinstance(value, str):
                    text = value.strip()
                    if "\x00" in text or any(ord(ch) < 32 for ch in text):
                        raise ValueError(
                            "--provider-context-json key '{}' for provider '{}' contains control characters".format(
                                key_name, provider_name
                            )
                        )
                    normalized[key_name] = text
                elif isinstance(value, bool):
                    normalized[key_name] = value
                elif isinstance(value, list):
                    clean: List[str] = []
                    for item in value:
                        if not isinstance(item, str):
                            raise ValueError(
                                "--provider-context-json key '{}' for provider '{}' list values must be strings".format(
                                    key_name, provider_name
                                )
                            )
                        item_text = item.strip()
                        if not item_text:
                            raise ValueError(
                                "--provider-context-json key '{}' for provider '{}' list values must not be empty".format(
                                    key_name, provider_name
                                )
                            )
                        if "\x00" in item_text or any(ord(ch) < 32 for ch in item_text):
                            raise ValueError(
                                "--provider-context-json key '{}' for provider '{}' contains control characters".format(
                                    key_name, provider_name
                                )
                            )
                        clean.append(item_text)
                    normalized[key_name] = clean
                else:
                    raise ValueError(
                        "--provider-context-json key '{}' for provider '{}' must be a string, boolean, or list of strings".format(
                            key_name, provider_name
                        )
                    )
        result[provider_name] = normalized
    return result


def _merge_provider_context(
    base: Dict[str, Dict[str, Any]],
    override: Dict[str, Dict[str, Any]],
) -> Dict[str, Dict[str, Any]]:
    """Deep-merge override context into base context."""
    merged: Dict[str, Dict[str, Any]] = {provider: dict(values) for provider, values in base.items()}
    for provider, config in override.items():
        current = merged.get(provider, {})
        current.update(config)
        merged[provider] = current
    return merged


def _merge_provider_permissions(
    base: Dict[str, Dict[str, str]],
    override: Dict[str, Dict[str, str]],
) -> Dict[str, Dict[str, str]]:
    merged: Dict[str, Dict[str, str]] = {provider: dict(values) for provider, values in base.items()}
    for provider, permissions in override.items():
        current = merged.get(provider, {})
        current.update(permissions)
        merged[provider] = current
    return merged


def _add_common_execution_args(parser: argparse.ArgumentParser) -> None:
    scope = parser.add_argument_group("Execution Scope")
    scope.add_argument("--repo", default=".", help="Repository root path")
    prompt_group = scope.add_mutually_exclusive_group()
    prompt_group.add_argument("--prompt", default="", help="Task prompt (inline)")
    prompt_group.add_argument(
        "--file",
        default="",
        help="Read prompt from file path, or '-' for stdin. Overridden by --prompt if both specified.",
    )
    scope.add_argument(
        "--providers",
        default=argparse.SUPPRESS,
        help=(
            "Comma-separated providers. Required unless configured explicitly. "
            "Supported: {}"
        ).format(SUPPORTED_PROVIDER_LIST),
    )
    scope.add_argument("--target-paths", default=".", help="Comma-separated task scope paths")
    scope.add_argument("--task-id", default="", help="Optional stable task id")
    scope.add_argument(
        "--transport",
        choices=("shim", "acp"),
        default=argparse.SUPPRESS,
        help="Agent communication transport. shim: stdout parsing (default), acp: Agent Client Protocol (JSON-RPC)",
    )
    scope.add_argument(
        "--execution-mode",
        choices=EXECUTION_MODES,
        default=argparse.SUPPRESS,
        help="Unified agent permission mode: read_only, write, or yolo",
    )
    scope.add_argument(
        "--agent",
        action="append",
        dest="invocation_agents",
        metavar="[ALIAS=]PROVIDER:MODEL",
        help="Repeatable model-qualified invocation. For example: --agent fast=pi:gpt-5.4",
    )
    scope.add_argument(
        "--custom-agent",
        nargs=2,
        metavar=("NAME", "COMMAND"),
        default=None,
        help="Register a temporary ACP agent; select it separately with --providers NAME",
    )

    timeouts = parser.add_argument_group("Timeout and Parallelism")
    timeouts.add_argument(
        "--max-provider-parallelism",
        type=int,
        default=argparse.SUPPRESS,
        help="Provider fan-out concurrency. 0 means full parallelism",
    )
    timeouts.add_argument(
        "--provider-timeouts",
        default="",
        help="Provider-specific stall-timeout overrides, e.g. claude=120,codex=90",
    )
    timeouts.add_argument(
        "--stall-timeout",
        type=int,
        default=argparse.SUPPRESS,
        help=f"Per-provider stall timeout in seconds (default: {DEFAULT_POLICY.stall_timeout_seconds})",
    )
    timeouts.add_argument(
        "--poll-interval",
        type=float,
        default=argparse.SUPPRESS,
        help="Provider status polling interval in seconds",
    )
    timeouts.add_argument(
        "--review-hard-timeout",
        type=int,
        default=argparse.SUPPRESS,
        help="Global hard deadline for entire review run, distinct from per-provider stall timeout (0 disables)",
    )

    output = parser.add_argument_group("Output")
    output.add_argument(
        "--artifact-base",
        default=DEFAULT_CONFIG.artifact_base,
        help="Artifact base directory",
    )
    output.add_argument(
        "--result-mode",
        choices=("artifact", "stdout", "both"),
        default="stdout",
        help="artifact: write files, stdout: print payload, both: do both",
    )
    output.add_argument(
        "--format",
        default="",
        help=argparse.SUPPRESS,
    )
    output.add_argument(
        "--include-token-usage",
        action="store_true",
        help="Best-effort token usage extraction (provider and aggregate). Disabled by default for privacy/noise control",
    )
    output.add_argument(
        "--synthesize",
        action="store_true",
        help="Run one extra read-only synthesis pass over prior raw answers (default: disabled)",
    )
    output.add_argument(
        "--synth-provider",
        default="",
        help="Provider to run synthesis pass (must be included in --providers). Defaults to claude when available",
    )
    output.add_argument(
        "--save-artifacts",
        action="store_true",
        help="Force artifact writes when result-mode is stdout",
    )
    output.add_argument(
        "--dry-run",
        action="store_true",
        help="Preview resolved providers, policy, risk, and artifacts without executing agents",
    )
    output_excl = output.add_mutually_exclusive_group()
    output_excl.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    output_excl.add_argument("--quiet", action="store_true", default=argparse.SUPPRESS,
        help="Output only final text, no headers or formatting")
    output_excl.add_argument(
        "--stream",
        choices=["jsonl", "live"],
        default=None,
        help="Output streaming events to stdout (jsonl or live terminal mode)",
    )

    access = parser.add_argument_group("Access and Contracts")
    access.add_argument("--allow-paths", default=".", help="Comma-separated allowed paths under repo root")
    access.add_argument(
        "--enforcement-mode",
        choices=("strict", "best_effort"),
        default=argparse.SUPPRESS,
        help="strict fails closed when permission requirements are unmet",
    )
    access.add_argument(
        "--provider-permissions-json",
        default="",
        help="Provider permission mapping JSON, e.g. '{\"codex\":{\"sandbox\":\"workspace-write\"}}'",
    )
    access.add_argument(
        "--provider-models-json",
        default="",
        help="Per-provider model mapping JSON, e.g. '{\"codex\":\"gpt-5.5\",\"pi\":{\"provider\":\"seal\",\"model\":\"deepseek-v4-pro\"}}'",
    )
    access.add_argument(
        "--provider-context-json",
        default="",
        help="Per-provider context policy JSON, e.g. '{\"pi\":{\"skills\":\"disabled\",\"context_files\":false}}'",
    )
    access.add_argument(
        "--perspectives-json",
        default="",
        help=argparse.SUPPRESS,
    )
    review_flow = access.add_mutually_exclusive_group()
    review_flow.add_argument(
        "--chain",
        action="store_true",
        help="Chain mode: run providers sequentially, feeding each provider's output as context to the next",
    )
    review_flow.add_argument(
        "--debate",
        action="store_true",
        help="Debate mode: run a second read-only stage over prior raw answers",
    )
    review_flow.add_argument(
        "--divide",
        choices=("files", "dimensions"),
        default="",
        help=argparse.SUPPRESS,
    )
    access.add_argument(
        "--strict-contract",
        action="store_true",
        help=argparse.SUPPRESS,
    )

    memory = parser.add_argument_group("Memory")
    memory.add_argument(
        "--memory",
        action="store_true",
        default=argparse.SUPPRESS,
        help=argparse.SUPPRESS,
    )
    memory.add_argument(
        "--space",
        default="",
        help=argparse.SUPPRESS,
    )

    legacy_scope = parser.add_argument_group("Legacy options")
    legacy_scope.add_argument("--diff", action="store_true", help=argparse.SUPPRESS)
    legacy_scope.add_argument("--staged", action="store_true", help=argparse.SUPPRESS)
    legacy_scope.add_argument("--unstaged", action="store_true", help=argparse.SUPPRESS)
    legacy_scope.add_argument("--diff-base", default="", help=argparse.SUPPRESS)


def build_parser() -> argparse.ArgumentParser:
    parser = _StreamSafeParser(
        prog="mco",
        description=TOP_LEVEL_DESCRIPTION,
        epilog=TOP_LEVEL_EPILOG,
        formatter_class=_HelpFormatter,
    )
    parser.add_argument(
        "--version",
        action="version",
        version="mco {}".format(__version__),
        help="Show version and exit",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser(
        "version",
        help="Print mco version",
        description="Print the installed mco version.",
        formatter_class=_HelpFormatter,
    )

    doctor = subparsers.add_parser(
        "doctor",
        help="Check provider installation/auth readiness",
        description="Probe local provider binaries and auth status for each selected provider.",
        epilog=DOCTOR_EPILOG,
        formatter_class=_HelpFormatter,
    )
    doctor.add_argument(
        "--providers",
        default=",".join(DEFAULT_DOCTOR_PROVIDERS),
        help="Comma-separated providers. Supported: {}".format(SUPPORTED_PROVIDER_LIST),
    )
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    doctor.add_argument(
        "--skill-health",
        action="store_true",
        help="Best-effort check that local mco-cli SKILL.md installs match the bundled reference (default: disabled)",
    )
    doctor.add_argument(
        "--repo",
        default=".",
        help="Repository root used to locate skills/mco-cli/SKILL.md for skill drift checks",
    )

    agent_cmd = subparsers.add_parser(
        "agent",
        help="List and inspect available agents",
        description="Show built-in agents plus custom agents from config files or CLI flags.",
        formatter_class=_HelpFormatter,
    )
    agent_sub = agent_cmd.add_subparsers(dest="agent_action", required=True)

    agent_list = agent_sub.add_parser("list", help="List available agents", formatter_class=_HelpFormatter)
    agent_list.add_argument("--repo", default=".", help="Repository root path")
    agent_list.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    agent_list.add_argument(
        "--agent",
        nargs=2,
        action="append",
        metavar=("NAME", "COMMAND"),
        default=[],
        help='Temporary custom ACP agent: --agent mybot "mybot --acp"',
    )

    agent_check = agent_sub.add_parser("check", help="Check one agent", formatter_class=_HelpFormatter)
    agent_check.add_argument("name", help="Agent name")
    agent_check.add_argument("--repo", default=".", help="Repository root path")
    agent_check.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    agent_check.add_argument(
        "--agent",
        nargs=2,
        action="append",
        metavar=("NAME", "COMMAND"),
        default=[],
        help='Temporary custom ACP agent: --agent mybot "mybot --acp"',
    )

    agent_models = agent_sub.add_parser("models", help="List provider model choices", formatter_class=_HelpFormatter)
    agent_models.add_argument(
        "--providers",
        default="codex,hermes,pi",
        help="Comma-separated providers to inspect. Supported discovery: codex,hermes,pi",
    )
    agent_models.add_argument("--json", action="store_true", help="Print machine-readable JSON output")

    run = subparsers.add_parser(
        "run",
        help="Run general multi-provider task execution",
        description="Run a prompt across multiple providers and return opaque raw answers.",
        epilog=RUN_EPILOG,
        formatter_class=_HelpFormatter,
    )
    _add_common_execution_args(run)

    review = subparsers.add_parser(
        "review",
        help="Run multi-provider review",
        description="Run a thin read-only multi-provider review and return raw answers.",
        epilog=REVIEW_EPILOG,
        formatter_class=_HelpFormatter,
    )
    _add_common_execution_args(review)

    findings = subparsers.add_parser(
        "findings",
        help=argparse.SUPPRESS,
        description="Removed legacy findings command.",
        formatter_class=_HelpFormatter,
    )
    findings.add_argument("legacy_args", nargs=argparse.REMAINDER)
    findings.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    memory_cmd = subparsers.add_parser(
        "memory",
        help=argparse.SUPPRESS,
        description="Removed legacy findings memory command.",
        formatter_class=_HelpFormatter,
    )
    memory_cmd.add_argument("legacy_args", nargs=argparse.REMAINDER)
    memory_cmd.add_argument("--json", action="store_true", help=argparse.SUPPRESS)

    skills_cmd = subparsers.add_parser(
        "skills",
        help="Read, inspect, and sync the bundled mco-cli Skill",
        description="Manage the version-matched mco-cli Skill bundled with this npm package.",
        formatter_class=_HelpFormatter,
    )
    skills_sub = skills_cmd.add_subparsers(dest="skills_action", required=True)

    skills_read = skills_sub.add_parser("read", help="Print bundled Skill markdown", formatter_class=_HelpFormatter)
    skills_read.add_argument("--json", action="store_true", help="Print machine-readable JSON output")

    skills_status = skills_sub.add_parser(
        "status",
        help="Show bundled Skill health and drift",
        formatter_class=_HelpFormatter,
    )
    skills_status.add_argument("--repo", default=".", help="Repository root used for project-local skill checks")
    skills_status.add_argument("--json", action="store_true", help="Print machine-readable JSON output")

    skills_sync = skills_sub.add_parser(
        "sync",
        help="Copy bundled Skill into selected calling agents",
        formatter_class=_HelpFormatter,
    )
    skills_sync.add_argument(
        "--agent",
        action="append",
        default=[],
        help="Calling-agent target for Skill installation (repeatable)",
    )
    skills_sync.add_argument("--dry-run", action="store_true", help="Print the exact sync plan without mutation")
    skills_sync.add_argument("--json", action="store_true", help="Print machine-readable JSON output")

    # ── serve subcommand ──────────────────────────────────────
    subparsers.add_parser(
        "serve",
        help="Start MCP server (stdio protocol)",
        description="Start a stdio MCP server exposing MCO tools for AI agents and MCP clients.",
        formatter_class=_HelpFormatter,
    )

    # ── session subcommand ────────────────────────────────────
    session_cmd = subparsers.add_parser(
        "session",
        help="Manage persistent multi-turn sessions with agents",
        description="Start, send, broadcast, cancel, queue, list, stop, resume, and view history of agent sessions.",
        formatter_class=_HelpFormatter,
    )
    session_sub = session_cmd.add_subparsers(dest="session_action", required=True)

    sess_start = session_sub.add_parser("start", help="Start a new session", formatter_class=_HelpFormatter)
    sess_start.add_argument("--provider", required=True, help="Agent provider (e.g. claude, codex, gemini, hermes, pi)")
    sess_start.add_argument("--name", default="", help="Session name (auto-generated if omitted)")
    sess_start.add_argument("--repo", default=".", help="Repository root path")

    sess_send = session_sub.add_parser("send", help="Send a prompt to a session", formatter_class=_HelpFormatter)
    sess_send.add_argument("name", help="Session name")
    sess_send.add_argument("prompt", nargs="?", default="", help="Prompt text")
    sess_send.add_argument("--file", default="", help="Read prompt from file, or '-' for stdin")
    sess_send.add_argument("--repo", default=".", help="Repository root path")
    sess_send.add_argument("--no-wait", action="store_true", help="Return after queuing, don't wait for result")
    sess_send.add_argument("--json", action="store_true", help="JSON output")

    sess_broadcast = session_sub.add_parser("broadcast", help="Send prompt to all active sessions", formatter_class=_HelpFormatter)
    sess_broadcast.add_argument("prompt", help="Prompt text")
    sess_broadcast.add_argument("--repo", default=".", help="Repository root path")
    sess_broadcast.add_argument("--json", action="store_true", help="JSON output")

    sess_list = session_sub.add_parser("list", help="List all sessions", formatter_class=_HelpFormatter)
    sess_list.add_argument("--repo", default=".", help="Repository root path")
    sess_list.add_argument("--json", action="store_true", help="JSON output")

    sess_stop = session_sub.add_parser("stop", help="Stop a session", formatter_class=_HelpFormatter)
    sess_stop.add_argument("name", help="Session name")
    sess_stop.add_argument("--repo", default=".", help="Repository root path")

    sess_history = session_sub.add_parser("history", help="View session conversation history", formatter_class=_HelpFormatter)
    sess_history.add_argument("name", help="Session name")
    sess_history.add_argument("--repo", default=".", help="Repository root path")
    sess_history.add_argument("--json", action="store_true", help="JSON output")

    sess_resume = session_sub.add_parser("resume", help="Resume a stopped/crashed session", formatter_class=_HelpFormatter)
    sess_resume.add_argument("name", help="Session name")
    sess_resume.add_argument("--repo", default=".", help="Repository root path")

    sess_ensure = session_sub.add_parser("ensure", help="Create or return existing session", formatter_class=_HelpFormatter)
    sess_ensure.add_argument("--provider", required=True, help="Agent provider")
    sess_ensure.add_argument("--name", required=True, help="Session name")
    sess_ensure.add_argument("--repo", default=".", help="Repository root path")

    sess_result = session_sub.add_parser("result", help="Retrieve result of a nowait request", formatter_class=_HelpFormatter)
    sess_result.add_argument("name", help="Session name")
    sess_result.add_argument("request_id", type=int, help="Request ID from --no-wait send")
    sess_result.add_argument("--repo", default=".", help="Repository root path")
    sess_result.add_argument("--json", action="store_true", help="JSON output")

    sess_cancel = session_sub.add_parser("cancel", help="Cancel running + queued prompts", formatter_class=_HelpFormatter)
    sess_cancel.add_argument("name", help="Session name")
    sess_cancel.add_argument("--repo", default=".", help="Repository root path")
    sess_cancel.add_argument("--json", action="store_true", help="JSON output")

    sess_queue = session_sub.add_parser("queue", help="Show queue status", formatter_class=_HelpFormatter)
    sess_queue.add_argument("name", help="Session name")
    sess_queue.add_argument("--repo", default=".", help="Repository root path")
    sess_queue.add_argument("--json", action="store_true", help="JSON output")

    return parser


def _resolve_config(args: argparse.Namespace, file_config: Optional[Dict] = None) -> ReviewConfig:
    cfg = ReviewConfig()
    fc = file_config or {}
    fc_policy = fc.get("policy", {}) if isinstance(fc.get("policy"), dict) else {}

    raw_providers = getattr(args, "providers", "")
    providers = _parse_providers(raw_providers) if raw_providers else list(cfg.providers)

    # artifact_base: CLI > config file > hardcoded default
    artifact_base = args.artifact_base if args.artifact_base != cfg.artifact_base else fc.get("artifact_base", cfg.artifact_base)

    provider_timeouts = dict(cfg.policy.provider_timeouts)
    # Merge config file provider_timeouts first, then CLI overrides on top
    if fc_policy.get("provider_timeouts"):
        provider_timeouts.update(fc_policy["provider_timeouts"])
    configured_agents = fc.get("agents", []) if isinstance(fc.get("agents"), list) else []
    for agent in configured_agents:
        if not isinstance(agent, dict):
            continue
        name = str(agent.get("name", "")).strip()
        timeout = agent.get("timeout")
        if name and isinstance(timeout, int) and timeout > 0 and name not in provider_timeouts:
            provider_timeouts[name] = timeout
    provider_timeouts.update(_parse_provider_timeouts(args.provider_timeouts))

    # allow_paths: CLI > config file > hardcoded default
    if args.allow_paths and args.allow_paths != ".":
        allow_paths = _parse_paths(args.allow_paths)
    elif fc_policy.get("allow_paths"):
        allow_paths = fc_policy["allow_paths"] if isinstance(fc_policy["allow_paths"], list) else [fc_policy["allow_paths"]]
    else:
        allow_paths = list(cfg.policy.allow_paths)

    # provider_permissions: merge config file base, then CLI JSON on top
    base_permissions = dict(cfg.policy.provider_permissions)
    if fc_policy.get("provider_permissions") and isinstance(fc_policy["provider_permissions"], dict):
        for k, v in fc_policy["provider_permissions"].items():
            base_permissions[k] = dict(base_permissions.get(k, {}), **v) if isinstance(v, dict) else v
    provider_permissions = _merge_provider_permissions(
        base_permissions,
        _parse_provider_permissions_json(getattr(args, "provider_permissions_json", "")),
    )
    cli_execution_mode = getattr(args, "execution_mode", "")
    if not isinstance(cli_execution_mode, str):
        cli_execution_mode = ""
    execution_mode = cli_execution_mode or fc_policy.get("execution_mode") or (
        "read_only" if getattr(args, "command", "run") == "review" else "write"
    )
    if execution_mode not in EXECUTION_MODES:
        raise ValueError("unknown execution_mode: {}".format(execution_mode))
    for provider in providers:
        profile_permissions = execution_permissions(provider, execution_mode)
        if profile_permissions is None and provider in SUPPORTED_PROVIDERS:
            raise ValueError(
                "{} does not support --execution-mode {}; use --execution-mode yolo or choose another provider".format(
                    provider,
                    execution_mode,
                )
            )
        if profile_permissions is not None:
            profile_permissions.update(provider_permissions.get(provider, {}))
            provider_permissions[provider] = profile_permissions

    base_models = dict(cfg.policy.provider_models)
    if fc_policy.get("provider_models") and isinstance(fc_policy["provider_models"], dict):
        base_models = _merge_provider_models(base_models, _parse_provider_models_json(json.dumps(fc_policy["provider_models"])))
    provider_models_json = getattr(args, "provider_models_json", "")
    if not isinstance(provider_models_json, str):
        provider_models_json = ""
    provider_models = _merge_provider_models(
        base_models,
        _parse_provider_models_json(provider_models_json),
    )

    # provider_context: merge config file base, then CLI JSON on top
    base_context = dict(cfg.policy.provider_context)
    if fc_policy.get("provider_context") and isinstance(fc_policy["provider_context"], dict):
        base_context = _merge_provider_context(base_context, _parse_provider_context_json(json.dumps(fc_policy["provider_context"])))
    provider_context_json = getattr(args, "provider_context_json", "")
    if not isinstance(provider_context_json, str):
        provider_context_json = ""
    provider_context = _merge_provider_context(
        base_context,
        _parse_provider_context_json(provider_context_json),
    )

    max_provider_parallelism = getattr(args, "max_provider_parallelism", None)
    if max_provider_parallelism is None:
        max_provider_parallelism = fc_policy.get("max_provider_parallelism", cfg.policy.max_provider_parallelism)

    # These are resolved by the config merge in main() (CLI > config > hardcoded).
    # Use getattr for safety when called outside main() (e.g. tests).
    enforcement_mode = getattr(args, "enforcement_mode", None) or fc_policy.get("enforcement_mode", cfg.policy.enforcement_mode)
    stall_timeout_seconds = getattr(args, "stall_timeout", None)
    if stall_timeout_seconds is None:
        stall_timeout_seconds = fc_policy.get("stall_timeout_seconds", cfg.policy.stall_timeout_seconds)
    poll_interval_seconds = getattr(args, "poll_interval", None)
    if poll_interval_seconds is None:
        poll_interval_seconds = fc_policy.get("poll_interval_seconds", cfg.policy.poll_interval_seconds)
    review_hard_timeout_seconds = getattr(args, "review_hard_timeout", None)
    if review_hard_timeout_seconds is None:
        review_hard_timeout_seconds = fc_policy.get("review_hard_timeout_seconds", cfg.policy.review_hard_timeout_seconds)
    # Parse perspectives from CLI or config
    perspectives: Dict[str, str] = {}
    perspectives_json = getattr(args, "perspectives_json", "")
    if perspectives_json:
        try:
            parsed = json.loads(perspectives_json)
        except json.JSONDecodeError as exc:
            raise ValueError("Invalid --perspectives-json: {}".format(exc))
        if not isinstance(parsed, dict):
            raise ValueError("--perspectives-json must be a JSON object, got {}".format(type(parsed).__name__))
        for k, v in parsed.items():
            if not isinstance(v, str):
                raise ValueError(
                    "--perspectives-json values must be strings, got {} for key '{}'".format(type(v).__name__, k)
                )
        perspectives = {str(k): str(v) for k, v in parsed.items()}
    if not perspectives:
        perspectives = fc_policy.get("perspectives", {})

    divide = str(getattr(args, "divide", "") or fc_policy.get("divide", "") or "").strip()
    if divide and divide not in ("files", "dimensions"):
        raise ValueError("--divide must be one of: files, dimensions")

    policy = ReviewPolicy(
        timeout_seconds=cfg.policy.timeout_seconds,
        stall_timeout_seconds=stall_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        review_hard_timeout_seconds=review_hard_timeout_seconds,
        max_provider_parallelism=max_provider_parallelism,
        provider_timeouts=provider_timeouts,
        allow_paths=allow_paths,
        provider_permissions=provider_permissions,
        enforcement_mode=enforcement_mode,
        perspectives=perspectives,
        provider_models=provider_models,
        provider_context=provider_context,
        chain=getattr(args, "chain", False) or fc_policy.get("chain", False),
        debate=getattr(args, "debate", False) or fc_policy.get("debate", False),
        divide=divide,
        execution_mode=execution_mode,
    )
    return ReviewConfig(providers=providers, artifact_base=artifact_base, policy=policy)


def _removed_surface_error(args: argparse.Namespace, message: str) -> int:
    if getattr(args, "json", False):
        payload = _error_envelope("removed_surface", message)
        print(json.dumps(payload, ensure_ascii=True))
    else:
        print(message, file=sys.stderr)
    return 2


def _package_root() -> Path:
    return Path(__file__).resolve().parent.parent


def _handle_skills(args: argparse.Namespace) -> int:
    package_root = _package_root()
    wants_json = bool(getattr(args, "json", False))

    if args.skills_action == "read":
        skill_path = package_root / "skills" / "mco-cli" / "SKILL.md"
        try:
            content = read_bundled_skill(package_root)
        except FileNotFoundError as exc:
            message = str(exc)
            if wants_json:
                print(json.dumps(_error_envelope("config_error", message), ensure_ascii=True))
            else:
                print(message, file=sys.stderr)
            return 2
        if wants_json:
            print(json.dumps({
                "ok": True,
                "skill": "mco-cli",
                "path": str(skill_path),
                "content": content,
            }, ensure_ascii=True))
        else:
            print(content, end="" if content.endswith("\n") else "\n")
        return 0

    if args.skills_action == "status":
        repo_root = Path(getattr(args, "repo", ".")).resolve()
        payload = {"ok": True, **skill_status(package_root, cwd=repo_root)}
        if wants_json:
            print(json.dumps(payload, ensure_ascii=True))
        else:
            health = payload["skill_health"]
            print("Skill status: {}".format(health.get("status")))
            print("Reference: {}".format((health.get("reference") or {}).get("path", "unknown")))
        return 0

    if args.skills_action == "sync":
        agents = list(getattr(args, "agent", []) or [])
        if not agents:
            message = "Choose one or more calling agents for the mco-cli Skill."
            if wants_json:
                print(json.dumps(_error_envelope("agent_selection_required", message), ensure_ascii=True))
            else:
                print(message, file=sys.stderr)
            return 2
        try:
            result = sync_bundled_skill(
                package_root,
                agents,
                dry_run=bool(getattr(args, "dry_run", False)),
            )
        except ValueError as exc:
            message = str(exc)
            subtype = "agent_selection_required" if "agent_selection_required" in message else "invalid_config"
            if "unknown skill agent" in message or "invalid skill agent" in message:
                subtype = "invalid_config"
            if wants_json:
                print(json.dumps(_error_envelope(subtype, message), ensure_ascii=True))
            else:
                print(message, file=sys.stderr)
            return 2
        payload = {"ok": result.get("status") != "failed", **result}
        if wants_json:
            print(json.dumps(payload, ensure_ascii=True))
        else:
            print("Skill sync {} for agents: {}".format(result.get("status"), ", ".join(result.get("agents", []))))
            if result.get("dry_run"):
                print("Command: {}".format(" ".join(result.get("argv", []))))
        return 0 if payload["ok"] else 1

    print("Unknown skills action.", file=sys.stderr)
    return 2


def _handle_session(args: argparse.Namespace) -> int:
    """Handle the session subcommand."""
    from pathlib import Path
    from .session.manager import start_session, stop_session, list_sessions, resume_session, ensure_session
    from .session.client import send_prompt, send_prompt_nowait, broadcast_prompt, cancel_session as client_cancel, queue_status, get_result
    from .session.state import load_history

    repo_root = str(Path(args.repo).resolve())

    if args.session_action == "start":
        provider = args.provider.strip()
        if provider not in SUPPORTED_PROVIDERS:
            print("Unsupported provider: {}. Supported: {}".format(
                provider, ", ".join(SUPPORTED_PROVIDERS)), file=sys.stderr)
            return 2
        name = args.name.strip() if args.name else None
        try:
            state = start_session(provider, repo_root=repo_root, name=name)
            print("Session '{}' started (provider={}, pid={})".format(
                state.name, state.provider, state.pid))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    if args.session_action == "send":
        prompt = args.prompt or ""
        file_path = getattr(args, "file", "") or ""
        if file_path:
            if file_path == "-":
                prompt = sys.stdin.read()
            else:
                p = Path(file_path)
                if not p.exists():
                    print("File not found: {}".format(file_path), file=sys.stderr)
                    return 2
                prompt = p.read_text(encoding="utf-8")
        if not prompt and not sys.stdin.isatty():
            prompt = sys.stdin.read()
        if not prompt:
            print("Prompt is required (positional, --file, or piped stdin).", file=sys.stderr)
            return 2
        if getattr(args, "no_wait", False):
            result = send_prompt_nowait(repo_root, args.name, prompt)
            if getattr(args, "json", False):
                print(json.dumps(result, ensure_ascii=True))
            else:
                if result.get("status") == "queued":
                    print("Queued as request #{} (position {})".format(
                        result.get("request_id", "?"), result.get("position", "?")))
                else:
                    print("Error: {}".format(result.get("message", "unknown")), file=sys.stderr)
                    return 2
            return 0
        try:
            result = send_prompt(repo_root, args.name, prompt)
        except KeyboardInterrupt:
            print("\nCancelling...", file=sys.stderr)
            client_cancel(repo_root, args.name)
            return 130
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=True))
        else:
            if result.get("status") == "ok":
                print(result.get("response", ""))
            else:
                print("Error: {}".format(result.get("message", "unknown error")), file=sys.stderr)
                return 2
        return 0

    if args.session_action == "broadcast":
        results = broadcast_prompt(repo_root, args.prompt)
        if not results:
            print("No active sessions.", file=sys.stderr)
            return 2
        if getattr(args, "json", False):
            print(json.dumps(results, ensure_ascii=True))
        else:
            for r in results:
                print("── {} ({}) ──".format(r["session_name"], r["provider"]))
                if r["status"] == "ok":
                    print(r.get("response", ""))
                else:
                    print("Error: {}".format(r.get("message", "")))
                print()
        # Exit 2 if ALL results failed
        if all(r.get("status") != "ok" for r in results):
            return 2
        return 0

    if args.session_action == "list":
        sessions = list_sessions(repo_root)
        if getattr(args, "json", False):
            print(json.dumps(sessions, ensure_ascii=True))
        else:
            if not sessions:
                print("No sessions found.")
            else:
                for s in sessions:
                    print("{name:20s} {provider:10s} {status:10s} turns={turn_count} pid={pid}".format(**s))
        return 0

    if args.session_action == "stop":
        ok = stop_session(repo_root, args.name)
        if ok:
            print("Session '{}' stopped.".format(args.name))
        else:
            print("Failed to stop session '{}'.".format(args.name), file=sys.stderr)
            return 2
        return 0

    if args.session_action == "history":
        entries = load_history(repo_root, args.name)
        if getattr(args, "json", False):
            from dataclasses import asdict
            print(json.dumps([asdict(e) for e in entries], ensure_ascii=True))
        else:
            if not entries:
                print("No history for session '{}'.".format(args.name))
            else:
                for e in entries:
                    label = "User" if e.role == "user" else "Assistant"
                    print("[{}] {}: {}".format(e.timestamp[:19], label, e.content[:200]))
        return 0

    if args.session_action == "resume":
        try:
            state = resume_session(repo_root, args.name)
            print("Session '{}' resumed (pid={})".format(state.name, state.pid))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    if args.session_action == "cancel":
        result = client_cancel(repo_root, args.name)
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=True))
        else:
            if result.get("status") == "ok":
                cancelled = result.get("cancelled", 0)
                if cancelled:
                    print("Cancelled {} request(s) in session '{}'.".format(cancelled, args.name))
                else:
                    print("Nothing running in session '{}'.".format(args.name))
            else:
                print("Error: {}".format(result.get("message", "unknown error")), file=sys.stderr)
                return 2
        return 0

    if args.session_action == "result":
        result = get_result(repo_root, args.name, args.request_id)
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=True))
        else:
            status = result.get("status", "error")
            if status == "ok":
                print(result.get("response", ""))
            elif status == "pending":
                print("Request #{} is still running.".format(args.request_id))
                return 1
            else:
                print("Error: {}".format(result.get("message", "unknown error")), file=sys.stderr)
                return 2
        return 0

    if args.session_action == "queue":
        result = queue_status(repo_root, args.name)
        if getattr(args, "json", False):
            print(json.dumps(result, ensure_ascii=True))
        else:
            if result.get("status") == "ok":
                running = result.get("running")
                queued = result.get("queued", 0)
                if running:
                    print("Running: request #{}".format(running))
                else:
                    print("Running: idle")
                print("Queued: {}".format(queued))
            else:
                print("Error: {}".format(result.get("message", "unknown error")), file=sys.stderr)
                return 2
        return 0

    if args.session_action == "ensure":
        try:
            state = ensure_session(args.provider, repo_root=repo_root, name=args.name)
            print("Session '{}' ready (provider={}, pid={})".format(
                state.name, state.provider, state.pid))
        except ValueError as exc:
            print(str(exc), file=sys.stderr)
            return 2
        return 0

    print("Unknown session action.", file=sys.stderr)
    return 2


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    # If streaming is requested, suppress argparse stderr and emit a machine-readable error.
    _raw_argv = argv if argv is not None else sys.argv[1:]
    _wants_stream = "--stream" in _raw_argv and any(mode in _raw_argv for mode in ("jsonl", "live"))
    _wants_json = "--json" in _raw_argv
    _parse_error_msg = ""
    if _wants_stream or _wants_json:
        def _capture_parse_error(message: str) -> None:
            nonlocal _parse_error_msg
            _parse_error_msg = message
        if isinstance(parser, _StreamSafeParser):
            parser.set_stream_error_handler(_capture_parse_error)
    try:
        args = parser.parse_args(argv)
    except SystemExit as exc:
        if exc.code != 0:
            message = _parse_error_msg or "Invalid arguments. Run 'mco review --help' for usage."
            if _wants_stream:
                print(json.dumps(_stream_error_event("parse_error", message), ensure_ascii=True), flush=True)
            elif _wants_json:
                print(json.dumps(_error_envelope("parse_error", message), ensure_ascii=True))
        return int(exc.code) if isinstance(exc.code, int) else 2
    if args.command == "version":
        print(__version__)
        return 0

    if args.command == "doctor":
        providers_str = getattr(args, "providers", ",".join(DEFAULT_DOCTOR_PROVIDERS))
        requested_providers = _parse_providers(providers_str)
        invalid_providers = [item for item in requested_providers if item not in SUPPORTED_PROVIDERS]
        if invalid_providers:
            message = "Unknown providers: {}".format(", ".join(invalid_providers))
            if args.json:
                print(json.dumps(_error_envelope("invalid_providers", message), ensure_ascii=True))
            else:
                print(message, file=sys.stderr)
            return 2
        providers = requested_providers
        repo_root = Path(getattr(args, "repo", ".")).resolve()
        skill_health = None
        skill_drift = None
        if getattr(args, "skill_health", False):
            skill_health, skill_drift = check_skill_health(
                enabled=True,
                package_root=Path(__file__).resolve().parent.parent,
                cwd=repo_root,
            )
        payload = _doctor_payload(
            providers,
            _doctor_provider_presence(providers),
            skill_health=skill_health,
            skill_drift=skill_drift,
        )
        if args.json:
            print(json.dumps(payload, ensure_ascii=True))
        else:
            print(_render_doctor_report(payload))
        return 0

    if args.command == "agent":
        repo_root = str(Path(getattr(args, "repo", ".")).resolve())
        cli_agents = _normalize_cli_agent_pairs(getattr(args, "agent", []))
        if args.agent_action == "list":
            payload = _load_available_agents(repo_root, cli_agents=cli_agents)
            if getattr(args, "json", False):
                print(json.dumps(payload, ensure_ascii=True))
            else:
                for item in payload:
                    risk = item.get("risk", {})
                    risk_level = risk.get("level") if isinstance(risk, dict) else ""
                    print(
                        "{name:20s} {transport:5s} {source:7s} {risk:15s} {detail}".format(
                            name=str(item.get("name", "")),
                            transport=str(item.get("transport", "")),
                            source=str(item.get("source", "")),
                            risk=str(risk_level or ""),
                            detail=str(item.get("model") or item.get("command") or ""),
                        ).rstrip()
                    )
            return 0

        if args.agent_action == "check":
            agent_name = args.name.strip() if isinstance(args.name, str) else ""
            if not agent_name:
                print("Agent name is required.", file=sys.stderr)
                return 2
            payload = _check_agent(repo_root, agent_name, cli_agents=cli_agents)
            if getattr(args, "json", False):
                print(json.dumps(payload, ensure_ascii=True))
            else:
                risk = payload.get("risk", {})
                risk_level = risk.get("level") if isinstance(risk, dict) else "unknown"
                print(
                    "Agent {name}: ready={ready} detected={detected} transport={transport} reason={reason} risk={risk}".format(
                        name=payload.get("name"),
                        ready=payload.get("ready"),
                        detected=payload.get("detected"),
                        transport=payload.get("transport"),
                        reason=payload.get("reason"),
                        risk=risk_level,
                    )
                )
            return 0

        if args.agent_action == "models":
            from .models import discover_models as _discover_models

            providers_str = getattr(args, "providers", "codex,hermes,pi")
            providers = [p.strip() for p in providers_str.split(",") if p.strip()]
            results: Dict[str, object] = {}
            for provider in providers:
                result = _discover_models(provider)
                results[provider] = result
                if not getattr(args, "json", False):
                    status = "OK" if result.get("ok") else "FAIL"
                    error = result.get("error", "")
                    models = result.get("models", [])
                    count = len(models) if isinstance(models, list) else 0
                    print(f"{provider}: {status} ({count} models){' — ' + error if error else ''}")
                    if isinstance(models, list):
                        for m in models[:5]:
                            print(f"  - {m.get('id', '?')}")
                        if len(models) > 5:
                            print(f"  ... and {len(models) - 5} more")
            if getattr(args, "json", False):
                print(json.dumps(results, ensure_ascii=True))
            return 0

    if args.command == "findings":
        return _removed_surface_error(
            args,
            "The findings command was removed. Use mco run/review with raw text, --json, --stream jsonl, "
            "or --result-mode artifact.",
        )

    if args.command == "memory":
        return _removed_surface_error(
            args,
            "The memory command was removed with the findings memory layer. Persist raw answers with "
            "--result-mode artifact or pass them through --chain, --debate, or --synthesize.",
        )

    if args.command == "skills":
        return _handle_skills(args)

    if args.command == "session":
        return _handle_session(args)

    if args.command == "serve":
        try:
            from .mcp_server import ensure_mcp_installed, run_server
            ensure_mcp_installed()
            import asyncio as _asyncio
            _asyncio.run(run_server())
        except ImportError:
            print(
                "mco serve requires the mcp package. Install with: python3 -m pip install mcp",
                file=sys.stderr,
            )
            return 2
        return 0

    if args.command not in ("run", "review"):
        parser.error("unsupported command")
        return 2

    # Load config files and apply as defaults for args the user didn't set
    from .config import load_config_files
    repo_root_for_config = str(Path(getattr(args, "repo", ".")).resolve())
    file_config = load_config_files(repo_root_for_config)

    policy_cfg = file_config.get("policy", {}) if isinstance(file_config.get("policy"), dict) else {}

    providers_was_explicit = hasattr(args, "providers")
    # Group 1: top-level flags
    _TOP_LEVEL_DEFAULTS = {
        "providers": ",".join(DEFAULT_CONFIG.providers),
        "transport": "shim",
        "quiet": False,
        "memory": False,
    }
    for attr, hardcoded_default in _TOP_LEVEL_DEFAULTS.items():
        if not hasattr(args, attr):
            if attr == "providers" and "providers" in file_config:
                setattr(args, attr, ",".join(file_config["providers"]))
            elif attr in file_config:
                setattr(args, attr, file_config[attr])
            else:
                setattr(args, attr, hardcoded_default)

    # Group 2: policy flags (config key names differ from args attr names)
    _POLICY_DEFAULTS = {
        "stall_timeout": ("stall_timeout_seconds", DEFAULT_POLICY.stall_timeout_seconds),
        "max_provider_parallelism": ("max_provider_parallelism", DEFAULT_POLICY.max_provider_parallelism),
        "poll_interval": ("poll_interval_seconds", DEFAULT_POLICY.poll_interval_seconds),
        "review_hard_timeout": ("review_hard_timeout_seconds", DEFAULT_POLICY.review_hard_timeout_seconds),
        "enforcement_mode": ("enforcement_mode", DEFAULT_POLICY.enforcement_mode),
    }
    for attr, (config_key, hardcoded_default) in _POLICY_DEFAULTS.items():
        if not hasattr(args, attr):
            if config_key in policy_cfg:
                setattr(args, attr, policy_cfg[config_key])
            else:
                setattr(args, attr, hardcoded_default)

    # Build stream emitter FIRST so mutual-exclusion/config errors can still stream.
    requested_stream_mode = getattr(args, "stream", None)
    stream_callback, stream_mode, stream_renderer = _build_stream_callback(
        requested_stream_mode,
        chain_mode=bool(getattr(args, "chain", False)),
    )

    def _stream_error_exit(code: str, message: str, *, task_failure: bool = False) -> int:
        """Emit a stable machine error when requested, otherwise use stderr."""
        if stream_callback:
            event = _stream_error_event(code, message)
            if task_failure:
                event.update({"stage": "run", "status": "failed", "exit_code": 2, "artifact_root": None})
            stream_callback(event)
        elif getattr(args, "json", False):
            payload = _error_envelope(code, message)
            if task_failure:
                payload.update({"stage": "run", "status": "failed", "exit_code": 2, "outputs": [], "artifact_root": None})
            print(json.dumps(payload, ensure_ascii=True))
        else:
            print(message, file=sys.stderr)
        return 2

    format_value = str(getattr(args, "format", "") or "").strip()
    if format_value:
        return _stream_error_exit(
            "removed_surface",
            "--format {} was removed with the findings contract. Use raw text, --json, --stream jsonl, "
            "or --result-mode artifact.".format(format_value),
        )
    if getattr(args, "strict_contract", False):
        return _stream_error_exit(
            "removed_surface",
            "--strict-contract was removed with the findings contract. Provider answers are now opaque raw text.",
        )
    if getattr(args, "memory", False) or str(getattr(args, "space", "") or "").strip():
        return _stream_error_exit(
            "removed_surface",
            "--memory/--space were removed with the findings memory layer. Persist raw answers with --result-mode artifact.",
        )
    if getattr(args, "diff", False) or getattr(args, "staged", False) or getattr(args, "unstaged", False) or str(getattr(args, "diff_base", "") or "").strip():
        return _stream_error_exit(
            "removed_surface",
            "diff review flags were removed. Put the desired scope in --target-paths or the prompt.",
        )
    if str(getattr(args, "divide", "") or "").strip() or str(getattr(args, "perspectives_json", "") or "").strip() or policy_cfg.get("divide") or policy_cfg.get("perspectives"):
        return _stream_error_exit(
            "removed_surface",
            "--divide and --perspectives-json were removed with the semantic review layer. "
            "Use explicit --agent invocations with partitioned --target-paths and raw prompts.",
        )

    configured_agents = file_config.get("agents", []) if isinstance(file_config.get("agents"), list) else []

    # Build extra_agents from --custom-agent flag.
    extra_agents = _normalize_cli_agent_pairs(getattr(args, "custom_agent", None))
    if not extra_agents:
        extra_agents = None

    try:
        cfg = _resolve_config(args, file_config=file_config)
    except ValueError as exc:
        return _stream_error_exit("config_error", "Configuration error: {}".format(exc))
    if cfg.policy.chain and cfg.policy.debate:
        return _stream_error_exit("invalid_config", "--debate and --chain are mutually exclusive")
    repo_root = str(Path(args.repo).resolve())

    # Valid providers = built-in providers + custom agent names
    valid_providers = set(SUPPORTED_PROVIDERS)
    valid_providers |= {
        str(item.get("name", "")).strip()
        for item in configured_agents
        if isinstance(item, dict) and str(item.get("name", "")).strip()
    }
    if extra_agents:
        valid_providers |= set(extra_agents.keys())

    invalid_providers = [item for item in cfg.providers if item not in valid_providers]
    if invalid_providers:
        return _stream_error_exit(
            "invalid_providers",
            "Unknown providers: {}".format(", ".join(invalid_providers)),
        )
    providers = list(cfg.providers)

    synth_provider = args.synth_provider.strip() if isinstance(args.synth_provider, str) else ""
    synthesize = bool(args.synthesize or synth_provider)
    if synth_provider and synth_provider not in providers:
        return _stream_error_exit("invalid_config", "--synth-provider must be one of selected providers")

    try:
        prompt = _resolve_prompt(
            args,
            default_prompt=(
                "Review the selected scope and report any concerns in natural language."
                if args.command == "review"
                else ""
            ),
        )
    except ValueError as exc:
        return _stream_error_exit("input_error", str(exc))
    raw_invocation_agents = list(getattr(args, "invocation_agents", []) or [])
    use_invocation_runtime = not getattr(args, "dry_run", False)
    if use_invocation_runtime:
        def _invocation_error(code: str, message: str) -> int:
            return _stream_error_exit(code, message, task_failure=True)

        if providers_was_explicit:
            if raw_invocation_agents:
                return _invocation_error("invalid_config", "--agent and --providers are mutually exclusive")
        try:
            execution_scope = validate_execution_scope(
                repo_root,
                _parse_paths(args.target_paths),
                cfg.policy.allow_paths,
            )
            invocations = (
                parse_invocations(raw_invocation_agents, execution_scope)
                if raw_invocation_agents
                else default_invocations(providers, execution_scope, cfg.policy.provider_models)
            )
        except ValueError as exc:
            return _invocation_error("input_error", str(exc))
        if not invocations:
            return _invocation_error(
                "provider_selection_required",
                "No providers selected. Ask the user which agents MCO should use, then pass the choice with "
                "--providers. Available: {}".format(SUPPORTED_PROVIDER_LIST),
            )
        adapter_map = _doctor_adapter_registry(
            transport=getattr(args, "transport", "shim"),
            extra_agents=extra_agents,
            configured_agents=configured_agents,
        )
        unknown = [item.provider for item in invocations if item.provider not in adapter_map]
        if unknown:
            return _invocation_error("invalid_providers", "Unknown providers: {}".format(", ".join(dict.fromkeys(unknown))))
        for invocation in invocations:
            preview = provider_policy_preview(invocation.provider, adapter_map[invocation.provider], cfg.policy)
            if preview["would_fail_strict"]:
                if getattr(args, "transport", "shim") == "acp" and cfg.policy.enforcement_mode == "strict":
                    applied_permissions = preview.get("applied_permissions", {})
                    risk = effective_provider_risk(
                        invocation.provider,
                        applied_permissions if isinstance(applied_permissions, dict) else {},
                        transport="acp",
                    )
                    if risk["level"] == "unknown":
                        return _invocation_error(
                            "invalid_config",
                            "risk_classification_unknown: strict ACP execution requires an explicit supported "
                            "permission override for provider(s): {}".format(invocation.provider),
                        )
                return _invocation_error(
                    "config_error",
                    "invocation '{}': {}".format(invocation.invocation_id, preview["failure_reason"]),
                )
            discovery = discover_models(invocation.provider)
            models = discovery.get("models", []) if isinstance(discovery, dict) else []
            known_model_ids = {
                str(item.get("id", ""))
                for item in models
                if isinstance(item, dict) and str(item.get("id", ""))
            }
            if discovery.get("ok") and known_model_ids and invocation.model != "default" and invocation.model not in known_model_ids:
                return _invocation_error(
                    "input_error",
                    "unknown model '{}' for provider '{}'".format(invocation.model, invocation.provider),
                )
        cancel_event = threading.Event()
        previous_sigint = signal.getsignal(signal.SIGINT)

        def _cancel_invocations(_signum: int, _frame: object) -> None:
            cancel_event.set()

        signal.signal(signal.SIGINT, _cancel_invocations)
        invocation_result_mode = getattr(args, "result_mode", "stdout")
        if getattr(args, "save_artifacts", False) and invocation_result_mode == "stdout":
            invocation_result_mode = "both"
        persist_invocation_artifacts = invocation_result_mode in ("artifact", "both")
        output_to_stdout = invocation_result_mode in ("stdout", "both")
        event_callback = None
        if not args.json and (stream_mode == "jsonl" or output_to_stdout):
            event_lock = threading.Lock()
            if stream_mode == "jsonl":
                def _emit_jsonl(event: Dict[str, object]) -> None:
                    with event_lock:
                        event_payload = dict(event)
                        diagnostic = event_payload.pop("stderr", "")
                        print(json.dumps(event_payload, ensure_ascii=True), flush=True)
                        if isinstance(diagnostic, str) and diagnostic:
                            print(diagnostic, file=sys.stderr, end="" if diagnostic.endswith("\n") else "\n", flush=True)

                event_callback = _emit_jsonl
            else:
                source_labels = {
                    item.invocation_id: "{} ({}:{})".format(item.invocation_id, item.provider, item.model)
                    for item in invocations
                }
                active_source = [None]

                def _emit_text(event: Dict[str, object]) -> None:
                    with event_lock:
                        if event.get("type") == "invocation_finished":
                            diagnostic = event.get("stderr", "")
                            if isinstance(diagnostic, str) and diagnostic:
                                print(diagnostic, file=sys.stderr, end="" if diagnostic.endswith("\n") else "\n", flush=True)
                            if event.get("status") != "success" and event.get("error"):
                                print(
                                    "[mco] {} {}: {}".format(
                                        event.get("invocation_id", "invocation"),
                                        event.get("status", "failed"),
                                        event.get("error"),
                                    ),
                                    file=sys.stderr,
                                    flush=True,
                                )
                            return
                        if event.get("type") != "output_delta":
                            return
                        source = str(event.get("invocation_id", ""))
                        delta = event.get("delta", "")
                        if not isinstance(delta, str):
                            return
                        if len(invocations) > 1 and active_source[0] != source:
                            prefix = "" if active_source[0] is None else "\n"
                            print("{}── {} ──\n".format(prefix, source_labels.get(source, source)), end="", flush=True)
                            active_source[0] = source
                        print(delta, end="", flush=True)

                event_callback = _emit_text
        try:
            payload = run_invocation_workflow(
                invocations=invocations,
                adapters=adapter_map,
                repo_root=repo_root,
                prompt=prompt,
                timeout_seconds=cfg.policy.stall_timeout_seconds,
                provider_permissions=cfg.policy.provider_permissions,
                allow_paths=cfg.policy.allow_paths,
                global_timeout_seconds=(
                    cfg.policy.review_hard_timeout_seconds
                    if cfg.policy.review_hard_timeout_seconds > 0
                    else None
                ),
                cancel_event=cancel_event,
                event_callback=event_callback,
                artifact_base=str(Path(cfg.artifact_base).resolve()),
                task_id=args.task_id or "",
                persist_artifacts=persist_invocation_artifacts,
                chain=cfg.policy.chain,
                debate=cfg.policy.debate,
                synthesize=synthesize,
                synthesis_provider=synth_provider or None,
            )
        except ValueError as exc:
            return _invocation_error("input_error", str(exc))
        finally:
            signal.signal(signal.SIGINT, previous_sigint)
            if stream_renderer is not None:
                stream_renderer.close()
        if args.json:
            json_payload = dict(payload)
            json_payload["outputs"] = [
                {key: value for key, value in item.items() if key != "stderr"}
                for item in payload["outputs"]
            ]
            print(json.dumps(json_payload, ensure_ascii=True))
        return int(payload["exit_code"])
    if not providers:
        return _stream_error_exit(
            "provider_selection_required",
            "No providers selected. Ask the user which agents MCO should use, then pass the choice with "
            "--providers. Available: {}".format(SUPPORTED_PROVIDER_LIST),
        )
    req = ExecutionPreviewRequest(
        repo_root=repo_root,
        prompt=prompt,
        providers=providers,  # type: ignore[arg-type]
        artifact_base=str(Path(cfg.artifact_base).resolve()),
        policy=cfg.policy,
        task_id=args.task_id or None,
        target_paths=[item.strip() for item in args.target_paths.split(",") if item.strip()],
    )
    review_mode = args.command == "review"
    effective_result_mode = args.result_mode
    if args.save_artifacts and effective_result_mode == "stdout":
        effective_result_mode = "both"
    write_artifacts = effective_result_mode in ("artifact", "both")
    transport = getattr(args, "transport", "shim")
    adapters = _doctor_adapter_registry(transport=transport, extra_agents=extra_agents, configured_agents=configured_agents) if (transport != "shim" or extra_agents or configured_agents) else None
    if getattr(args, "dry_run", False):
        preview_adapters = adapters or _doctor_adapter_registry()
        try:
            payload = _build_dry_run_payload(
                args,
                req,
                providers=providers,
                adapters=preview_adapters,
                review_mode=review_mode,
                result_mode=effective_result_mode,
                write_artifacts=write_artifacts,
                transport=transport,
                synthesize=synthesize,
                synth_provider=synth_provider,
            )
        except (KeyError, TypeError, ValueError) as exc:
            if stream_renderer is not None:
                stream_renderer.close()
            return _stream_error_exit(
                "runtime_error",
                "Dry-run command preview failed: {}".format(exc),
            )
        if stream_renderer is not None:
            stream_renderer.close()
        if args.json:
            print(json.dumps(payload, ensure_ascii=True))
        else:
            print(_render_dry_run_report(payload))
        return 0
    if stream_renderer is not None:
        stream_renderer.close()
    return _stream_error_exit("runtime_error", "Execution did not enter the invocation-native runtime")


if __name__ == "__main__":
    raise SystemExit(main())
