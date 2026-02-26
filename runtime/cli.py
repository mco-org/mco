from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Dict, List

from .config import ReviewConfig, ReviewPolicy, load_review_config
from .review_engine import ReviewRequest, run_review


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
        if not pair or "=" not in pair:
            continue
        provider, timeout_text = pair.split("=", 1)
        provider_name = provider.strip()
        if not provider_name:
            continue
        try:
            timeout = int(timeout_text.strip())
        except Exception:
            continue
        if timeout <= 0:
            continue
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
        return {}
    if not isinstance(payload, dict):
        return {}

    result: Dict[str, Dict[str, str]] = {}
    for provider, permissions in payload.items():
        provider_name = str(provider).strip()
        if not provider_name or not isinstance(permissions, dict):
            continue
        normalized: Dict[str, str] = {}
        for key, value in permissions.items():
            key_name = str(key).strip()
            if not key_name:
                continue
            normalized[key_name] = str(value)
        if normalized:
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
    parser.add_argument("--repo", default=".", help="Repository root path")
    parser.add_argument("--prompt", required=True, help="Task prompt")
    parser.add_argument("--providers", default="", help="Comma-separated providers, e.g. claude,codex")
    parser.add_argument("--config", default="", help="Config file path (.json or .yaml/.yml)")
    parser.add_argument("--artifact-base", default="", help="Artifact base directory override")
    parser.add_argument("--state-file", default="", help="Runtime state file override")
    parser.add_argument("--task-id", default="", help="Optional stable task id")
    parser.add_argument("--idempotency-key", default="", help="Optional stable idempotency key")
    parser.add_argument("--target-paths", default=".", help="Comma-separated task scope paths")
    parser.add_argument("--allow-paths", default="", help="Comma-separated allowed paths (default: .)")
    parser.add_argument(
        "--enforcement-mode",
        choices=("strict", "best_effort"),
        default="",
        help="Permission enforcement mode (default: strict)",
    )
    parser.add_argument(
        "--provider-permissions-json",
        default="",
        help="Provider permission mapping as JSON, e.g. '{\"codex\":{\"sandbox\":\"workspace-write\"}}'",
    )
    parser.add_argument(
        "--max-provider-parallelism",
        type=int,
        default=None,
        help="Override provider fan-out concurrency (0 means full parallelism)",
    )
    parser.add_argument(
        "--provider-timeouts",
        default="",
        help="Comma-separated provider timeout overrides, e.g. claude=120,codex=90",
    )
    parser.add_argument("--json", action="store_true", help="Print machine-readable result JSON")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="mco", description="Multi-CLI Orchestrator")
    subparsers = parser.add_subparsers(dest="command", required=True)

    run = subparsers.add_parser("run", help="Run general multi-provider task execution")
    _add_common_execution_args(run)

    review = subparsers.add_parser("review", help="Run multi-provider review")
    _add_common_execution_args(review)
    return parser


def _resolve_config(args: argparse.Namespace) -> ReviewConfig:
    cfg = load_review_config(args.config or None)
    providers = _parse_providers(args.providers) if args.providers else cfg.providers
    artifact_base = args.artifact_base or cfg.artifact_base
    state_file = args.state_file or cfg.state_file
    provider_timeouts = dict(cfg.policy.provider_timeouts)
    provider_timeouts.update(_parse_provider_timeouts(args.provider_timeouts))
    allow_paths = _parse_paths(args.allow_paths) if args.allow_paths else list(cfg.policy.allow_paths)
    provider_permissions = _merge_provider_permissions(
        cfg.policy.provider_permissions,
        _parse_provider_permissions_json(args.provider_permissions_json),
    )
    max_provider_parallelism = cfg.policy.max_provider_parallelism
    if args.max_provider_parallelism is not None:
        max_provider_parallelism = args.max_provider_parallelism
    enforcement_mode = args.enforcement_mode or cfg.policy.enforcement_mode

    policy = ReviewPolicy(
        timeout_seconds=cfg.policy.timeout_seconds,
        max_retries=cfg.policy.max_retries,
        high_escalation_threshold=cfg.policy.high_escalation_threshold,
        require_non_empty_findings=cfg.policy.require_non_empty_findings,
        max_provider_parallelism=max_provider_parallelism,
        provider_timeouts=provider_timeouts,
        allow_paths=allow_paths,
        provider_permissions=provider_permissions,
        enforcement_mode=enforcement_mode,
    )
    return ReviewConfig(providers=providers, artifact_base=artifact_base, state_file=state_file, policy=policy)


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.command not in ("run", "review"):
        parser.error("unsupported command")
        return 2

    cfg = _resolve_config(args)
    repo_root = str(Path(args.repo).resolve())
    providers = [item for item in cfg.providers if item in ("claude", "codex", "gemini", "opencode", "qwen")]
    if not providers:
        print("No valid providers selected.", file=sys.stderr)
        return 2

    req = ReviewRequest(
        repo_root=repo_root,
        prompt=args.prompt,
        providers=providers,  # type: ignore[arg-type]
        artifact_base=str(Path(cfg.artifact_base).resolve()),
        state_file=str(Path(cfg.state_file).resolve()),
        policy=cfg.policy,
        task_id=args.task_id or None,
        idempotency_key=args.idempotency_key or None,
        target_paths=[item.strip() for item in args.target_paths.split(",") if item.strip()],
    )
    review_mode = args.command == "review"
    result = run_review(req, review_mode=review_mode)

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
        "created_new_task": result.created_new_task,
    }
    if args.json:
        print(json.dumps(payload, ensure_ascii=True))
    else:
        print(f"task_id={result.task_id}")
        print(f"decision={result.decision}")
        print(f"artifact_root={result.artifact_root}")
        print(f"findings={result.findings_count}")
        print(f"parse_success={result.parse_success_count}")
        print(f"parse_failure={result.parse_failure_count}")
        print(f"schema_valid={result.schema_valid_count}")
        print(f"dropped_findings={result.dropped_findings_count}")

    if result.decision == "FAIL":
        return 2
    if review_mode and result.decision == "INCONCLUSIVE":
        return 3
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
