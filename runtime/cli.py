from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Dict, List, Mapping

from .adapters import adapter_registry
from .config import ReviewConfig, ReviewPolicy
from .contracts import ProviderPresence
from .formatters import format_markdown_pr, format_sarif
from .review_engine import ReviewRequest, run_review

SUPPORTED_PROVIDERS = ("claude", "codex", "gemini", "opencode", "qwen")
DEFAULT_CONFIG = ReviewConfig()
DEFAULT_POLICY = DEFAULT_CONFIG.policy


class _HelpFormatter(argparse.RawTextHelpFormatter):
    def _get_help_string(self, action: argparse.Action) -> str:
        help_text = action.help or ""
        default = action.default
        if default not in (None, "", False, argparse.SUPPRESS) and "%(default)" not in help_text:
            help_text += " (default: %(default)s)"
        return help_text


TOP_LEVEL_DESCRIPTION = (
    "MCO - Orchestrate AI Coding Agents. Any Prompt. Any Agent. Any IDE.\n"
    "Use `run` for general tasks and `review` for structured findings."
)

TOP_LEVEL_EPILOG = (
    "Examples:\n"
    "  mco doctor --json\n"
    "  mco run --repo . --prompt \"Summarize this repo.\" --providers claude,codex\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --providers claude,codex,qwen --json\n\n"
    "Use `mco doctor -h`, `mco run -h`, or `mco review -h` for full command options."
)

RUN_EPILOG = (
    "Examples:\n"
    "  mco run --repo . --prompt \"Summarize the architecture.\" --providers claude,codex\n"
    "  mco run --repo . --prompt \"List risky files.\" --providers claude,codex,qwen --json\n"
    "  mco run --repo . --prompt \"Compare provider outputs.\" --providers claude,codex,qwen --synthesize\n"
    "  mco run --repo . --prompt \"Analyze runtime.\" --save-artifacts --json\n\n"
    "Exit codes:\n"
    "  0 = success\n"
    "  2 = input/config/runtime failure"
)

REVIEW_EPILOG = (
    "Examples:\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --providers claude,codex\n"
    "  mco review --repo . --prompt \"Review for security issues.\" --providers claude,codex,qwen --json\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --providers claude,codex,qwen --synthesize --synth-provider claude\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --providers claude,codex --format markdown-pr\n"
    "  mco review --repo . --prompt \"Review for bugs.\" --providers claude,codex --format sarif\n"
    "  mco review --repo . --prompt \"Review runtime/ only.\" --target-paths runtime --strict-contract\n\n"
    "Exit codes:\n"
    "  0 = success\n"
    "  2 = FAIL / input / config / runtime failure\n"
    "  3 = INCONCLUSIVE (review mode only)"
)

DOCTOR_EPILOG = (
    "Examples:\n"
    "  mco doctor\n"
    "  mco doctor --providers claude,codex --json\n\n"
    "Exit codes:\n"
    "  0 = command completed (read overall_ok in output)\n"
    "  2 = invalid input"
)

FINDINGS_EPILOG = (
    "Examples:\n"
    "  mco findings list --repo .\n"
    "  mco findings list --repo . --status open --json\n"
    "  mco findings confirm sha256:abc123 --status accepted --repo .\n\n"
    "Exit codes:\n"
    "  0 = success\n"
    "  2 = input/config/runtime failure"
)

MEMORY_EPILOG = (
    "Examples:\n"
    "  mco memory agent-stats --repo .\n"
    "  mco memory agent-stats --repo . --space my-repo --json\n"
    "  mco memory priors --repo . --category security\n"
    "  mco memory status --repo .\n\n"
    "Exit codes:\n"
    "  0 = success\n"
    "  2 = input/config/runtime failure"
)


def _doctor_adapter_registry() -> Mapping[str, object]:
    return adapter_registry()


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


def _doctor_payload(providers: List[str], presence_map: Dict[str, ProviderPresence]) -> Dict[str, object]:
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
        }
    return {
        "command": "doctor",
        "overall_ok": ready_count == len(providers),
        "ready_count": ready_count,
        "provider_count": len(providers),
        "providers": provider_payload,
    }


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
    return "\n".join(lines)


def _finding_location_from_dict(finding: Dict[str, object]) -> str:
    evidence = finding.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    file_path = str(evidence.get("file", ""))
    line = evidence.get("line")
    if file_path and isinstance(line, int):
        return f"{file_path}:{line}"
    return file_path


def _render_user_readable_report(
    command: str,
    result_mode: str,
    providers: List[str],
    payload: Dict[str, object],
    provider_results: Dict[str, Dict[str, object]],
    findings: Optional[List[Dict[str, object]]] = None,
) -> str:
    lines: List[str] = []
    title = "Review" if command == "review" else "Run"
    lines.append(f"{title} Result")
    lines.append("")
    lines.append("Execution Summary")
    lines.append(f"- task_id: {payload['task_id']}")
    lines.append(f"- decision: {payload['decision']}")
    lines.append(f"- terminal_state: {payload['terminal_state']}")
    lines.append(f"- providers: {', '.join(providers)}")
    lines.append(
        f"- provider_success/failure: {payload['provider_success_count']}/{payload['provider_failure_count']}"
    )
    lines.append(f"- findings_count: {payload['findings_count']}")
    lines.append(f"- parse_success/failure: {payload['parse_success_count']}/{payload['parse_failure_count']}")
    lines.append(f"- schema_valid_count: {payload['schema_valid_count']}")
    token_usage_summary = payload.get("token_usage_summary")
    if isinstance(token_usage_summary, dict):
        totals = token_usage_summary.get("totals", {})
        if isinstance(totals, dict):
            lines.append(
                "- token_usage: "
                f"completeness={token_usage_summary.get('completeness')}, "
                f"providers_with_usage={token_usage_summary.get('providers_with_usage')}/{token_usage_summary.get('provider_count')}, "
                f"prompt={totals.get('prompt_tokens', 0)}, completion={totals.get('completion_tokens', 0)}, total={totals.get('total_tokens', 0)}"
            )
    synthesis = payload.get("synthesis")
    if isinstance(synthesis, dict):
        lines.append(
            "- synthesis: "
            f"provider={synthesis.get('provider')}, success={synthesis.get('success')}, reason={synthesis.get('reason')}"
        )
    lines.append("")
    lines.append("Provider Details")
    for provider in sorted(provider_results.keys()):
        details = provider_results.get(provider, {})
        success = bool(details.get("success"))
        attempts = details.get("attempts")
        final_error = details.get("final_error")
        parse_reason = details.get("parse_reason")
        findings_count = details.get("findings_count")
        lines.append(
            f"- {provider}: success={success}, attempts={attempts}, final_error={final_error}, parse_reason={parse_reason}, findings={findings_count}"
        )
        output_text = str(details.get("final_text", "")) or str(details.get("output_text", ""))
        if output_text:
            lines.append("  output:")
            for raw_line in output_text.splitlines():
                lines.append(f"    {raw_line}")
        token_usage = details.get("token_usage")
        if isinstance(token_usage, dict):
            lines.append(
                "  token_usage: "
                f"completeness={details.get('token_usage_completeness')}, "
                f"prompt={token_usage.get('prompt_tokens', '-')}, "
                f"completion={token_usage.get('completion_tokens', '-')}, "
                f"total={token_usage.get('total_tokens', '-')}"
            )
    lines.append("")
    if result_mode in ("artifact", "both"):
        lines.append("Artifacts")
        lines.append(f"- artifact_root: {payload['artifact_root']}")
    else:
        lines.append("Artifacts")
        lines.append("- artifact files are skipped in stdout mode")

    # Diff scope findings breakdown (only when findings have diff_scope tags)
    if findings and any(f.get("diff_scope") for f in findings):
        in_diff = [f for f in findings if f.get("diff_scope") == "in_diff"]
        related = [f for f in findings if f.get("diff_scope") == "related"]

        if in_diff:
            lines.append("")
            lines.append(f"In Diff ({len(in_diff)} findings)")
            for f in in_diff:
                lines.append(
                    f"  {str(f.get('severity', '-')).upper():8s} "
                    f"{str(f.get('category', '-')):15s} "
                    f"{f.get('title', '-')}  "
                    f"{_finding_location_from_dict(f)}"
                )
        if related:
            lines.append("")
            lines.append(f"Related ({len(related)} findings)")
            for f in related:
                lines.append(
                    f"  {str(f.get('severity', '-')).upper():8s} "
                    f"{str(f.get('category', '-')):15s} "
                    f"{f.get('title', '-')}  "
                    f"{_finding_location_from_dict(f)}"
                )

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
    scope.add_argument("--prompt", required=True, help="Task prompt")
    scope.add_argument(
        "--providers",
        default=",".join(DEFAULT_CONFIG.providers),
        help="Comma-separated providers. Supported: claude,codex,gemini,opencode,qwen",
    )
    scope.add_argument("--target-paths", default=".", help="Comma-separated task scope paths")
    scope.add_argument("--task-id", default="", help="Optional stable task id")

    timeouts = parser.add_argument_group("Timeout and Parallelism")
    timeouts.add_argument(
        "--max-provider-parallelism",
        type=int,
        default=DEFAULT_POLICY.max_provider_parallelism,
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
        default=DEFAULT_POLICY.stall_timeout_seconds,
        help="Cancel a provider when output progress is idle for N seconds",
    )
    timeouts.add_argument(
        "--poll-interval",
        type=float,
        default=DEFAULT_POLICY.poll_interval_seconds,
        help="Provider status polling interval in seconds",
    )
    timeouts.add_argument(
        "--review-hard-timeout",
        type=int,
        default=DEFAULT_POLICY.review_hard_timeout_seconds,
        help="Review-mode hard deadline in seconds (0 disables)",
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
        choices=("report", "markdown-pr", "sarif"),
        default="report",
        help="Output format when --json is not set. markdown-pr/sarif are review-only",
    )
    output.add_argument(
        "--include-token-usage",
        action="store_true",
        help="Best-effort token usage extraction (provider and aggregate). Disabled by default for privacy/noise control",
    )
    output.add_argument(
        "--synthesize",
        action="store_true",
        help="Run one extra synthesis pass to produce consensus/divergence summary (default: disabled)",
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
    output.add_argument("--json", action="store_true", help="Print machine-readable JSON output")
    output.add_argument(
        "--stream",
        choices=["jsonl"],
        default=None,
        help="Output JSONL event stream to stdout (mutually exclusive with --json and --format)",
    )

    access = parser.add_argument_group("Access and Contracts")
    access.add_argument("--allow-paths", default=".", help="Comma-separated allowed paths under repo root")
    access.add_argument(
        "--enforcement-mode",
        choices=("strict", "best_effort"),
        default=DEFAULT_POLICY.enforcement_mode,
        help="strict fails closed when permission requirements are unmet",
    )
    access.add_argument(
        "--provider-permissions-json",
        default="",
        help="Provider permission mapping JSON, e.g. '{\"codex\":{\"sandbox\":\"workspace-write\"}}'",
    )
    access.add_argument(
        "--strict-contract",
        action="store_true",
        help="Review mode only: enforce strict findings JSON contract",
    )

    memory = parser.add_argument_group("Memory")
    memory.add_argument(
        "--memory",
        action="store_true",
        help="Enable memory layer (requires evermemos-mcp). Injects history context and writes back findings",
    )
    memory.add_argument(
        "--space",
        default="",
        help="Space slug, e.g. 'my-repo' (default: auto-inferred from git remote). "
             "Do NOT include 'coding:' prefix — it is added automatically. Requires --memory",
    )

    diff_group = parser.add_argument_group("Diff Mode")
    diff_exclusive = diff_group.add_mutually_exclusive_group()
    diff_exclusive.add_argument(
        "--diff",
        action="store_true",
        help="Review only changes vs merge-base with main/master branch",
    )
    diff_exclusive.add_argument(
        "--staged",
        action="store_true",
        help="Review only staged changes (git diff --cached)",
    )
    diff_exclusive.add_argument(
        "--unstaged",
        action="store_true",
        help="Review only unstaged working tree changes (git diff)",
    )
    diff_group.add_argument(
        "--diff-base",
        default="",
        help="Git ref for branch diff comparison (e.g. origin/main, HEAD~3). Implies --diff",
    )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mco",
        description=TOP_LEVEL_DESCRIPTION,
        epilog=TOP_LEVEL_EPILOG,
        formatter_class=_HelpFormatter,
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor = subparsers.add_parser(
        "doctor",
        help="Check provider installation/auth readiness",
        description="Probe local provider binaries and auth status for each selected provider.",
        epilog=DOCTOR_EPILOG,
        formatter_class=_HelpFormatter,
    )
    doctor.add_argument(
        "--providers",
        default=",".join(DEFAULT_CONFIG.providers),
        help="Comma-separated providers. Supported: claude,codex,gemini,opencode,qwen",
    )
    doctor.add_argument("--json", action="store_true", help="Print machine-readable JSON output")

    run = subparsers.add_parser(
        "run",
        help="Run general multi-provider task execution",
        description="Run a prompt across multiple providers without enforcing findings schema.",
        epilog=RUN_EPILOG,
        formatter_class=_HelpFormatter,
    )
    _add_common_execution_args(run)

    review = subparsers.add_parser(
        "review",
        help="Run multi-provider review",
        description="Run structured multi-provider review with normalized findings and decisions.",
        epilog=REVIEW_EPILOG,
        formatter_class=_HelpFormatter,
    )
    _add_common_execution_args(review)

    findings = subparsers.add_parser(
        "findings",
        help="List and manage persisted findings",
        description="List and confirm findings stored in evermemos memory.",
        epilog=FINDINGS_EPILOG,
        formatter_class=_HelpFormatter,
    )
    findings_sub = findings.add_subparsers(dest="findings_action", required=True)

    findings_list = findings_sub.add_parser(
        "list",
        help="List findings",
        formatter_class=_HelpFormatter,
    )
    findings_list.add_argument("--repo", default=".", help="Repository root path")
    findings_list.add_argument("--status", default=None, help="Filter by status (e.g. open, accepted, rejected)")
    findings_list.add_argument("--space", default="", help="Space slug override")
    findings_list.add_argument("--json", action="store_true", help="Print machine-readable JSON output")

    findings_confirm = findings_sub.add_parser(
        "confirm",
        help="Update finding status",
        formatter_class=_HelpFormatter,
    )
    findings_confirm.add_argument("hash", help="Finding hash to confirm")
    findings_confirm.add_argument(
        "--status",
        required=True,
        choices=("accepted", "rejected", "wontfix"),
        help="New status for the finding",
    )
    findings_confirm.add_argument("--repo", default=".", help="Repository root path")
    findings_confirm.add_argument("--space", default="", help="Space slug override")

    # ── memory subcommand ──────────────────────────────────────
    memory_cmd = subparsers.add_parser(
        "memory",
        help="View agent stats, priors, and memory space status",
        description="Inspect memory layer data: agent scores, blended priors, and space status.",
        epilog=MEMORY_EPILOG,
        formatter_class=_HelpFormatter,
    )
    memory_sub = memory_cmd.add_subparsers(dest="memory_action", required=True)

    mem_agent_stats = memory_sub.add_parser(
        "agent-stats",
        help="Show agent reliability scores",
        formatter_class=_HelpFormatter,
    )
    mem_agent_stats.add_argument("--repo", default=".", help="Repository root path")
    mem_agent_stats.add_argument("--space", default="", help="Space slug override")
    mem_agent_stats.add_argument("--json", action="store_true", help="Print machine-readable JSON output")

    mem_priors = memory_sub.add_parser(
        "priors",
        help="Show blended agent weight priors",
        formatter_class=_HelpFormatter,
    )
    mem_priors.add_argument("--repo", default=".", help="Repository root path")
    mem_priors.add_argument("--category", required=True, help="Task category for display context")
    mem_priors.add_argument("--space", default="", help="Space slug override")

    mem_status = memory_sub.add_parser(
        "status",
        help="Show memory space status overview",
        formatter_class=_HelpFormatter,
    )
    mem_status.add_argument("--repo", default=".", help="Repository root path")
    mem_status.add_argument("--space", default="", help="Space slug override")

    # ── serve subcommand ──────────────────────────────────────
    subparsers.add_parser(
        "serve",
        help="Start MCP server (stdio protocol)",
        description="Start a stdio MCP server exposing MCO tools for AI agents and MCP clients.",
        formatter_class=_HelpFormatter,
    )

    return parser


def _resolve_config(args: argparse.Namespace) -> ReviewConfig:
    cfg = ReviewConfig()
    providers = _parse_providers(args.providers) if args.providers else list(cfg.providers)
    artifact_base = args.artifact_base or cfg.artifact_base
    provider_timeouts = dict(cfg.policy.provider_timeouts)
    provider_timeouts.update(_parse_provider_timeouts(args.provider_timeouts))
    allow_paths = _parse_paths(args.allow_paths) if args.allow_paths else list(cfg.policy.allow_paths)
    provider_permissions = _merge_provider_permissions(
        cfg.policy.provider_permissions,
        _parse_provider_permissions_json(args.provider_permissions_json),
    )
    max_provider_parallelism = args.max_provider_parallelism
    if max_provider_parallelism < 0:
        max_provider_parallelism = cfg.policy.max_provider_parallelism
    enforcement_mode = args.enforcement_mode or cfg.policy.enforcement_mode
    stall_timeout_seconds = args.stall_timeout if args.stall_timeout > 0 else cfg.policy.stall_timeout_seconds
    poll_interval_seconds = args.poll_interval if args.poll_interval > 0 else cfg.policy.poll_interval_seconds
    review_hard_timeout_seconds = (
        args.review_hard_timeout if args.review_hard_timeout >= 0 else cfg.policy.review_hard_timeout_seconds
    )
    enforce_findings_contract = bool(args.strict_contract)

    policy = ReviewPolicy(
        timeout_seconds=cfg.policy.timeout_seconds,
        stall_timeout_seconds=stall_timeout_seconds,
        poll_interval_seconds=poll_interval_seconds,
        review_hard_timeout_seconds=review_hard_timeout_seconds,
        enforce_findings_contract=enforce_findings_contract,
        max_retries=cfg.policy.max_retries,
        high_escalation_threshold=cfg.policy.high_escalation_threshold,
        require_non_empty_findings=cfg.policy.require_non_empty_findings,
        max_provider_parallelism=max_provider_parallelism,
        provider_timeouts=provider_timeouts,
        allow_paths=allow_paths,
        provider_permissions=provider_permissions,
        enforcement_mode=enforcement_mode,
    )
    return ReviewConfig(providers=providers, artifact_base=artifact_base, policy=policy)


def _handle_findings(args: argparse.Namespace) -> int:
    """Handle the findings subcommand (list / confirm)."""
    from .bridge.evermemos_client import EverMemosClient
    from .bridge.space import infer_space_slug
    from .findings_cli import confirm_finding, list_findings, render_findings_table

    api_key = os.environ.get("EVERMEMOS_API_KEY", "")
    if not api_key:
        print("EVERMEMOS_API_KEY environment variable is required for findings.", file=sys.stderr)
        return 2

    repo_root = str(Path(args.repo).resolve())
    space_override = args.space.strip() if isinstance(args.space, str) else ""
    slug = infer_space_slug(repo_root, explicit=space_override or None)
    findings_space = f"coding:{slug}--findings"

    client = EverMemosClient(api_key=api_key)

    if args.findings_action == "list":
        status_filter = args.status if args.status else None
        findings = list_findings(client, findings_space, status_filter=status_filter)
        if getattr(args, "json", False):
            print(json.dumps(findings, ensure_ascii=True))
        else:
            if not findings:
                print("No findings found.")
            else:
                print(render_findings_table(findings))
        return 0

    if args.findings_action == "confirm":
        finding_hash = args.hash
        new_status = args.status
        ok = confirm_finding(client, findings_space, finding_hash, new_status)
        if ok:
            print(f"Finding {finding_hash} updated to '{new_status}'.")
            return 0
        else:
            print(f"Finding with hash '{finding_hash}' not found.", file=sys.stderr)
            return 2

    print("Unknown findings action.", file=sys.stderr)
    return 2


def _handle_memory(args: argparse.Namespace) -> int:
    """Handle the memory subcommand (agent-stats / priors / status)."""
    from .bridge.evermemos_client import EverMemosClient
    from .bridge.space import infer_space_slug
    from .memory_cli import show_agent_stats, show_priors, show_status

    api_key = os.environ.get("EVERMEMOS_API_KEY", "")
    if not api_key:
        print("EVERMEMOS_API_KEY environment variable is required for memory.", file=sys.stderr)
        return 2

    repo_root = str(Path(args.repo).resolve())
    space_override = args.space.strip() if isinstance(args.space, str) else ""
    slug = infer_space_slug(repo_root, explicit=space_override or None)

    client = EverMemosClient(api_key=api_key)

    if args.memory_action == "agent-stats":
        agents_space = f"coding:{slug}--agents"
        if getattr(args, "json", False):
            # For JSON output, fetch raw scores
            raw = client.fetch_history(space=agents_space, memory_type="episodic_memory", limit=100)
            scores = []
            for item in raw:
                content = item.get("content", "")
                if EverMemosClient.is_agent_score_entry(content):
                    try:
                        scores.append(EverMemosClient.deserialize_agent_score(content))
                    except (ValueError, json.JSONDecodeError):
                        continue
            print(json.dumps(scores, ensure_ascii=True))
        else:
            print(show_agent_stats(client, agents_space))
        return 0

    if args.memory_action == "priors":
        category = args.category
        print(show_priors(client, repo_root, slug, category))
        return 0

    if args.memory_action == "status":
        print(show_status(client, slug))
        return 0

    print("Unknown memory action.", file=sys.stderr)
    return 2


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command == "doctor":
        providers = [item for item in _parse_providers(args.providers) if item in SUPPORTED_PROVIDERS]
        if not providers:
            print("No valid providers selected.", file=sys.stderr)
            return 2
        payload = _doctor_payload(providers, _doctor_provider_presence(providers))
        if args.json:
            print(json.dumps(payload, ensure_ascii=True))
        else:
            print(_render_doctor_report(payload))
        return 0

    if args.command == "findings":
        return _handle_findings(args)

    if args.command == "memory":
        return _handle_memory(args)

    if args.command == "serve":
        try:
            from .mcp_server import ensure_mcp_installed, run_server
            ensure_mcp_installed()
            import asyncio as _asyncio
            _asyncio.run(run_server())
        except ImportError:
            print(
                "mco serve requires the mcp package. Install with: pip install mco[memory]",
                file=sys.stderr,
            )
            return 2
        return 0

    if args.command not in ("run", "review"):
        parser.error("unsupported command")
        return 2

    # Build thread-safe stream emitter FIRST so even mutual-exclusion errors
    # can be emitted as JSONL events
    stream_mode = getattr(args, "stream", None)
    stream_callback = None
    if stream_mode == "jsonl":
        import threading as _threading
        _stream_lock = _threading.Lock()

        def _stream_emit(event: dict) -> None:
            line = json.dumps(event, ensure_ascii=True)
            with _stream_lock:
                print(line, flush=True)

        stream_callback = _stream_emit

    def _stream_error_exit(code: str, message: str) -> int:
        """Emit error event (if streaming) or print to stderr, then return 2."""
        if stream_callback:
            from datetime import datetime, timezone
            stream_callback({
                "type": "error", "code": code, "message": message,
                "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ"),
            })
        else:
            print(message, file=sys.stderr)
        return 2

    # Validate --stream mutual exclusion (now uses _stream_error_exit for JSONL errors)
    if stream_mode and args.json:
        return _stream_error_exit("invalid_config", "--stream and --json are mutually exclusive")
    if stream_mode and args.format not in ("report",):
        return _stream_error_exit("invalid_config", "--stream and --format are mutually exclusive")

    try:
        cfg = _resolve_config(args)
    except ValueError as exc:
        return _stream_error_exit("config_error", "Configuration error: {}".format(exc))
    repo_root = str(Path(args.repo).resolve())
    providers = [item for item in cfg.providers if item in SUPPORTED_PROVIDERS]
    if not providers:
        return _stream_error_exit("invalid_providers", "No valid providers selected.")
    synth_provider = args.synth_provider.strip() if isinstance(args.synth_provider, str) else ""
    synthesize = bool(args.synthesize or synth_provider)
    if synth_provider and synth_provider not in providers:
        return _stream_error_exit("invalid_config", "--synth-provider must be one of selected providers")

    memory_space = args.space.strip() if isinstance(args.space, str) else ""
    if memory_space and not args.memory:
        return _stream_error_exit("invalid_config", "--space requires --memory")
    if memory_space and ":" in memory_space:
        return _stream_error_exit(
            "invalid_config",
            "--space takes a slug (e.g. 'my-repo'), not a full space_id.\n"
            "The 'coding:' prefix and '--findings'/'--context' suffixes are added automatically.",
        )

    # Normalize diff flags
    diff_base_arg = args.diff_base.strip() if isinstance(args.diff_base, str) else ""
    if diff_base_arg and args.staged:
        return _stream_error_exit("invalid_config", "--diff-base cannot be used with --staged")
    if diff_base_arg and args.unstaged:
        return _stream_error_exit("invalid_config", "--diff-base cannot be used with --unstaged")
    diff_mode = None
    if args.diff or diff_base_arg:
        diff_mode = "branch"
    elif args.staged:
        diff_mode = "staged"
    elif args.unstaged:
        diff_mode = "unstaged"

    req = ReviewRequest(
        repo_root=repo_root,
        prompt=args.prompt,
        providers=providers,  # type: ignore[arg-type]
        artifact_base=str(Path(cfg.artifact_base).resolve()),
        policy=cfg.policy,
        task_id=args.task_id or None,
        target_paths=[item.strip() for item in args.target_paths.split(",") if item.strip()],
        include_token_usage=bool(args.include_token_usage),
        synthesize=synthesize,
        synthesis_provider=synth_provider or None,
        memory_enabled=bool(args.memory),
        memory_space=memory_space or None,
        diff_mode=diff_mode,
        diff_base=diff_base_arg or None,
        stream_callback=stream_callback,
    )
    review_mode = args.command == "review"
    if args.format in ("markdown-pr", "sarif") and not review_mode:
        print(f"--format {args.format} is supported only for review command", file=sys.stderr)
        return 2
    effective_result_mode = args.result_mode
    if args.save_artifacts and effective_result_mode == "stdout":
        effective_result_mode = "both"
    write_artifacts = effective_result_mode in ("artifact", "both")
    try:
        result = run_review(req, review_mode=review_mode, write_artifacts=write_artifacts)
    except ValueError as exc:
        return _stream_error_exit("input_error", "Input error: {}".format(exc))

    # In stream mode, events were already emitted — just return exit code
    if stream_mode:
        if result.decision == "FAIL":
            return 2
        if review_mode and result.decision == "INCONCLUSIVE":
            return 3
        return 0

    payload = {
        "command": args.command,
        "task_id": result.task_id,
        "artifact_root": result.artifact_root,
        "decision": result.decision,
        "terminal_state": result.terminal_state,
        "provider_success_count": sum(1 for item in result.provider_results.values() if bool(item.get("success"))),
        "provider_failure_count": sum(1 for item in result.provider_results.values() if not bool(item.get("success"))),
        "findings_count": result.findings_count,
        "parse_success_count": result.parse_success_count,
        "parse_failure_count": result.parse_failure_count,
        "schema_valid_count": result.schema_valid_count,
        "dropped_findings_count": result.dropped_findings_count,
    }
    if result.token_usage_summary is not None:
        payload["token_usage_summary"] = result.token_usage_summary
    if result.synthesis is not None:
        payload["synthesis"] = result.synthesis
    if effective_result_mode == "artifact":
        if args.json:
            print(json.dumps(payload, ensure_ascii=True))
        else:
            if args.format == "markdown-pr":
                print(format_markdown_pr(payload, result.findings))
            elif args.format == "sarif":
                print(json.dumps(format_sarif(payload, result.findings), ensure_ascii=True, indent=2))
            else:
                print(
                    _render_user_readable_report(
                        args.command,
                        effective_result_mode,
                        providers,
                        payload,
                        result.provider_results,
                        result.findings,
                    )
                )
    else:
        detailed_payload = dict(payload)
        detailed_payload["result_mode"] = effective_result_mode
        detailed_payload["provider_results"] = result.provider_results
        if args.json:
            print(json.dumps(detailed_payload, ensure_ascii=True))
        else:
            if args.format == "markdown-pr":
                print(format_markdown_pr(payload, result.findings))
            elif args.format == "sarif":
                print(json.dumps(format_sarif(payload, result.findings), ensure_ascii=True, indent=2))
            else:
                print(
                    _render_user_readable_report(
                        args.command,
                        effective_result_mode,
                        providers,
                        payload,
                        result.provider_results,
                        result.findings,
                    )
                )

    if result.decision == "FAIL":
        return 2
    if review_mode and result.decision == "INCONCLUSIVE":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
