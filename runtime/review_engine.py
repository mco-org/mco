from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Dict, List, Mapping, Optional, Set, Tuple

from .adapters import ClaudeAdapter, CodexAdapter, GeminiAdapter, OpenCodeAdapter, QwenAdapter
from .adapters.parsing import inspect_contract_output
from .artifacts import expected_paths, task_artifact_root
from .config import ReviewPolicy
from .contracts import Evidence, NormalizeContext, NormalizedFinding, ProviderAdapter, ProviderId, TaskInput
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


@dataclass(frozen=True)
class ReviewResult:
    task_id: str
    artifact_root: str
    decision: str
    terminal_state: str
    provider_results: Dict[str, Dict[str, object]]
    findings_count: int
    parse_success_count: int
    parse_failure_count: int
    schema_valid_count: int
    dropped_findings_count: int


def _sha(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_payload_hash(payload: object) -> str:
    serialized = json.dumps(payload, ensure_ascii=True, sort_keys=True, separators=(",", ":"))
    return _sha(serialized)


def _default_task_id(repo_root: str, prompt: str) -> str:
    return f"task-{_sha(f'{repo_root}:{prompt}')[:16]}"


def _build_prompt(user_prompt: str, target_paths: List[str]) -> str:
    scope = ", ".join(target_paths) if target_paths else "."
    return f"{user_prompt}\n\nScope: {scope}\n\n{STRICT_JSON_CONTRACT}"


def _build_run_prompt(user_prompt: str, target_paths: List[str], allow_paths: List[str]) -> str:
    scope = ", ".join(target_paths) if target_paths else "."
    allowed = ", ".join(allow_paths) if allow_paths else "."
    return f"{user_prompt}\n\nScope: {scope}\nAllowed Paths: {allowed}"


def _adapter_registry() -> Mapping[str, ProviderAdapter]:
    return {
        "claude": ClaudeAdapter(),
        "codex": CodexAdapter(),
        "gemini": GeminiAdapter(),
        "opencode": OpenCodeAdapter(),
        "qwen": QwenAdapter(),
    }


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
    except Exception:
        return set()
    if not isinstance(keys, list):
        return set()
    return {str(item).strip() for item in keys if str(item).strip()}


def _provider_stall_timeout_seconds(policy: ReviewPolicy, provider: str) -> int:
    timeout = policy.provider_timeouts.get(provider, policy.stall_timeout_seconds)
    try:
        value = int(timeout)
    except Exception:
        value = policy.stall_timeout_seconds
    return value if value > 0 else policy.stall_timeout_seconds


def _poll_interval_seconds(policy: ReviewPolicy) -> float:
    try:
        value = float(policy.poll_interval_seconds)
    except Exception:
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
        except Exception:
            continue
        findings.append(finding)
    return findings


def _run_provider(
    request: ReviewRequest,
    runtime: OrchestratorRuntime,
    adapter_map: Mapping[str, ProviderAdapter],
    resolved_task_id: str,
    full_prompt: str,
    target_paths: List[str],
    allow_paths: List[str],
    review_mode: bool,
    provider: str,
) -> _ProviderExecutionOutcome:
    adapter = adapter_map.get(provider)
    if adapter is None:
        _ensure_provider_artifacts(request.artifact_base, resolved_task_id, provider)
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
        _ensure_provider_artifacts(request.artifact_base, resolved_task_id, provider)
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
        _ensure_provider_artifacts(request.artifact_base, resolved_task_id, provider)
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

    def runner(_attempt: int) -> AttemptResult:
        run_ref = None
        try:
            metadata = {
                "artifact_root": request.artifact_base,
                "allow_paths": allow_paths,
                "provider_permissions": effective_permissions,
                "enforcement_mode": request.policy.enforcement_mode,
            }
            if review_mode and provider == "codex" and REVIEW_FINDINGS_SCHEMA_PATH.exists():
                metadata["output_schema_path"] = str(REVIEW_FINDINGS_SCHEMA_PATH)
            input_task = TaskInput(
                task_id=resolved_task_id,
                prompt=full_prompt,
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

                cancel_reason = ""
                if review_hard_timeout_seconds > 0 and (now - started) > review_hard_timeout_seconds:
                    cancel_reason = "hard_deadline_exceeded"
                elif (now - last_progress_at) > provider_stall_timeout:
                    cancel_reason = "stall_timeout"

                if cancel_reason:
                    if run_ref is not None:
                        try:
                            adapter.cancel(run_ref)
                        except Exception:
                            pass
                    raw_dir = Path(run_ref.artifact_path) / "raw"
                    timeout_stdout = _read_text(raw_dir / f"{provider}.stdout.log")
                    timeout_stderr = _read_text(raw_dir / f"{provider}.stderr.log")
                    timeout_payload = {
                        "cancel_reason": cancel_reason,
                        "wall_clock_seconds": round(now - started, 3),
                        "last_progress_at": _timestamp_to_iso(last_progress_at),
                        "output_text": _output_text(timeout_stdout, timeout_stderr),
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
        "output_text": str(output.get("output_text", "")),
        "parse_ok": parse_ok,
        "parse_reason": str(output.get("parse_reason", "")),
        "schema_valid_count": provider_schema_valid,
        "dropped_count": provider_dropped,
        "findings_count": len(findings),
        "output_path": output.get("status", {}).get("output_path") if isinstance(output.get("status"), dict) else None,
        "requested_permissions": requested_permissions,
        "applied_permissions": effective_permissions,
        "unknown_permission_keys": unknown_permission_keys,
        "enforcement_mode": request.policy.enforcement_mode,
    }
    _ensure_provider_artifacts(request.artifact_base, resolved_task_id, provider)
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
    adapter_map = dict(adapters or _adapter_registry())
    task_id = request.task_id or _default_task_id(request.repo_root, request.prompt)
    runtime = OrchestratorRuntime(
        retry_policy=RetryPolicy(max_retries=request.policy.max_retries, base_delay_seconds=1.0, backoff_multiplier=2.0),
    )
    resolved_task_id = task_id
    artifact_root = str(task_artifact_root(request.artifact_base, resolved_task_id))
    root_path = Path(artifact_root)
    root_path.mkdir(parents=True, exist_ok=True)

    normalized_targets, normalized_allow_paths = _normalize_scopes(
        request.repo_root,
        request.target_paths or ["."],
        request.policy.allow_paths or ["."],
    )
    full_prompt = (
        _build_prompt(request.prompt, normalized_targets)
        if review_mode
        else _build_run_prompt(request.prompt, normalized_targets, normalized_allow_paths)
    )
    provider_order: List[str] = []
    provider_seen = set()
    for provider in request.providers:
        if provider in provider_seen:
            continue
        provider_seen.add(provider)
        provider_order.append(provider)
    provider_order = sorted(provider_order)

    if request.policy.max_provider_parallelism <= 0:
        max_workers = max(1, len(provider_order))
    else:
        max_workers = max(1, min(len(provider_order), request.policy.max_provider_parallelism))
    outcomes: Dict[str, _ProviderExecutionOutcome] = {}
    if max_workers <= 1:
        for provider in provider_order:
            outcomes[provider] = _run_provider(
                request,
                runtime,
                adapter_map,
                resolved_task_id,
                full_prompt,
                normalized_targets,
                normalized_allow_paths,
                review_mode,
                provider,
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
                    full_prompt,
                    normalized_targets,
                    normalized_allow_paths,
                    review_mode,
                    provider,
                ): provider
                for provider in provider_order
            }
            for future in as_completed(futures):
                provider = futures[future]
                try:
                    outcomes[provider] = future.result()
                except Exception as exc:  # pragma: no cover - protective guard
                    _ensure_provider_artifacts(request.artifact_base, resolved_task_id, provider)
                    outcomes[provider] = _ProviderExecutionOutcome(
                        provider=provider,
                        success=False,
                        parse_ok=False,
                        schema_valid_count=0,
                        dropped_count=0,
                        findings=[],
                        provider_result={"success": False, "reason": "internal_error", "error": str(exc)},
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
        required_provider_success[provider] = outcome.success
        aggregated_findings.extend(outcome.findings)
        if review_mode:
            if outcome.parse_ok:
                parse_success_count += 1
            else:
                parse_failure_count += 1
            schema_valid_count += outcome.schema_valid_count
            dropped_findings_count += outcome.dropped_count

    terminal_state = runtime.evaluate_terminal_state(required_provider_success)
    aggregated_findings.sort(key=lambda item: (item.provider, item.finding_id, item.fingerprint))

    counts = {"critical": 0, "high": 0, "medium": 0, "low": 0}
    for finding in aggregated_findings:
        counts[finding.severity] = counts.get(finding.severity, 0) + 1

    if review_mode and counts.get("critical", 0) > 0:
        decision = "FAIL"
    elif review_mode and counts.get("high", 0) >= request.policy.high_escalation_threshold:
        decision = "ESCALATE"
    elif review_mode and request.policy.enforce_findings_contract and len(aggregated_findings) == 0:
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

    findings_json = [
        asdict(item)
        for item in aggregated_findings
    ]

    if review_mode and write_artifacts:
        _write_json(root_path / "findings.json", findings_json)

    summary = [
        f"# {'Review' if review_mode else 'Run'} Summary ({resolved_task_id})",
        "",
        f"- Decision: {decision}",
        f"- Terminal state: {terminal_state.value}",
        f"- Providers: {', '.join(provider_order)}",
        f"- Findings total: {len(aggregated_findings)}",
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
        "## Provider Results",
    ]
    for provider in provider_order:
        details = provider_results.get(provider, {})
        success = bool(details.get("success"))
        parse_reason = str(details.get("parse_reason", ""))
        cancel_reason = str(details.get("cancel_reason", ""))
        summary.append(
            f"- {provider}: success={success}, final_error={details.get('final_error')}, parse_reason={parse_reason or '-'}, cancel_reason={cancel_reason or '-'}"
        )
        output_text = str(details.get("output_text", ""))
        if output_text:
            summary.append("  output:")
            for raw_line in output_text.splitlines():
                summary.append(f"    {raw_line}")
    if write_artifacts:
        _write_text(root_path / "summary.md", "\n".join(summary))

    decision_lines = [f"# {'Review' if review_mode else 'Run'} Decision ({resolved_task_id})", ""]
    decision_lines.append(f"- decision: {decision}")
    decision_lines.append(f"- terminal_state: {terminal_state.value}")
    if review_mode:
        decision_lines.append(
            f"- rule_trace: critical={counts['critical']}, high={counts['high']}, findings={len(aggregated_findings)}"
        )
    else:
        success_count = sum(1 for value in required_provider_success.values() if value)
        decision_lines.append(
            f"- run_trace: providers={len(required_provider_success)}, success={success_count}, failed={len(required_provider_success) - success_count}"
        )
    if write_artifacts:
        _write_text(root_path / "decision.md", "\n".join(decision_lines))

    run_payload = {
        "task_id": resolved_task_id,
        "mode": "review" if review_mode else "run",
        "terminal_state": terminal_state.value,
        "decision": decision,
        "effective_cwd": str(Path(request.repo_root).resolve(strict=False)),
        "allow_paths": normalized_allow_paths,
        "allow_paths_hash": _stable_payload_hash(normalized_allow_paths),
        "target_paths": normalized_targets,
        "enforcement_mode": request.policy.enforcement_mode,
        "enforce_findings_contract": request.policy.enforce_findings_contract,
        "provider_permissions": request.policy.provider_permissions,
        "permissions_hash": _stable_payload_hash(request.policy.provider_permissions),
        "provider_results": provider_results,
        "findings_count": len(aggregated_findings),
        "parse_success_count": parse_success_count,
        "parse_failure_count": parse_failure_count,
        "schema_valid_count": schema_valid_count,
        "dropped_findings_count": dropped_findings_count,
    }
    if write_artifacts:
        _write_json(root_path / "run.json", run_payload)

    return ReviewResult(
        task_id=resolved_task_id,
        artifact_root=artifact_root,
        decision=decision,
        terminal_state=terminal_state.value,
        provider_results=provider_results,
        findings_count=len(aggregated_findings),
        parse_success_count=parse_success_count,
        parse_failure_count=parse_failure_count,
        schema_valid_count=schema_valid_count,
        dropped_findings_count=dropped_findings_count,
    )
