from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
import re
import sys
import tempfile
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Set, Tuple

from .adapters import adapter_registry
from .adapters.parsing import extract_final_text_from_output, extract_token_usage_from_output, inspect_contract_output
from .artifacts import expected_paths, task_artifact_root
from .config import DIVISION_DIMENSIONS, ReviewPolicy
from .contracts import ConsensusLevel, Evidence, NormalizeContext, NormalizedFinding, ProviderAdapter, ProviderId, TaskInput
from .orchestrator import OrchestratorRuntime
from .retry import RetryPolicy
from .types import AttemptResult, ErrorKind, TaskState


STRICT_JSON_CONTRACT = (
    "Return JSON only. Use this exact shape: "
    '{"findings":[{"finding_id":"<id>","severity":"critical|high|medium|low","category":"bug|security|performance|maintainability|test-gap","title":"<title>",'
    '"evidence":{"file":"<path>","line":null,"symbol":null,"snippet":"<snippet>"},'
    '"recommendation":"<fix>","confidence":0.0,"fingerprint":"<stable-hash>"}]}. '
    "If no findings, return {\"findings\":[]}."
)
REVIEW_FINDINGS_SCHEMA_PATH = Path(__file__).resolve().parent / "schemas" / "review_findings.schema.json"


@dataclass(frozen=True)
class ReviewRequest:
    repo_root: str
    prompt: str
    providers: List[ProviderId]
    artifact_base: str
    policy: ReviewPolicy
    task_id: Optional[str] = None
    target_paths: Optional[List[str]] = None
    include_token_usage: bool = False
    synthesize: bool = False
    synthesis_provider: Optional[ProviderId] = None
    memory_enabled: bool = False
    memory_space: Optional[str] = None
    diff_mode: Optional[str] = None    # "branch" | "staged" | "unstaged" | None
    diff_base: Optional[str] = None    # git ref, only for diff_mode="branch"
    stream_callback: Optional[Any] = None  # Callable[[Dict[str, Any]], None] for JSONL streaming


@dataclass(frozen=True)
class ReviewResult:
    task_id: str
    artifact_root: Optional[str]
    decision: str
    terminal_state: str
    provider_results: Dict[str, Dict[str, object]]
    findings_count: int
    parse_success_count: int
    parse_failure_count: int
    schema_valid_count: int
    dropped_findings_count: int
    findings: List[Dict[str, object]] = field(default_factory=list)
    token_usage_summary: Optional[Dict[str, object]] = None
    synthesis: Optional[Dict[str, object]] = None
    debate_round: Optional[Dict[str, object]] = None
    division_strategy: Optional[str] = None


def _now_iso() -> str:
    """Return current UTC time in ISO 8601 format."""
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%fZ")


def _emit_event(request: "ReviewRequest", event: Dict[str, object]) -> None:
    """Emit a streaming event if stream_callback is set."""
    cb = request.stream_callback
    if cb is not None:
        if "timestamp" not in event:
            event["timestamp"] = _now_iso()
        cb(event)


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_payload_hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return _sha(serialized)


def _default_task_id(repo_root: str, prompt: str) -> str:
    return f"task-{_sha(f'{repo_root}:{prompt}')[:16]}"


def _build_prompt(user_prompt: str, target_paths: List[str]) -> str:
    scope = ", ".join(target_paths) if target_paths else "(none)"
    return f"{user_prompt}\n\nScope: {scope}\n\n{STRICT_JSON_CONTRACT}"


def _build_run_prompt(user_prompt: str, target_paths: List[str], allow_paths: List[str]) -> str:
    scope = ", ".join(target_paths) if target_paths else "(none)"
    allowed = ", ".join(allow_paths) if allow_paths else "."
    return f"{user_prompt}\n\nScope: {scope}\nAllowed Paths: {allowed}"


_DISCOVER_REVIEW_EXCLUDED_NAMES = {
    ".git",
    ".golutra",
    "node_modules",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    "reports",
    "artifacts",
    "dist",
    "build",
}
_DISCOVER_REVIEW_EXCLUDED_SUFFIXES = {".pyc", ".pyo"}


def _is_discover_review_path_excluded(root: Path, path: Path) -> bool:
    try:
        relative = path.relative_to(root)
    except ValueError:
        relative = path
    return any(part in _DISCOVER_REVIEW_EXCLUDED_NAMES for part in relative.parts) or path.suffix in _DISCOVER_REVIEW_EXCLUDED_SUFFIXES


def _discover_review_files(repo_root: str, target_paths: List[str]) -> List[Tuple[str, int]]:
    root = Path(repo_root).resolve(strict=False)
    discovered: Dict[str, int] = {}
    for raw_path in target_paths:
        if not str(raw_path).strip():
            continue
        resolved = _safe_resolve(root, raw_path)
        if resolved.is_file():
            rel = resolved.relative_to(root).as_posix()
            discovered[rel] = int(resolved.stat().st_size)
            continue
        if not resolved.exists() or not resolved.is_dir():
            continue
        for current_root, dirnames, filenames in os.walk(resolved):
            current_path = Path(current_root)
            dirnames[:] = [
                dirname
                for dirname in dirnames
                if not _is_discover_review_path_excluded(root, current_path / dirname)
            ]
            for filename in filenames:
                child = current_path / filename
                if _is_discover_review_path_excluded(root, child):
                    continue
                rel = child.relative_to(root).as_posix()
                if rel not in discovered:
                    discovered[rel] = int(child.stat().st_size)
    return sorted(discovered.items(), key=lambda item: (-item[1], item[0]))


def _distribute_files_round_robin(
    providers: List[str],
    files_with_sizes: List[Tuple[str, int]],
) -> Dict[str, List[str]]:
    assignments: Dict[str, List[str]] = {provider: [] for provider in providers}
    if not providers:
        return assignments
    for index, (file_path, _size) in enumerate(files_with_sizes):
        provider = providers[index % len(providers)]
        assignments[provider].append(file_path)
    return assignments


def _dimension_perspective(dimension: str) -> str:
    return (
        "Focus this review on {} concerns. "
        "Prioritize findings in this dimension and avoid broad unrelated commentary."
    ).format(dimension)


def _assign_division_dimensions(providers: List[str]) -> Dict[str, Dict[str, str]]:
    assignments: Dict[str, Dict[str, str]] = {}
    for index, provider in enumerate(providers):
        if index < len(DIVISION_DIMENSIONS):
            dimension = DIVISION_DIMENSIONS[index]
            assignments[provider] = {
                "mode": "dimensions",
                "dimension": dimension,
                "perspective": _dimension_perspective(dimension),
            }
        else:
            assignments[provider] = {
                "mode": "dimensions",
                "dimension": "full-review",
                "perspective": "",
            }
    return assignments


def _assigned_scope_prefix(assigned_scope: Optional[Dict[str, object]]) -> str:
    if not isinstance(assigned_scope, dict):
        return ""
    mode = str(assigned_scope.get("mode", "")).strip().lower()
    if mode == "files":
        paths = assigned_scope.get("paths")
        assigned_paths = [str(item) for item in paths] if isinstance(paths, list) else []
        rendered_paths = ", ".join(assigned_paths) if assigned_paths else "(none)"
        return (
            "## Assigned Scope\n"
            "Division strategy: files\n"
            f"Assigned files: {rendered_paths}\n"
            "Review only these assigned files. "
            "Do not inspect or report findings outside this file slice.\n\n"
        )
    if mode == "dimensions":
        dimension = str(assigned_scope.get("dimension", "full-review")).strip() or "full-review"
        if dimension == "full-review":
            return (
                "## Assigned Scope\n"
                "Division strategy: dimensions\n"
                "Assigned dimension: full-review\n"
                "You are the overflow reviewer. Perform a comprehensive review across all scoped files.\n\n"
            )
        return (
            "## Assigned Scope\n"
            "Division strategy: dimensions\n"
            f"Assigned dimension: {dimension}\n"
            "Review all scoped files, but prioritize findings in your assigned dimension.\n\n"
        )
    return ""


def _assigned_scope_summary(assigned_scope: Optional[Dict[str, object]]) -> str:
    if not isinstance(assigned_scope, dict):
        return ""
    mode = str(assigned_scope.get("mode", "")).strip().lower()
    if mode == "files":
        paths = assigned_scope.get("paths")
        assigned_paths = [str(item) for item in paths] if isinstance(paths, list) else []
        if not assigned_paths:
            return "files:none"
        preview = ", ".join(assigned_paths[:2])
        if len(assigned_paths) > 2:
            preview += f" (+{len(assigned_paths) - 2} more)"
        return f"files:{preview}"
    if mode == "dimensions":
        dimension = str(assigned_scope.get("dimension", "full-review")).strip() or "full-review"
        return f"dimensions:{dimension}"
    return ""


def _attach_source_scopes(
    merged_findings: List[Dict[str, object]],
    provider_results: Dict[str, Dict[str, object]],
) -> List[Dict[str, object]]:
    for finding in merged_findings:
        detected_by = finding.get("detected_by")
        providers = [str(item) for item in detected_by] if isinstance(detected_by, list) else []
        source_scopes: List[str] = []
        for provider in providers:
            summary = _assigned_scope_summary(provider_results.get(provider, {}).get("assigned_scope"))
            if summary:
                source_scopes.append(f"{provider}={summary}")
        if source_scopes:
            finding["source_scopes"] = source_scopes
    return merged_findings


def _skipped_provider_outcome(
    request: ReviewRequest,
    provider: str,
    assigned_scope: Optional[Dict[str, object]],
    reason: str = "no_files_assigned",
) -> "_ProviderExecutionOutcome":
    provider_result = {
        "success": True,
        "skipped": True,
        "reason": reason,
        "attempts": 0,
        "final_error": None,
        "cancel_reason": "",
        "wall_clock_seconds": 0.0,
        "last_progress_at": "",
        "output_text": "",
        "final_text": "",
        "response_ok": True,
        "response_reason": reason,
        "parse_ok": True,
        "parse_reason": reason,
        "schema_valid_count": 0,
        "dropped_count": 0,
        "findings_count": 0,
        "output_path": None,
        "requested_permissions": {},
        "applied_permissions": {},
        "unknown_permission_keys": [],
        "enforcement_mode": request.policy.enforcement_mode,
        "assigned_scope": dict(assigned_scope) if isinstance(assigned_scope, dict) else None,
    }
    _emit_event(request, {
        "type": "provider_finished",
        "provider": provider,
        "success": True,
        "skipped": True,
        "findings_count": 0,
        "wall_clock_seconds": 0,
        "findings": [],
        "final_error": None,
        "reason": reason,
    })
    return _ProviderExecutionOutcome(
        provider=provider,
        success=True,
        parse_ok=True,
        schema_valid_count=0,
        dropped_count=0,
        findings=[],
        provider_result=provider_result,
    )


def _adapter_registry() -> Mapping[str, ProviderAdapter]:
    return adapter_registry()


def _load_memory_hooks(request: "ReviewRequest") -> "RunHooks":
    """Lazy-load Bridge and fill hook slots. Returns a RunHooks instance."""
    from .hooks import RunHooks
    hooks = RunHooks()
    try:
        from .bridge import register_hooks
        register_hooks(hooks, request)
    except ImportError as exc:
        msg = (
            "[mco] --memory requires the bridge module. Install with: pip install mco[memory]\n"
            "       Import error: {}".format(exc)
        )
        if request.stream_callback is not None:
            _emit_event(request, {
                "type": "provider_error",
                "provider": "memory",
                "error_kind": "missing_dependency",
                "message": msg,
            })
        else:
            print(msg, file=sys.stderr)
    return hooks


def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def _output_text(stdout_text: str, stderr_text: str) -> str:
    return stdout_text if stdout_text.strip() else stderr_text


def _response_quality(success: bool, output_text: str, final_text: str) -> Tuple[bool, str]:
    if not success:
        return (False, "provider_failed")
    if not final_text.strip():
        return (False, "empty_final_text")
    if final_text.strip() == output_text.strip():
        return (True, "raw_text")
    return (True, "extracted_final_text")


def _token_usage_completeness(usage: Optional[Dict[str, int]]) -> str:
    if not usage:
        return "unavailable"
    has_prompt = "prompt_tokens" in usage
    has_completion = "completion_tokens" in usage
    has_total = "total_tokens" in usage
    if has_prompt and has_completion and has_total:
        return "full"
    return "partial"


def _aggregate_token_usage_summary(provider_results: Dict[str, Dict[str, object]]) -> Dict[str, object]:
    totals = {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}
    provider_count = len(provider_results)
    providers_with_usage = 0
    all_full = True
    for details in provider_results.values():
        usage = details.get("token_usage")
        completeness = str(details.get("token_usage_completeness", "unavailable"))
        if isinstance(usage, dict):
            providers_with_usage += 1
            for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                value = usage.get(key)
                if isinstance(value, int):
                    totals[key] += value
        if completeness != "full":
            all_full = False

    if providers_with_usage == 0:
        summary_completeness = "unavailable"
    elif providers_with_usage == provider_count and all_full:
        summary_completeness = "full"
    else:
        summary_completeness = "partial"

    return {
        "providers_with_usage": providers_with_usage,
        "provider_count": provider_count,
        "completeness": summary_completeness,
        "totals": totals,
    }


def _resolve_synthesis_provider(
    provider_order: List[str],
    requested_provider: Optional[str],
) -> Optional[str]:
    if requested_provider:
        return requested_provider if requested_provider in provider_order else None
    if "claude" in provider_order:
        return "claude"
    return provider_order[0] if provider_order else None


def _truncate_synthesis_text(text: str, limit: int = 1200) -> str:
    normalized = text.strip()
    if len(normalized) <= limit:
        return normalized
    return normalized[:limit].rstrip() + "..."


def _build_synthesis_prompt(
    review_mode: bool,
    decision: str,
    terminal_state: str,
    provider_results: Dict[str, Dict[str, object]],
    merged_findings: List[Dict[str, object]],
) -> str:
    provider_summaries: List[Dict[str, object]] = []
    for provider, details in provider_results.items():
        text = str(details.get("final_text", "")) or str(details.get("output_text", ""))
        provider_summaries.append(
            {
                "provider": provider,
                "success": bool(details.get("success")),
                "final_error": details.get("final_error"),
                "findings_count": int(details.get("findings_count", 0)),
                "summary_text": _truncate_synthesis_text(text),
            }
        )

    findings_for_prompt = [
        {
            "severity": finding.get("severity"),
            "category": finding.get("category"),
            "title": finding.get("title"),
            "location": (
                f"{finding.get('evidence', {}).get('file')}:{finding.get('evidence', {}).get('line')}"
                if isinstance(finding.get("evidence"), dict)
                else ""
            ),
            "detected_by": finding.get("detected_by", []),
            "recommendation": finding.get("recommendation", ""),
            "confidence": finding.get("confidence", 0.0),
            "consensus_level": finding.get("consensus_level", "unverified"),
            "consensus_score": finding.get("consensus_score", 0.0),
        }
        for finding in merged_findings[:40]
    ]

    mode = "review" if review_mode else "run"
    return (
        f"You are synthesizing outputs from multiple coding agents for a {mode} task.\n\n"
        f"Decision: {decision}\nTerminal state: {terminal_state}\n\n"
        "Provider outputs (JSON):\n"
        f"{json.dumps(provider_summaries, ensure_ascii=True)}\n\n"
        "Consensus-ranked findings (JSON):\n"
        f"{json.dumps(findings_for_prompt, ensure_ascii=True)}\n\n"
        "Produce concise markdown with these headings only:\n"
        "## Consensus\n## Divergence\n## Recommended Next Steps\n\n"
        "Constraints:\n"
        "- Max 220 words\n"
        "- No code fences\n"
        "- Base the narrative on consensus_level and consensus_score, not raw provider output alone\n"
        "- Be concrete and action-oriented\n"
    )


@dataclass(frozen=True)
class _ProviderExecutionOutcome:
    provider: str
    success: bool
    parse_ok: bool
    schema_valid_count: int
    dropped_count: int
    findings: List[NormalizedFinding]
    provider_result: Dict[str, object]


def _safe_resolve(repo_root: Path, raw_path: str) -> Path:
    candidate_raw = Path(raw_path)
    base = candidate_raw if candidate_raw.is_absolute() else (repo_root / candidate_raw)
    resolved = base.resolve(strict=False)
    repo_resolved = repo_root.resolve(strict=False)
    try:
        resolved.relative_to(repo_resolved)
    except Exception as exc:
        raise ValueError(f"path_outside_repo: {raw_path}") from exc
    return resolved


def _normalize_scopes(repo_root: str, target_paths: List[str], allow_paths: List[str]) -> Tuple[List[str], List[str]]:
    root = Path(repo_root).resolve(strict=False)
    raw_allow = allow_paths if allow_paths else ["."]
    raw_target = target_paths if target_paths else ["."]

    normalized_allow: List[str] = []
    allow_resolved: List[Path] = []
    for raw_path in raw_allow:
        resolved = _safe_resolve(root, raw_path)
        rel = resolved.relative_to(root).as_posix()
        rel_value = rel if rel else "."
        normalized_allow.append(rel_value)
        allow_resolved.append(resolved)

    normalized_target: List[str] = []
    for raw_path in raw_target:
        resolved = _safe_resolve(root, raw_path)
        in_allow = False
        for allow_root in allow_resolved:
            if resolved == allow_root or allow_root in resolved.parents:
                in_allow = True
                break
        if not in_allow:
            raise ValueError(f"target_path_outside_allow_paths: {raw_path}")
        rel = resolved.relative_to(root).as_posix()
        normalized_target.append(rel if rel else ".")

    return normalized_target, normalized_allow


def _supported_permission_keys(adapter: ProviderAdapter) -> Set[str]:
    fn = getattr(adapter, "supported_permission_keys", None)
    if not callable(fn):
        return set()
    try:
        keys = fn()
    except (TypeError, AttributeError):
        return set()
    if not isinstance(keys, list):
        return set()
    return {str(item).strip() for item in keys if str(item).strip()}


def _provider_stall_timeout_seconds(policy: ReviewPolicy, provider: str) -> int:
    timeout = policy.provider_timeouts.get(provider, policy.stall_timeout_seconds)
    try:
        value = int(timeout)
    except (TypeError, ValueError):
        print(f"[mco] warning: invalid stall timeout for '{provider}', using default", file=sys.stderr)
        value = policy.stall_timeout_seconds
    return value if value > 0 else policy.stall_timeout_seconds


def _poll_interval_seconds(policy: ReviewPolicy) -> float:
    try:
        value = float(policy.poll_interval_seconds)
    except (TypeError, ValueError):
        print("[mco] warning: invalid poll interval, using default 1.0s", file=sys.stderr)
        value = 1.0
    return value if value > 0 else 1.0


def _timestamp_to_iso(timestamp: float) -> str:
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(timestamp))


def _raw_output_size_snapshot(artifact_path: str, provider: str) -> Tuple[int, int]:
    root = Path(artifact_path) / "raw"
    stdout_path = root / f"{provider}.stdout.log"
    stderr_path = root / f"{provider}.stderr.log"
    stdout_size = stdout_path.stat().st_size if stdout_path.exists() else 0
    stderr_size = stderr_path.stat().st_size if stderr_path.exists() else 0
    return (stdout_size, stderr_size)


def _ensure_provider_artifacts(artifact_base: str, task_id: str, provider: str) -> None:
    paths = expected_paths(artifact_base, task_id, (provider,))
    provider_json = paths[f"providers/{provider}.json"]
    if not provider_json.exists():
        _write_json(provider_json, {"provider": provider, "note": "provider result fallback"})
    for key in (f"raw/{provider}.stdout.log", f"raw/{provider}.stderr.log"):
        p = paths[key]
        if not p.exists():
            _write_text(p, "")


def _deserialize_findings(payload: object) -> List[NormalizedFinding]:
    findings: List[NormalizedFinding] = []
    findings_payload = payload if isinstance(payload, list) else []
    serialized_findings = [item for item in findings_payload if isinstance(item, dict)]
    for item in serialized_findings:
        try:
            evidence_raw = item.get("evidence", {})
            if not isinstance(evidence_raw, dict):
                continue
            evidence = Evidence(
                file=str(evidence_raw.get("file", "")),
                line=evidence_raw.get("line") if isinstance(evidence_raw.get("line"), int) else None,
                snippet=str(evidence_raw.get("snippet", "")),
                symbol=evidence_raw.get("symbol") if isinstance(evidence_raw.get("symbol"), str) else None,
            )
            finding = NormalizedFinding(
                task_id=str(item["task_id"]),
                provider=item["provider"],
                finding_id=str(item["finding_id"]),
                severity=item["severity"],
                category=item["category"],
                title=str(item["title"]),
                evidence=evidence,
                recommendation=str(item.get("recommendation", "")),
                confidence=float(item.get("confidence", 0.0)),
                fingerprint=str(item.get("fingerprint", "")),
                raw_ref=str(item.get("raw_ref", "")),
            )
        except (KeyError, TypeError, ValueError):
            continue
        findings.append(finding)
    return findings


_SEVERITY_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3}


def _normalize_for_dedupe(value: str) -> str:
    return re.sub(r"\s+", " ", value.strip().lower())


def _finding_dedupe_key(item: NormalizedFinding) -> str:
    line_value = str(item.evidence.line) if isinstance(item.evidence.line, int) else ""
    symbol_value = _normalize_for_dedupe(item.evidence.symbol or "")
    return _sha(
        "||".join(
            [
                _normalize_for_dedupe(item.category),
                _normalize_for_dedupe(item.title),
                _normalize_for_dedupe(item.evidence.file.replace("\\", "/")),
                line_value,
                symbol_value,
            ]
        )
    )


_CONSENSUS_LEVEL_ORDER: Dict[str, int] = {
    "confirmed": 0,
    "needs-verification": 1,
    "unverified": 2,
}


def _agreement_ratio(detected_by_count: int, total_providers_ran: int) -> float:
    safe_total = max(1, total_providers_ran)
    return min(max(detected_by_count, 0) / safe_total, 1.0)


def _consensus_level(detected_by_count: int, total_providers_ran: int) -> ConsensusLevel:
    if detected_by_count <= 1:
        return "unverified"
    if _agreement_ratio(detected_by_count, total_providers_ran) >= 0.5:
        return "confirmed"
    return "needs-verification"


def _apply_consensus_metadata(
    merged_findings: List[Dict[str, object]],
    total_providers_ran: int,
) -> List[Dict[str, object]]:
    for payload in merged_findings:
        detected_by = payload.get("detected_by")
        detected_by_count = len(detected_by) if isinstance(detected_by, list) else 0
        max_confidence_raw = payload.get("confidence")
        max_confidence = float(max_confidence_raw) if isinstance(max_confidence_raw, (int, float)) else 0.0
        agreement_ratio = _agreement_ratio(detected_by_count, total_providers_ran)
        payload["consensus_score"] = round(agreement_ratio * max_confidence, 4)
        payload["consensus_level"] = _consensus_level(detected_by_count, total_providers_ran)
    return merged_findings


def _consensus_counts(findings: List[Dict[str, object]]) -> Dict[str, int]:
    counts = {level: 0 for level in _CONSENSUS_LEVEL_ORDER}
    for finding in findings:
        level = str(finding.get("consensus_level", "")).strip().lower()
        if level in counts:
            counts[level] += 1
    return counts


def _consensus_sort_key(entry: Dict[str, object]) -> Tuple[int, float, int, str, int, str]:
    level = str(entry.get("consensus_level", "unverified")).lower()
    severity = str(entry.get("severity", "low")).lower()
    evidence = entry.get("evidence")
    file_path = ""
    line = 0
    if isinstance(evidence, dict):
        file_path = str(evidence.get("file", ""))
        line_raw = evidence.get("line")
        line = line_raw if isinstance(line_raw, int) else 0
    score_raw = entry.get("consensus_score")
    score = float(score_raw) if isinstance(score_raw, (int, float)) else 0.0
    return (
        _CONSENSUS_LEVEL_ORDER.get(level, len(_CONSENSUS_LEVEL_ORDER)),
        -score,
        _SEVERITY_ORDER.get(severity, 99),
        file_path,
        line,
        str(entry.get("title", "")),
    )


def _merge_findings_across_providers(
    findings: List[NormalizedFinding],
    total_providers_ran: int,
) -> List[Dict[str, object]]:
    merged: Dict[str, Dict[str, object]] = {}
    for item in findings:
        key = _finding_dedupe_key(item)
        existing = merged.get(key)
        if existing is None:
            payload = asdict(item)
            payload["detected_by"] = [item.provider]
            merged[key] = payload
            continue

        detected_by = existing.get("detected_by")
        if not isinstance(detected_by, list):
            detected_by = []
            existing["detected_by"] = detected_by
        if item.provider not in detected_by:
            detected_by.append(item.provider)

        current_confidence = float(existing.get("confidence", 0.0))
        if item.confidence > current_confidence:
            existing["confidence"] = item.confidence

        current_severity = str(existing.get("severity", "low")).lower()
        if _SEVERITY_ORDER.get(item.severity, 99) < _SEVERITY_ORDER.get(current_severity, 99):
            existing["severity"] = item.severity

    merged_findings = list(merged.values())
    for payload in merged_findings:
        detected_by = payload.get("detected_by")
        if isinstance(detected_by, list):
            payload["detected_by"] = sorted({str(item) for item in detected_by if str(item)})

    _apply_consensus_metadata(merged_findings, total_providers_ran)
    merged_findings.sort(key=_consensus_sort_key)
    return merged_findings


def _consensus_label(level: str, chain_mode: bool = False) -> str:
    normalized = level.strip().lower()
    if chain_mode and normalized == "confirmed":
        return "confirmed-by"
    return normalized or "unverified"


def _finding_location_text(finding: Dict[str, object]) -> str:
    evidence = finding.get("evidence")
    if not isinstance(evidence, dict):
        return "-"
    file_path = str(evidence.get("file", "")).strip()
    line = evidence.get("line")
    if file_path and isinstance(line, int) and line > 0:
        return f"{file_path}:{line}"
    return file_path or "-"


def _finding_key_from_payload(finding: Dict[str, object]) -> str:
    fingerprint = str(finding.get("fingerprint", "")).strip()
    if fingerprint:
        return fingerprint
    evidence = finding.get("evidence")
    file_path = ""
    line = ""
    if isinstance(evidence, dict):
        file_path = str(evidence.get("file", "")).strip()
        line_value = evidence.get("line")
        line = str(line_value) if isinstance(line_value, int) else ""
    return _sha(
        "||".join(
            [
                str(finding.get("category", "")).strip().lower(),
                str(finding.get("title", "")).strip().lower(),
                file_path.lower(),
                line,
            ]
        )
    )


def _build_debate_prompt(
    original_prompt: str,
    provider: str,
    findings: List[Dict[str, object]],
) -> str:
    lines = [
        f"You are reviewing findings from other agents for this task.",
        f"Original task: {original_prompt.strip()}",
        "",
        "For each finding below, respond with exactly one of: AGREE, DISAGREE, or REFINE.",
        "Include a brief reason.",
        "Use this exact format for every finding:",
        "Finding 1: [title] at [location] (reported by [provider])",
        "Your verdict: AGREE|DISAGREE|REFINE",
        "Reason: ...",
        "",
        f"You are provider: {provider}",
        "",
    ]
    for index, finding in enumerate(findings, start=1):
        reporters = finding.get("detected_by")
        if isinstance(reporters, list):
            reporter_text = ", ".join(str(item) for item in reporters if str(item).strip())
        else:
            reporter_text = str(finding.get("provider", "")).strip()
        lines.extend(
            [
                f"Finding {index}: {finding.get('title', '-')} at {_finding_location_text(finding)} (reported by {reporter_text or 'unknown'})",
                f"Severity: {finding.get('severity', '-')}",
                f"Category: {finding.get('category', '-')}",
                f"Recommendation: {finding.get('recommendation', '-')}",
                "",
            ]
        )
    return "\n".join(lines).rstrip() + "\n"


def _parse_debate_votes(output_text: str, expected_count: int) -> List[Dict[str, object]]:
    pattern = re.compile(
        r"Finding\s+(\d+)\s*:(.*?)(?=(?:\n\s*Finding\s+\d+\s*:)|\Z)",
        re.IGNORECASE | re.DOTALL,
    )
    votes: Dict[int, Dict[str, object]] = {}
    for match in pattern.finditer(output_text or ""):
        finding_index = int(match.group(1))
        if finding_index <= 0 or finding_index > expected_count or finding_index in votes:
            continue
        block = match.group(0)
        verdict_match = re.search(
            r"(?:Your\s+)?verdict\s*:\s*(AGREE|DISAGREE|REFINE)\b",
            block,
            re.IGNORECASE,
        )
        if verdict_match is None:
            continue
        reason_match = re.search(r"Reason\s*:\s*(.+)", block, re.IGNORECASE | re.DOTALL)
        reason = reason_match.group(1).strip() if reason_match is not None else ""
        votes[finding_index] = {
            "index": finding_index - 1,
            "verdict": verdict_match.group(1).upper(),
            "reason": reason,
        }
    return [votes[index] for index in sorted(votes.keys())]


def _consensus_level_from_support_ratio(support_ratio: float) -> ConsensusLevel:
    if support_ratio >= 0.5:
        return "confirmed"
    if support_ratio >= 0.25:
        return "needs-verification"
    return "unverified"


def _apply_debate_results(
    merged_findings: List[Dict[str, object]],
    debate_round: Dict[str, object],
    total_providers_ran: int,
) -> List[Dict[str, object]]:
    finding_summaries = debate_round.get("findings", [])
    if not isinstance(finding_summaries, list):
        merged_findings.sort(key=_consensus_sort_key)
        return merged_findings

    summaries_by_key = {}
    for item in finding_summaries:
        if not isinstance(item, dict):
            continue
        summaries_by_key[str(item.get("finding_key", ""))] = item

    safe_total = max(1, total_providers_ran)
    for finding in merged_findings:
        key = _finding_key_from_payload(finding)
        summary = summaries_by_key.get(key)
        if not isinstance(summary, dict):
            continue

        detected_by = finding.get("detected_by")
        detected_by_count = len(detected_by) if isinstance(detected_by, list) else 0
        vote_summary = summary.get("vote_summary", {})
        agree_count = int(vote_summary.get("agree", 0)) if isinstance(vote_summary, dict) else 0
        disagree_count = int(vote_summary.get("disagree", 0)) if isinstance(vote_summary, dict) else 0
        refine_count = int(vote_summary.get("refine", 0)) if isinstance(vote_summary, dict) else 0

        confidence_raw = finding.get("confidence")
        max_confidence = float(confidence_raw) if isinstance(confidence_raw, (int, float)) else 0.0
        base_support_ratio = detected_by_count / safe_total
        adjusted_support_ratio = min(
            max(base_support_ratio + ((agree_count - disagree_count) / safe_total), 0.0),
            1.0,
        )
        updated_score = round(max_confidence * adjusted_support_ratio, 4)
        updated_level = _consensus_level_from_support_ratio(adjusted_support_ratio) if updated_score > 0 else "unverified"

        summary["consensus_score_after"] = updated_score
        summary["consensus_level_after"] = updated_level
        summary["refined"] = refine_count > 0

        finding["consensus_score"] = updated_score
        finding["consensus_level"] = updated_level
        finding["debate"] = {
            "vote_summary": vote_summary,
            "refined": refine_count > 0,
            "consensus_score_before": summary.get("consensus_score_before"),
            "consensus_score_after": updated_score,
            "consensus_level_before": summary.get("consensus_level_before"),
            "consensus_level_after": updated_level,
            "votes": summary.get("votes", []),
        }

    merged_findings.sort(key=_consensus_sort_key)
    return merged_findings


def _run_debate_round(
    request: ReviewRequest,
    runtime: OrchestratorRuntime,
    adapter_map: Mapping[str, ProviderAdapter],
    resolved_task_id: str,
    merged_findings: List[Dict[str, object]],
    provider_order: List[str],
    normalized_targets: List[str],
    normalized_allow_paths: List[str],
) -> Dict[str, object]:
    debate_round: Dict[str, object] = {
        "enabled": True,
        "provider_order": list(provider_order),
        "providers": {},
        "findings": [],
    }
    finding_summaries: Dict[str, Dict[str, object]] = {}
    for finding in merged_findings:
        key = _finding_key_from_payload(finding)
        reporters = finding.get("detected_by")
        finding_summaries[key] = {
            "finding_key": key,
            "title": str(finding.get("title", "-")),
            "location": _finding_location_text(finding),
            "reported_by": list(reporters) if isinstance(reporters, list) else [],
            "consensus_score_before": float(finding.get("consensus_score", 0.0)),
            "consensus_level_before": str(finding.get("consensus_level", "unverified")),
            "votes": [],
            "vote_summary": {"agree": 0, "disagree": 0, "refine": 0},
        }

    _emit_event(request, {
        "type": "debate_started",
        "task_id": resolved_task_id,
        "provider_count": len(provider_order),
        "findings_count": len(merged_findings),
    })

    with tempfile.TemporaryDirectory(prefix="mco-debate-") as debate_artifact_base:
        for provider in provider_order:
            candidate_findings = []
            for finding in merged_findings:
                detected_by = finding.get("detected_by")
                reporters = detected_by if isinstance(detected_by, list) else []
                if provider in reporters:
                    continue
                candidate_findings.append(finding)

            provider_votes: List[Dict[str, object]] = []
            provider_payload: Dict[str, object] = {
                "reviewed_count": len(candidate_findings),
                "votes": provider_votes,
                "success": True,
                "final_error": None,
            }
            if not candidate_findings:
                debate_round["providers"][provider] = provider_payload
                continue

            challenge_prompt = _build_debate_prompt(request.prompt, provider, candidate_findings)
            debate_request = ReviewRequest(
                repo_root=request.repo_root,
                prompt=challenge_prompt,
                providers=[provider],  # type: ignore[list-item]
                artifact_base=debate_artifact_base,
                policy=request.policy,
                task_id=f"{resolved_task_id}-debate-{provider}",
                target_paths=request.target_paths,
                include_token_usage=False,
                synthesize=False,
                synthesis_provider=None,
                memory_enabled=False,
                memory_space=None,
                diff_mode=None,
                diff_base=None,
                stream_callback=None,
            )
            outcome = _run_provider(
                debate_request,
                runtime,
                adapter_map,
                f"{resolved_task_id}-debate-{provider}",
                debate_artifact_base,
                False,
                challenge_prompt,
                normalized_targets,
                normalized_allow_paths,
                False,
                provider,
            )
            provider_payload["success"] = outcome.success
            provider_payload["final_error"] = outcome.provider_result.get("final_error")
            output_text = str(outcome.provider_result.get("final_text", "")) or str(
                outcome.provider_result.get("output_text", "")
            )
            parsed_votes = _parse_debate_votes(output_text, len(candidate_findings))
            for vote in parsed_votes:
                finding = candidate_findings[int(vote["index"])]
                finding_key = _finding_key_from_payload(finding)
                vote_payload = {
                    "finding_key": finding_key,
                    "title": str(finding.get("title", "-")),
                    "location": _finding_location_text(finding),
                    "reported_by": list(finding.get("detected_by", [])) if isinstance(finding.get("detected_by"), list) else [],
                    "verdict": str(vote.get("verdict", "")),
                    "reason": str(vote.get("reason", "")),
                }
                provider_votes.append(vote_payload)
                summary = finding_summaries[finding_key]
                summary_votes = summary.get("votes")
                if isinstance(summary_votes, list):
                    summary_votes.append({"provider": provider, **vote_payload})
                vote_summary = summary.get("vote_summary")
                verdict_key = str(vote.get("verdict", "")).lower()
                if isinstance(vote_summary, dict) and verdict_key in vote_summary:
                    vote_summary[verdict_key] = int(vote_summary.get(verdict_key, 0)) + 1
            debate_round["providers"][provider] = provider_payload

    debate_round["findings"] = list(finding_summaries.values())
    _emit_event(request, {
        "type": "debate_finished",
        "task_id": resolved_task_id,
        "provider_count": len(provider_order),
        "findings_count": len(merged_findings),
        "providers_with_votes": sum(
            1
            for item in debate_round["providers"].values()
            if isinstance(item, dict) and item.get("votes")
        ),
    })
    return debate_round


def _format_consensus_summary_markdown(
    findings: List[Dict[str, object]],
    total_providers_ran: int,
    chain_mode: bool = False,
) -> str:
    counts = _consensus_counts(findings)
    lines = [
        "## Consensus Analysis",
        f"- Providers ran: {total_providers_ran}",
        "- Score formula: agreement_ratio x max_confidence",
        f"- confirmed: {counts['confirmed']}",
        f"- needs-verification: {counts['needs-verification']}",
        f"- unverified: {counts['unverified']}",
        "",
    ]
    for level in ("confirmed", "needs-verification", "unverified"):
        group = [finding for finding in findings if str(finding.get("consensus_level", "")).lower() == level]
        if not group:
            continue
        lines.append(f"## {_consensus_label(level, chain_mode=chain_mode).title()}")
        for finding in group:
            evidence = finding.get("evidence")
            location = ""
            if isinstance(evidence, dict):
                file_path = str(evidence.get("file", "")).strip()
                line_value = evidence.get("line")
                if file_path and isinstance(line_value, int) and line_value > 0:
                    location = f"{file_path}:{line_value}"
                else:
                    location = file_path
            score_raw = finding.get("consensus_score")
            score = float(score_raw) if isinstance(score_raw, (int, float)) else 0.0
            detected_by = finding.get("detected_by")
            detected_by_count = len(detected_by) if isinstance(detected_by, list) else 0
            lines.append(
                f"- [{score:.2f}] {str(finding.get('severity', 'low')).upper()} {finding.get('title', 'Finding')}"
                f" ({detected_by_count}/{max(1, total_providers_ran)} providers)"
                + (f" at {location}" if location else "")
            )
        lines.append("")

    lines.extend(
        [
            "## Recommended Next Steps",
            "- Address confirmed findings first.",
            "- Reproduce needs-verification findings with targeted validation.",
            "- Treat unverified findings as leads until corroborated by another provider or test evidence.",
        ]
    )
    return "\n".join(lines)


def _tag_diff_scope(
    findings: List[Dict[str, object]],
    diff_file_set: Optional[set],
) -> List[Dict[str, object]]:
    """Tag each finding with diff_scope based on whether its file is in the diff.

    If diff_file_set is None (non-diff mode), returns findings unchanged.
    """
    if diff_file_set is None:
        return findings
    for finding in findings:
        evidence = finding.get("evidence")
        if not isinstance(evidence, dict):
            finding["diff_scope"] = "unknown"
            continue
        file_path = str(evidence.get("file", "")).strip()
        if not file_path:
            finding["diff_scope"] = "unknown"
        elif file_path in diff_file_set:
            finding["diff_scope"] = "in_diff"
        else:
            finding["diff_scope"] = "related"
    return findings


def _run_provider(
    request: ReviewRequest,
    runtime: OrchestratorRuntime,
    adapter_map: Mapping[str, ProviderAdapter],
    resolved_task_id: str,
    runtime_artifact_base: str,
    persist_artifacts: bool,
    full_prompt: str,
    target_paths: List[str],
    allow_paths: List[str],
    review_mode: bool,
    provider: str,
    assigned_scope: Optional[Dict[str, object]] = None,
    perspective: Optional[str] = None,
) -> _ProviderExecutionOutcome:
    def _ensure_if_persisting() -> None:
        if persist_artifacts:
            _ensure_provider_artifacts(runtime_artifact_base, resolved_task_id, provider)

    _emit_event(request, {"type": "provider_started", "provider": provider})

    adapter = adapter_map.get(provider)
    if adapter is None:
        _emit_event(request, {
            "type": "provider_error", "provider": provider,
            "error_kind": "adapter_not_implemented",
            "message": "No adapter for provider: {}".format(provider),
        })
        _emit_event(request, {
            "type": "provider_finished", "provider": provider,
            "success": False, "findings_count": 0, "wall_clock_seconds": 0,
            "findings": [], "final_error": "adapter_not_implemented",
        })
        _ensure_if_persisting()
        return _ProviderExecutionOutcome(
            provider=provider,
            success=False,
            parse_ok=False,
            schema_valid_count=0,
            dropped_count=0,
            findings=[],
            provider_result={"success": False, "reason": "adapter_not_implemented"},
        )

    presence = adapter.detect()
    if not presence.detected or not presence.auth_ok:
        _emit_event(request, {
            "type": "provider_error", "provider": provider,
            "error_kind": "provider_unavailable",
            "message": "Provider unavailable: detected={}, auth_ok={}".format(
                presence.detected, presence.auth_ok),
        })
        _emit_event(request, {
            "type": "provider_finished", "provider": provider,
            "success": False, "findings_count": 0, "wall_clock_seconds": 0,
            "findings": [], "final_error": "provider_unavailable",
        })
        _ensure_if_persisting()
        return _ProviderExecutionOutcome(
            provider=provider,
            success=False,
            parse_ok=False,
            schema_valid_count=0,
            dropped_count=0,
            findings=[],
            provider_result={
                "success": False,
                "reason": "provider_unavailable",
                "detected": presence.detected,
                "auth_ok": presence.auth_ok,
                "presence_reason": presence.reason,
                "binary_path": presence.binary_path,
                "version": presence.version,
            },
        )

    requested_permissions = request.policy.provider_permissions.get(provider, {})
    requested_permissions = requested_permissions if isinstance(requested_permissions, dict) else {}
    supported_keys = _supported_permission_keys(adapter)
    unknown_permission_keys = sorted(
        key for key in requested_permissions.keys() if str(key).strip() and key not in supported_keys
    )
    effective_permissions = {
        str(key): str(value)
        for key, value in requested_permissions.items()
        if str(key).strip() in supported_keys
    }
    if unknown_permission_keys and request.policy.enforcement_mode == "strict":
        _emit_event(request, {
            "type": "provider_error", "provider": provider,
            "error_kind": "permission_enforcement_failed",
            "message": "Unknown permission keys: {}".format(unknown_permission_keys),
        })
        _emit_event(request, {
            "type": "provider_finished", "provider": provider,
            "success": False, "findings_count": 0, "wall_clock_seconds": 0,
            "findings": [], "final_error": "permission_enforcement_failed",
        })
        _ensure_if_persisting()
        return _ProviderExecutionOutcome(
            provider=provider,
            success=False,
            parse_ok=False,
            schema_valid_count=0,
            dropped_count=0,
            findings=[],
            provider_result={
                "success": False,
                "reason": "permission_enforcement_failed",
                "enforcement_mode": request.policy.enforcement_mode,
                "requested_permissions": requested_permissions,
                "supported_permission_keys": sorted(supported_keys),
                "unknown_permission_keys": unknown_permission_keys,
            },
        )

    provider_stall_timeout = _provider_stall_timeout_seconds(request.policy, provider)
    poll_interval_seconds = _poll_interval_seconds(request.policy)
    review_hard_timeout_seconds = request.policy.review_hard_timeout_seconds if review_mode else 0

    # Inject per-provider perspective if configured
    provider_prompt = _assigned_scope_prefix(assigned_scope) + full_prompt
    effective_perspective = perspective if perspective is not None else request.policy.perspectives.get(provider, "")
    if effective_perspective:
        provider_prompt = "## Review Perspective\n{}\n\n{}".format(effective_perspective, full_prompt)
        provider_prompt = _assigned_scope_prefix(assigned_scope) + provider_prompt

    def runner(_attempt: int) -> AttemptResult:
        run_ref = None
        try:
            metadata = {
                "artifact_root": runtime_artifact_base,
                "allow_paths": allow_paths,
                "provider_permissions": effective_permissions,
                "enforcement_mode": request.policy.enforcement_mode,
            }
            if review_mode and provider == "codex" and REVIEW_FINDINGS_SCHEMA_PATH.exists():
                metadata["output_schema_path"] = str(REVIEW_FINDINGS_SCHEMA_PATH)
            input_task = TaskInput(
                task_id=resolved_task_id,
                prompt=provider_prompt,
                repo_root=request.repo_root,
                target_paths=target_paths,
                timeout_seconds=provider_stall_timeout,
                metadata=metadata,
            )
            run_ref = adapter.run(input_task)
            started = time.time()
            last_progress_at = started
            last_snapshot = _raw_output_size_snapshot(run_ref.artifact_path, provider)
            status = None
            while True:
                status = adapter.poll(run_ref)
                now = time.time()
                if status.completed:
                    break

                current_snapshot = _raw_output_size_snapshot(run_ref.artifact_path, provider)
                if current_snapshot != last_snapshot:
                    last_snapshot = current_snapshot
                    last_progress_at = now
                    _emit_event(request, {
                        "type": "provider_progress",
                        "provider": provider,
                        "total_output_bytes": current_snapshot[0] if isinstance(current_snapshot, tuple) else 0,
                    })

                cancel_reason = ""
                if review_hard_timeout_seconds > 0 and (now - started) > review_hard_timeout_seconds:
                    cancel_reason = "hard_deadline_exceeded"
                elif (now - last_progress_at) > provider_stall_timeout:
                    cancel_reason = "stall_timeout"

                if cancel_reason:
                    _emit_event(request, {
                        "type": "provider_error",
                        "provider": provider,
                        "error_kind": cancel_reason,
                        "message": "Provider cancelled: {}".format(cancel_reason),
                    })
                    if run_ref is not None:
                        try:
                            adapter.cancel(run_ref)
                        except (OSError, ProcessLookupError):
                            pass
                    raw_dir = Path(run_ref.artifact_path) / "raw"
                    timeout_stdout = _read_text(raw_dir / f"{provider}.stdout.log")
                    timeout_stderr = _read_text(raw_dir / f"{provider}.stderr.log")
                    timeout_output_text = _output_text(timeout_stdout, timeout_stderr)
                    timeout_payload = {
                        "cancel_reason": cancel_reason,
                        "wall_clock_seconds": round(now - started, 3),
                        "last_progress_at": _timestamp_to_iso(last_progress_at),
                        "output_text": timeout_output_text,
                        "final_text": extract_final_text_from_output(timeout_output_text),
                        "parse_ok": False,
                        "parse_reason": "",
                        "schema_valid_count": 0,
                        "dropped_count": 0,
                        "findings": [],
                        "run_ref": asdict(run_ref),
                        "status": asdict(status),
                    }
                    return AttemptResult(
                        success=False,
                        output=timeout_payload,
                        error_kind=ErrorKind.RETRYABLE_TIMEOUT,
                        stderr=cancel_reason,
                    )

                time.sleep(poll_interval_seconds)

            if status is None or not status.completed:
                if run_ref is not None:
                    try:
                        adapter.cancel(run_ref)
                    except Exception:
                        pass
                fallback_payload = {
                    "cancel_reason": "provider_poll_timeout",
                    "wall_clock_seconds": round(time.time() - started, 3),
                    "last_progress_at": _timestamp_to_iso(last_progress_at),
                    "output_text": "",
                    "parse_ok": False,
                    "parse_reason": "",
                    "schema_valid_count": 0,
                    "dropped_count": 0,
                    "findings": [],
                    "run_ref": asdict(run_ref) if run_ref is not None else None,
                    "status": asdict(status) if status is not None else None,
                }
                return AttemptResult(
                    success=False,
                    output=fallback_payload,
                    error_kind=ErrorKind.RETRYABLE_TIMEOUT,
                    stderr="provider_poll_timeout",
                )

            raw_dir = Path(run_ref.artifact_path) / "raw"
            raw_stdout = _read_text(raw_dir / f"{provider}.stdout.log")
            raw_stderr = _read_text(raw_dir / f"{provider}.stderr.log")
            findings: List[NormalizedFinding] = []
            parse_ok = False
            parse_reason = "not_applicable"
            schema_valid_count = 0
            dropped_count = 0
            success = status.attempt_state == "SUCCEEDED"
            if review_mode:
                findings = adapter.normalize(
                    raw_stdout,
                    NormalizeContext(
                        task_id=resolved_task_id,
                        provider=provider,
                        repo_root=request.repo_root,
                        raw_ref=f"raw/{provider}.stdout.log",
                    ),
                )
                contract_info = inspect_contract_output(raw_stdout)
                parse_ok = bool(contract_info["parse_ok"])
                parse_reason = str(contract_info.get("parse_reason", ""))
                schema_valid_count = int(contract_info["schema_valid_count"])
                dropped_count = int(contract_info["dropped_count"])
                if request.policy.enforce_findings_contract:
                    success = status.attempt_state == "SUCCEEDED" and parse_ok
                    if request.policy.require_non_empty_findings and success and len(findings) == 0:
                        success = False

            payload = {
                "provider": provider,
                "status": asdict(status),
                "run_ref": asdict(run_ref),
                "cancel_reason": "",
                "wall_clock_seconds": round(time.time() - started, 3),
                "last_progress_at": _timestamp_to_iso(last_progress_at),
                "output_text": _output_text(raw_stdout, raw_stderr),
                "parse_ok": parse_ok,
                "parse_reason": parse_reason,
                "schema_valid_count": schema_valid_count,
                "dropped_count": dropped_count,
                "findings": [asdict(item) for item in findings],
            }
            payload["final_text"] = extract_final_text_from_output(str(payload.get("output_text", "")))
            if success:
                return AttemptResult(success=True, output=payload)
            if status.error_kind:
                return AttemptResult(success=False, output=payload, error_kind=status.error_kind)
            return AttemptResult(success=False, output=payload, error_kind=ErrorKind.NORMALIZATION_ERROR)
        except Exception as exc:  # pragma: no cover - guarded by contract tests
            return AttemptResult(success=False, error_kind=ErrorKind.NORMALIZATION_ERROR, stderr=str(exc))

    run_result = runtime.run_with_retry(resolved_task_id, provider, runner)
    output = run_result.output if isinstance(run_result.output, dict) else {}
    parse_ok = bool(output.get("parse_ok", False))
    provider_schema_valid = int(output.get("schema_valid_count", 0))
    provider_dropped = int(output.get("dropped_count", 0))
    findings = _deserialize_findings(output.get("findings"))
    output_text = str(output.get("output_text", ""))
    final_text = str(output.get("final_text", ""))
    response_ok, response_reason = _response_quality(run_result.success, output_text, final_text)
    token_usage = extract_token_usage_from_output(output_text) if request.include_token_usage else None
    token_usage_completeness = _token_usage_completeness(token_usage) if request.include_token_usage else None

    wall_clock_value = output.get("wall_clock_seconds")
    try:
        wall_clock_seconds = float(wall_clock_value) if wall_clock_value is not None else 0.0
    except Exception:
        wall_clock_seconds = 0.0

    provider_result = {
        "success": run_result.success,
        "attempts": run_result.attempts,
        "final_error": run_result.final_error.value if run_result.final_error else None,
        "cancel_reason": str(output.get("cancel_reason", "")),
        "wall_clock_seconds": wall_clock_seconds,
        "last_progress_at": str(output.get("last_progress_at", "")),
        "output_text": output_text,
        "final_text": final_text,
        "response_ok": response_ok,
        "response_reason": response_reason,
        "parse_ok": parse_ok,
        "parse_reason": str(output.get("parse_reason", "")),
        "schema_valid_count": provider_schema_valid,
        "dropped_count": provider_dropped,
        "findings_count": len(findings),
        "output_path": (
            output.get("status", {}).get("output_path")
            if persist_artifacts and isinstance(output.get("status"), dict)
            else None
        ),
        "requested_permissions": requested_permissions,
        "applied_permissions": effective_permissions,
        "unknown_permission_keys": unknown_permission_keys,
        "enforcement_mode": request.policy.enforcement_mode,
        "assigned_scope": dict(assigned_scope) if isinstance(assigned_scope, dict) else None,
    }
    if request.include_token_usage:
        provider_result["token_usage"] = token_usage
        provider_result["token_usage_completeness"] = token_usage_completeness
    _ensure_if_persisting()
    _emit_event(request, {
        "type": "provider_finished",
        "provider": provider,
        "success": run_result.success,
        "findings_count": len(findings),
        "wall_clock_seconds": wall_clock_seconds,
        "findings": [asdict(item) for item in findings],
        "final_error": run_result.final_error.value if run_result.final_error else None,
    })
    return _ProviderExecutionOutcome(
        provider=provider,
        success=run_result.success,
        parse_ok=parse_ok,
        schema_valid_count=provider_schema_valid,
        dropped_count=provider_dropped,
        findings=findings,
        provider_result=provider_result,
    )


def run_review(
    request: ReviewRequest,
    adapters: Optional[Mapping[str, ProviderAdapter]] = None,
    review_mode: bool = True,
    write_artifacts: bool = True,
) -> ReviewResult:
    temp_artifact_dir: Optional[tempfile.TemporaryDirectory[str]] = None
    adapter_map = dict(adapters or _adapter_registry())
    task_id = request.task_id or _default_task_id(request.repo_root, request.prompt)
    runtime = OrchestratorRuntime(
        retry_policy=RetryPolicy(max_retries=request.policy.max_retries, base_delay_seconds=1.0, backoff_multiplier=2.0),
    )
    resolved_task_id = task_id
    artifact_root = str(task_artifact_root(request.artifact_base, resolved_task_id)) if write_artifacts else None
    runtime_artifact_base = request.artifact_base
    if not write_artifacts:
        temp_artifact_dir = tempfile.TemporaryDirectory(prefix="mco-stdout-")
        runtime_artifact_base = temp_artifact_dir.name
    root_path = Path(artifact_root) if artifact_root else None
    if write_artifacts and root_path:
        root_path.mkdir(parents=True, exist_ok=True)

    try:
        normalized_targets, normalized_allow_paths = _normalize_scopes(
            request.repo_root,
            request.target_paths or ["."],
            request.policy.allow_paths or ["."],
        )
        division_strategy = str(getattr(request.policy, "divide", "") or "").strip().lower() or None

        # ── Diff mode: compute scope and augment prompt ──
        _diff_file_set: Optional[set] = None
        _diff_prompt_prefix = ""
        if request.diff_mode:
            from .diff_utils import detect_main_branch, diff_files, diff_content

            _diff_base = request.diff_base
            if request.diff_mode == "branch" and not _diff_base:
                _diff_base = detect_main_branch(request.repo_root)
            changed = diff_files(request.repo_root, request.diff_mode, _diff_base)

            # Intersect with user-provided target_paths if set
            user_target = request.target_paths or ["."]
            if user_target != ["."]:
                user_dirs = set(user_target)
                changed = [
                    f for f in changed
                    if any(f == d or f.startswith(d.rstrip("/") + "/") for d in user_dirs)
                ]

            if not changed:
                if request.stream_callback is None:
                    import sys as _sys
                    print(
                        "No changes detected for the specified diff mode. Nothing to review.",
                        file=_sys.stderr,
                    )
                _no_op_result = ReviewResult(
                    task_id=task_id,
                    artifact_root=None,
                    decision="PASS",
                    terminal_state="COMPLETED",
                    provider_results={},
                    findings_count=0,
                    parse_success_count=0,
                    parse_failure_count=0,
                    schema_valid_count=0,
                    dropped_findings_count=0,
                    findings=[],
                    division_strategy=division_strategy,
                )
                # Emit stream events even for empty diff
                _emit_event(request, {
                    "type": "run_started",
                    "task_id": task_id,
                    "providers": list(request.providers),
                    "review_mode": review_mode,
                    "division_strategy": division_strategy,
                })
                _emit_event(request, {
                    "type": "result",
                    "task_id": task_id,
                    "decision": "PASS",
                    "terminal_state": "COMPLETED",
                    "division_strategy": division_strategy,
                    "findings_count": 0,
                    "findings": [],
                    "provider_results": {},
                })
                return _no_op_result

            _diff_file_set = set(changed)
            normalized_targets = changed

            _diff_text = diff_content(request.repo_root, request.diff_mode, _diff_base)
            if _diff_text:
                _diff_prompt_prefix = (
                    f"{_diff_text}\n\n"
                    "Review the changes above and any code directly affected by them.\n"
                    "Do not report issues in unchanged code unless they are directly "
                    "caused or exposed by the changes.\n\n"
                    "---\n"
                )

        _effective_prompt = _diff_prompt_prefix + request.prompt if _diff_prompt_prefix else request.prompt
        prompt_body = _effective_prompt
        full_prompt = (
            _build_prompt(_effective_prompt, normalized_targets)
            if review_mode
            else _build_run_prompt(_effective_prompt, normalized_targets, normalized_allow_paths)
        )

        # ── Memory hook: pre_run ──
        _run_hooks = None
        if request.memory_enabled:
            _run_hooks = _load_memory_hooks(request)
            injected = _run_hooks.invoke_pre_run(
                prompt=_effective_prompt,
                repo_root=request.repo_root,
                providers=list(request.providers),
            )
            if injected is not None:
                prompt_body = injected
                full_prompt = (
                    _build_prompt(injected, normalized_targets)
                    if review_mode
                    else _build_run_prompt(injected, normalized_targets, normalized_allow_paths)
                )

        provider_order: List[str] = []
        provider_seen = set()
        for provider in request.providers:
            if provider in provider_seen:
                continue
            provider_seen.add(provider)
            provider_order.append(provider)
        # Preserve user-specified order — critical for --chain where sequence matters.
        # Do NOT sort here; the caller controls ordering via request.providers.

        _emit_event(request, {
            "type": "run_started",
            "task_id": task_id,
            "providers": provider_order,
            "review_mode": review_mode,
            "division_strategy": division_strategy,
        })

        provider_target_paths: Dict[str, List[str]] = {provider: list(normalized_targets) for provider in provider_order}
        provider_prompts: Dict[str, str] = {provider: full_prompt for provider in provider_order}
        provider_assigned_scopes: Dict[str, Dict[str, object]] = {}
        provider_perspectives: Dict[str, str] = {
            provider: str(request.policy.perspectives.get(provider, ""))
            for provider in provider_order
        }
        skipped_outcomes: Dict[str, _ProviderExecutionOutcome] = {}

        if division_strategy == "files":
            discovered_files = _discover_review_files(request.repo_root, normalized_targets)
            if not discovered_files:
                _no_files_result = ReviewResult(
                    task_id=task_id,
                    artifact_root=None,
                    decision="PASS",
                    terminal_state="COMPLETED",
                    provider_results={},
                    findings_count=0,
                    parse_success_count=0,
                    parse_failure_count=0,
                    schema_valid_count=0,
                    dropped_findings_count=0,
                    findings=[],
                    division_strategy=division_strategy,
                )
                _emit_event(request, {
                    "type": "result",
                    "task_id": task_id,
                    "decision": "PASS",
                    "terminal_state": "COMPLETED",
                    "findings_count": 0,
                    "findings": [],
                    "provider_results": {},
                    "division_strategy": division_strategy,
                })
                return _no_files_result
            file_assignments = _distribute_files_round_robin(provider_order, discovered_files)
            for provider in provider_order:
                assigned_files = list(file_assignments.get(provider, []))
                provider_target_paths[provider] = assigned_files
                provider_assigned_scopes[provider] = {
                    "mode": "files",
                    "paths": assigned_files,
                    "path_count": len(assigned_files),
                }
                if assigned_files:
                    provider_prompts[provider] = (
                        _build_prompt(prompt_body, assigned_files)
                        if review_mode
                        else _build_run_prompt(prompt_body, assigned_files, normalized_allow_paths)
                    )
                else:
                    skipped_outcomes[provider] = _skipped_provider_outcome(
                        request,
                        provider,
                        provider_assigned_scopes[provider],
                    )
        elif division_strategy == "dimensions":
            dimension_assignments = _assign_division_dimensions(provider_order)
            for provider in provider_order:
                assigned = dict(dimension_assignments.get(provider, {}))
                assigned["paths"] = list(normalized_targets)
                provider_assigned_scopes[provider] = assigned
                if not provider_perspectives.get(provider):
                    provider_perspectives[provider] = str(assigned.get("perspective", ""))

        if request.policy.max_provider_parallelism <= 0:
            max_workers = max(1, len(provider_order))
        else:
            max_workers = max(1, min(len(provider_order), request.policy.max_provider_parallelism))
        outcomes: Dict[str, _ProviderExecutionOutcome] = dict(skipped_outcomes)
        runnable_providers = [provider for provider in provider_order if provider not in skipped_outcomes]

        # Chain mode: sequential execution where each provider gets prior outputs as context
        if request.policy.chain and len(runnable_providers) > 1:
            chain_prompt = full_prompt
            for idx, provider in enumerate(runnable_providers):
                outcomes[provider] = _run_provider(
                    request,
                    runtime,
                    adapter_map,
                    resolved_task_id,
                    runtime_artifact_base,
                    write_artifacts,
                    chain_prompt,
                    provider_target_paths.get(provider, normalized_targets),
                    normalized_allow_paths,
                    review_mode,
                    provider,
                    provider_assigned_scopes.get(provider),
                    provider_perspectives.get(provider),
                )
                # Append this provider's output as context for the next provider
                if idx < len(runnable_providers) - 1:
                    pr = outcomes[provider].provider_result
                    output_text = str(pr.get("final_text", "")) or str(pr.get("output_text", ""))
                    if output_text.strip():
                        chain_prompt = (
                            "{}\n\n"
                            "---\n"
                            "## Prior Analysis by {}\n"
                            "{}\n"
                            "---\n\n"
                            "Review the above analysis critically. "
                            "Confirm valid findings, challenge questionable ones, "
                            "and add any issues that were missed."
                        ).format(chain_prompt, provider, output_text.strip())
        elif max_workers <= 1:
            for provider in runnable_providers:
                outcomes[provider] = _run_provider(
                    request,
                    runtime,
                    adapter_map,
                    resolved_task_id,
                    runtime_artifact_base,
                    write_artifacts,
                    provider_prompts.get(provider, full_prompt),
                    provider_target_paths.get(provider, normalized_targets),
                    normalized_allow_paths,
                    review_mode,
                    provider,
                    provider_assigned_scopes.get(provider),
                    provider_perspectives.get(provider),
                )
        else:
            with ThreadPoolExecutor(max_workers=max_workers) as executor:
                futures = {
                    executor.submit(
                        _run_provider,
                        request,
                        runtime,
                        adapter_map,
                        resolved_task_id,
                        runtime_artifact_base,
                        write_artifacts,
                        provider_prompts.get(provider, full_prompt),
                        provider_target_paths.get(provider, normalized_targets),
                        normalized_allow_paths,
                        review_mode,
                        provider,
                        provider_assigned_scopes.get(provider),
                        provider_perspectives.get(provider),
                    ): provider
                    for provider in runnable_providers
                }
                # Compute a generous outer timeout: hard timeout (or stall timeout * 2) + buffer
                _hard = request.policy.review_hard_timeout_seconds
                _stall = request.policy.stall_timeout_seconds
                _outer_timeout = (_hard if _hard > 0 else _stall * 2) + 60
                try:
                    for future in as_completed(futures, timeout=_outer_timeout):
                        provider = futures[future]
                        try:
                            outcomes[provider] = future.result()
                        except Exception as exc:  # pragma: no cover - protective guard
                            if write_artifacts:
                                _ensure_provider_artifacts(runtime_artifact_base, resolved_task_id, provider)
                            outcomes[provider] = _ProviderExecutionOutcome(
                                provider=provider,
                                success=False,
                                parse_ok=False,
                                schema_valid_count=0,
                                dropped_count=0,
                                findings=[],
                                provider_result={"success": False, "reason": "internal_error", "error": str(exc)},
                            )
                except TimeoutError:
                    for future, provider in futures.items():
                        if provider not in outcomes:
                            future.cancel()
                            outcomes[provider] = _ProviderExecutionOutcome(
                                provider=provider,
                                success=False,
                                parse_ok=False,
                                schema_valid_count=0,
                                dropped_count=0,
                                findings=[],
                                provider_result={"success": False, "reason": "executor_timeout"},
                            )

        provider_results: Dict[str, Dict[str, object]] = {}
        required_provider_success: Dict[str, bool] = {}
        aggregated_findings: List[NormalizedFinding] = []
        parse_success_count = 0
        parse_failure_count = 0
        schema_valid_count = 0
        dropped_findings_count = 0

        for provider in provider_order:
            outcome = outcomes[provider]
            provider_results[provider] = outcome.provider_result
            is_skipped = bool(outcome.provider_result.get("skipped"))
            if not is_skipped:
                required_provider_success[provider] = outcome.success
            aggregated_findings.extend(outcome.findings)
            if review_mode:
                if not is_skipped:
                    if outcome.parse_ok:
                        parse_success_count += 1
                    else:
                        parse_failure_count += 1
                    schema_valid_count += outcome.schema_valid_count
                    dropped_findings_count += outcome.dropped_count

        token_usage_summary = _aggregate_token_usage_summary(provider_results) if request.include_token_usage else None

        active_provider_order = [provider for provider in provider_order if provider in required_provider_success]
        terminal_state = runtime.evaluate_terminal_state(required_provider_success)
        aggregated_findings.sort(key=lambda item: (item.provider, item.finding_id, item.fingerprint))
        merged_findings = _merge_findings_across_providers(
            aggregated_findings,
            total_providers_ran=len(active_provider_order),
        )
        merged_findings = _tag_diff_scope(merged_findings, _diff_file_set)
        debate_round: Optional[Dict[str, object]] = None
        if review_mode and request.policy.debate and len(active_provider_order) > 1:
            debate_round = _run_debate_round(
                request,
                runtime,
                adapter_map,
                resolved_task_id,
                merged_findings,
                active_provider_order,
                normalized_targets,
                normalized_allow_paths,
            )
            merged_findings = _apply_debate_results(
                merged_findings,
                debate_round,
                total_providers_ran=len(active_provider_order),
            )
        merged_findings = _attach_source_scopes(merged_findings, provider_results)
        consensus_counts = _consensus_counts(merged_findings)

        counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
        for finding in merged_findings:
            severity = str(finding.get("severity", "")).lower()
            if severity in counts:
                counts[severity] = counts.get(severity, 0) + 1

        if review_mode and counts.get("critical", 0) > 0:
            decision = "FAIL"
        elif review_mode and counts.get("high", 0) >= request.policy.high_escalation_threshold:
            decision = "ESCALATE"
        elif review_mode and request.policy.enforce_findings_contract and len(merged_findings) == 0:
            decision = "INCONCLUSIVE"
        elif review_mode and terminal_state == TaskState.FAILED:
            decision = "FAIL"
        elif review_mode and terminal_state == TaskState.PARTIAL_SUCCESS:
            decision = "PARTIAL"
        elif not review_mode and terminal_state == TaskState.FAILED:
            decision = "FAIL"
        elif not review_mode and terminal_state == TaskState.PARTIAL_SUCCESS:
            decision = "PARTIAL"
        else:
            decision = "PASS"

        findings_json = merged_findings

        # ── Memory hook: post_run ──
        if _run_hooks is not None:
            _run_hooks.invoke_post_run(
                findings=findings_json,
                provider_results=provider_results,
                repo_root=request.repo_root,
                prompt=request.prompt,
                providers=list(request.providers),
            )

        synthesis: Optional[Dict[str, object]] = None
        if request.synthesize:
            consensus_text = _format_consensus_summary_markdown(
                merged_findings,
                total_providers_ran=len(active_provider_order),
            )
            selected_synthesis_provider = _resolve_synthesis_provider(active_provider_order, request.synthesis_provider)
            if selected_synthesis_provider is None:
                synthesis = {
                    "provider": request.synthesis_provider,
                    "success": False,
                    "reason": (
                        "requested_provider_not_selected"
                        if request.synthesis_provider
                        else "no_provider_available"
                    ),
                    "text": consensus_text,
                }
            else:
                _emit_event(request, {
                    "type": "synthesis_started",
                    "provider": selected_synthesis_provider,
                })
                synthesis_prompt = _build_synthesis_prompt(
                    review_mode,
                    decision,
                    terminal_state.value,
                    provider_results,
                    merged_findings,
                )
                with tempfile.TemporaryDirectory(prefix="mco-synthesis-") as synthesis_artifact_base:
                    synthesis_request = ReviewRequest(
                        repo_root=request.repo_root,
                        prompt=synthesis_prompt,
                        providers=[selected_synthesis_provider],  # type: ignore[list-item]
                        artifact_base=synthesis_artifact_base,
                        policy=request.policy,
                        task_id=request.task_id,
                        target_paths=request.target_paths,
                        include_token_usage=request.include_token_usage,
                        synthesize=False,
                        synthesis_provider=None,
                    )
                    synthesis_outcome = _run_provider(
                        synthesis_request,
                        runtime,
                        adapter_map,
                        resolved_task_id,
                        synthesis_artifact_base,
                        False,
                        synthesis_prompt,
                        normalized_targets,
                        normalized_allow_paths,
                        False,
                        selected_synthesis_provider,
                    )
                synthesis_provider_result = synthesis_outcome.provider_result
                synthesis_text = str(synthesis_provider_result.get("final_text", "")) or str(
                    synthesis_provider_result.get("output_text", "")
                )
                narrative_success = bool(synthesis_provider_result.get("success")) and bool(synthesis_text.strip())
                synthesis_success = narrative_success
                has_consensus_fallback = not narrative_success
                failure_reason = synthesis_provider_result.get("final_error")
                if failure_reason is None:
                    failure_reason = synthesis_provider_result.get("response_reason")
                if failure_reason is None:
                    failure_reason = synthesis_provider_result.get("reason")
                synthesis_reason = "ok" if narrative_success else (
                    str(failure_reason) if failure_reason not in (None, "") else "synthesis_failed"
                )
                _emit_event(request, {
                    "type": "synthesis_finished",
                    "success": narrative_success,
                })
                combined_text = consensus_text
                if narrative_success and synthesis_text.strip():
                    combined_text = (
                        f"{consensus_text}\n\n## Agent Narrative\n{synthesis_text.strip()}"
                    )
                synthesis = {
                    "provider": selected_synthesis_provider,
                    "success": synthesis_success,
                    "reason": synthesis_reason,
                    "text": combined_text,
                    "consensus_text": consensus_text,
                    "has_consensus_fallback": has_consensus_fallback,
                    "attempts": synthesis_provider_result.get("attempts"),
                    "final_error": synthesis_provider_result.get("final_error"),
                    "wall_clock_seconds": synthesis_provider_result.get("wall_clock_seconds"),
                    "response_ok": synthesis_provider_result.get("response_ok"),
                    "response_reason": synthesis_provider_result.get("response_reason"),
                    "narrative": {
                        "provider": selected_synthesis_provider,
                        "success": narrative_success,
                        "reason": synthesis_reason,
                        "text": synthesis_text,
                    },
                }
                if request.include_token_usage:
                    synthesis["token_usage"] = synthesis_provider_result.get("token_usage")
                    synthesis["token_usage_completeness"] = synthesis_provider_result.get(
                        "token_usage_completeness",
                    )

        if review_mode and write_artifacts and root_path:
            _write_json(root_path / "findings.json", findings_json)

        summary = [
            f"# {'Review' if review_mode else 'Run'} Summary ({resolved_task_id})",
            "",
            f"- Decision: {decision}",
            f"- Terminal state: {terminal_state.value}",
            f"- Division strategy: {division_strategy or 'none'}",
            f"- Providers: {', '.join(provider_order)}",
            f"- Findings total: {len(merged_findings)}",
            f"- Parse success count: {parse_success_count}",
            f"- Parse failure count: {parse_failure_count}",
            f"- Schema valid finding count: {schema_valid_count}",
            f"- Dropped finding count: {dropped_findings_count}",
            f"- Allow paths: {', '.join(normalized_allow_paths)}",
            f"- Enforcement mode: {request.policy.enforcement_mode}",
            f"- Strict contract: {request.policy.enforce_findings_contract}",
            "",
            "## Severity Counts",
            f"- critical: {counts['critical']}",
            f"- high: {counts['high']}",
            f"- medium: {counts['medium']}",
            f"- low: {counts['low']}",
            "",
            "## Consensus Counts",
            f"- confirmed: {consensus_counts['confirmed']}",
            f"- needs-verification: {consensus_counts['needs-verification']}",
            f"- unverified: {consensus_counts['unverified']}",
            "",
            "## Provider Results",
        ]
        for provider in provider_order:
            details = provider_results.get(provider, {})
            success = bool(details.get("success"))
            parse_reason = str(details.get("parse_reason", ""))
            cancel_reason = str(details.get("cancel_reason", ""))
            assigned_scope_summary = _assigned_scope_summary(details.get("assigned_scope"))
            summary.append(
                f"- {provider}: success={success}, final_error={details.get('final_error')}, parse_reason={parse_reason or '-'}, cancel_reason={cancel_reason or '-'}, assigned_scope={assigned_scope_summary or '-'}"
            )
            output_text = str(details.get("output_text", ""))
            if output_text:
                summary.append("  output:")
                for raw_line in output_text.splitlines():
                    summary.append(f"    {raw_line}")
        if synthesis is not None:
            summary.append("")
            summary.append("## Synthesis")
            summary.append(f"- provider: {synthesis.get('provider')}")
            summary.append(f"- success: {synthesis.get('success')}")
            summary.append(f"- reason: {synthesis.get('reason')}")
            text = str(synthesis.get("text", ""))
            if text:
                summary.append("  output:")
                for raw_line in text.splitlines():
                    summary.append(f"    {raw_line}")
        if write_artifacts and root_path:
            _write_text(root_path / "summary.md", "\n".join(summary))

        decision_lines = [f"# {'Review' if review_mode else 'Run'} Decision ({resolved_task_id})", ""]
        decision_lines.append(f"- decision: {decision}")
        decision_lines.append(f"- terminal_state: {terminal_state.value}")
        if review_mode:
            decision_lines.append(
                f"- rule_trace: critical={counts['critical']}, high={counts['high']}, findings={len(merged_findings)}"
            )
        else:
            success_count = sum(1 for value in required_provider_success.values() if value)
            decision_lines.append(
                f"- run_trace: providers={len(required_provider_success)}, success={success_count}, failed={len(required_provider_success) - success_count}"
            )
        if write_artifacts and root_path:
            _write_text(root_path / "decision.md", "\n".join(decision_lines))

        run_payload = {
            "task_id": resolved_task_id,
            "mode": "review" if review_mode else "run",
            "division_strategy": division_strategy,
            "terminal_state": terminal_state.value,
            "decision": decision,
            "effective_cwd": str(Path(request.repo_root).resolve(strict=False)),
            "allow_paths": normalized_allow_paths,
            "allow_paths_hash": _stable_payload_hash(normalized_allow_paths),
            "target_paths": normalized_targets,
            "provider_scopes": {
                provider: details.get("assigned_scope")
                for provider, details in provider_results.items()
                if details.get("assigned_scope") is not None
            },
            "enforcement_mode": request.policy.enforcement_mode,
            "enforce_findings_contract": request.policy.enforce_findings_contract,
            "provider_permissions": request.policy.provider_permissions,
            "permissions_hash": _stable_payload_hash(request.policy.provider_permissions),
            "provider_results": provider_results,
            "findings_count": len(merged_findings),
            "parse_success_count": parse_success_count,
            "parse_failure_count": parse_failure_count,
            "schema_valid_count": schema_valid_count,
            "dropped_findings_count": dropped_findings_count,
        }
        if token_usage_summary is not None:
            run_payload["token_usage_summary"] = token_usage_summary
        run_payload["consensus_summary"] = {
            "provider_count": len(active_provider_order),
            "level_counts": consensus_counts,
        }
        if debate_round is not None:
            run_payload["debate_round"] = debate_round
        if synthesis is not None:
            run_payload["synthesis"] = synthesis
        if write_artifacts and root_path:
            _write_json(root_path / "run.json", run_payload)

        _emit_event(
            request,
            {
                "type": "consensus",
                "task_id": resolved_task_id,
                "provider_count": len(active_provider_order),
                "level_counts": consensus_counts,
                "findings": findings_json,
                "division_strategy": division_strategy,
            },
        )

        # ── Stream: result event ──
        _result_event: Dict[str, object] = {
            "type": "result",
            "task_id": resolved_task_id,
            "decision": decision,
            "terminal_state": terminal_state.value,
            "division_strategy": division_strategy,
            "findings_count": len(merged_findings),
            "findings": findings_json,
            "provider_results": {
                p: {"success": pr.get("success"), "findings_count": pr.get("findings_count", 0),
                     "wall_clock_seconds": pr.get("wall_clock_seconds", 0),
                     "assigned_scope": pr.get("assigned_scope")}
                for p, pr in provider_results.items()
            },
        }
        if token_usage_summary is not None:
            _result_event["token_usage_summary"] = token_usage_summary
        if debate_round is not None:
            _result_event["debate_round"] = debate_round
        if synthesis is not None:
            _result_event["synthesis"] = synthesis
        _emit_event(request, _result_event)

        return ReviewResult(
            task_id=resolved_task_id,
            artifact_root=artifact_root,
            decision=decision,
            terminal_state=terminal_state.value,
            provider_results=provider_results,
            findings_count=len(merged_findings),
            parse_success_count=parse_success_count,
            parse_failure_count=parse_failure_count,
            schema_valid_count=schema_valid_count,
            dropped_findings_count=dropped_findings_count,
            findings=findings_json,
            token_usage_summary=token_usage_summary,
            synthesis=synthesis,
            debate_round=debate_round,
            division_strategy=division_strategy,
        )
    finally:
        if temp_artifact_dir is not None:
            temp_artifact_dir.cleanup()
