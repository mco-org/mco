from __future__ import annotations

import hashlib
import re
import sys
import threading
import time
from dataclasses import dataclass
from typing import Callable, Dict, List, Optional, Sequence, TextIO


_SEVERITY_ORDER = ("critical", "high", "medium", "low")
_SARIF_LEVEL_BY_SEVERITY = {
    "critical": "error",
    "high": "warning",
    "medium": "note",
    "low": "note",
}
_CONSENSUS_LEVEL_ORDER = ("confirmed", "needs-verification", "unverified")


def _consensus_level_label(level: object, chain_mode: bool = False) -> str:
    normalized = str(level or "unverified").strip().lower() or "unverified"
    if chain_mode and normalized == "confirmed":
        return "confirmed-by"
    return normalized


def _consensus_badge(detected_by: list, total_providers: int, chain_mode: bool = False) -> str:
    """Return a human-readable consensus badge for a finding.

    In parallel mode: based on independent agreement across providers.
    In chain mode: later agents reviewed earlier agents' output, so
    "agree" becomes "confirmed" to reflect non-independent validation.
    """
    n = len(detected_by) if isinstance(detected_by, list) else 0
    if total_providers <= 1 or n <= 0:
        return ""
    if chain_mode:
        if n >= 2:
            return "[confirmed by {}/{}]".format(n, total_providers)
        return "[unconfirmed]"
    if n >= 2:
        return "[{}/{} agree]".format(n, total_providers)
    return "[1 agent only]"


def _consensus_cell(finding: Dict[str, object], total_providers: int, chain_mode: bool = False) -> str:
    level_label = _consensus_level_label(finding.get("consensus_level"), chain_mode=chain_mode)
    badge = _consensus_badge(finding.get("detected_by", []), total_providers, chain_mode=chain_mode)
    score_raw = finding.get("consensus_score")
    score = float(score_raw) if isinstance(score_raw, (int, float)) else 0.0
    parts = [level_label]
    if badge:
        parts.append(badge)
    parts.append(f"score={score:.2f}")
    return " ".join(parts)


def _escape_markdown_cell(value: object) -> str:
    text = str(value)
    return text.replace("\\", "\\\\").replace("|", "\\|").replace("\n", "<br>")


def _finding_location(finding: Dict[str, object]) -> str:
    evidence = finding.get("evidence")
    if not isinstance(evidence, dict):
        return "-"
    file_path = str(evidence.get("file", "")).strip()
    line = evidence.get("line")
    if not file_path:
        return "-"
    if isinstance(line, int) and line > 0:
        return f"{file_path}:{line}"
    return file_path


def format_markdown_pr(payload: Dict[str, object], findings: List[Dict[str, object]], total_providers: int = 0, chain_mode: bool = False) -> str:
    counts = {level: 0 for level in _SEVERITY_ORDER}
    for finding in findings:
        severity = str(finding.get("severity", "")).lower()
        if severity in counts:
            counts[severity] += 1

    lines: List[str] = [
        "## MCO Review Summary",
        "",
        f"- Decision: **{payload.get('decision', '-')}**",
        f"- Terminal State: `{payload.get('terminal_state', '-')}`",
        f"- Division Strategy: `{payload.get('division_strategy', 'none') or 'none'}`",
        f"- Providers: success `{payload.get('provider_success_count', 0)}` / failure `{payload.get('provider_failure_count', 0)}`",
        f"- Findings: `{payload.get('findings_count', 0)}`",
        "",
        "### Severity Breakdown",
        "",
        "| Severity | Count |",
        "|---|---:|",
    ]
    for level in _SEVERITY_ORDER:
        lines.append(f"| `{level}` | {counts[level]} |")

    lines.append("")
    lines.append("### Consensus Breakdown")
    lines.append("")
    lines.append("| Level | Count |")
    lines.append("|---|---:|")
    consensus_counts = {level: 0 for level in _CONSENSUS_LEVEL_ORDER}
    for finding in findings:
        level = str(finding.get("consensus_level", "unverified")).lower()
        if level in consensus_counts:
            consensus_counts[level] += 1
    for level in _CONSENSUS_LEVEL_ORDER:
        lines.append(f"| `{_consensus_level_label(level, chain_mode=chain_mode)}` | {consensus_counts[level]} |")

    lines.append("")
    lines.append("### Findings")
    lines.append("")
    if not findings:
        lines.append("_No findings reported._")
        return "\n".join(lines)

    ordered_findings = sorted(
        findings,
        key=lambda item: (
            _CONSENSUS_LEVEL_ORDER.index(str(item.get("consensus_level", "unverified")).lower())
            if str(item.get("consensus_level", "unverified")).lower() in _CONSENSUS_LEVEL_ORDER
            else len(_CONSENSUS_LEVEL_ORDER),
            -float(item.get("consensus_score", 0.0))
            if isinstance(item.get("consensus_score"), (int, float))
            else 0.0,
            _SEVERITY_ORDER.index(str(item.get("severity", "low")).lower())
            if str(item.get("severity", "low")).lower() in _SEVERITY_ORDER
            else len(_SEVERITY_ORDER),
            _finding_location(item),
            str(item.get("title", "")),
        ),
    )
    for level in _CONSENSUS_LEVEL_ORDER:
        level_findings = [item for item in ordered_findings if str(item.get("consensus_level", "unverified")).lower() == level]
        if not level_findings:
            continue
        has_source_scopes = any(isinstance(item.get("source_scopes"), list) and item.get("source_scopes") for item in level_findings)
        lines.append(f"#### {_consensus_level_label(level, chain_mode=chain_mode).title()}")
        lines.append("")
        if has_source_scopes:
            lines.extend(
                [
                    "| Severity | Category | Title | Location | Confidence | Consensus | Source Scope | Recommendation |",
                    "|---|---|---|---|---:|---|---|---|",
                ]
            )
        else:
            lines.extend(
                [
                    "| Severity | Category | Title | Location | Confidence | Consensus | Recommendation |",
                    "|---|---|---|---|---:|---|---|",
                ]
            )
        for finding in level_findings:
            confidence_value = finding.get("confidence")
            if isinstance(confidence_value, (int, float)):
                confidence_text = f"{float(confidence_value):.2f}"
            else:
                confidence_text = "-"
            cols = [
                f"`{_escape_markdown_cell(str(finding.get('severity', '-')).lower())}`",
                _escape_markdown_cell(finding.get("category", "-")),
                _escape_markdown_cell(finding.get("title", "-")),
                f"`{_escape_markdown_cell(_finding_location(finding))}`",
                confidence_text,
                _escape_markdown_cell(_consensus_cell(finding, total_providers, chain_mode=chain_mode)),
            ]
            if has_source_scopes:
                source_scopes = finding.get("source_scopes")
                cols.append(_escape_markdown_cell(", ".join(str(item) for item in source_scopes) if isinstance(source_scopes, list) else "-"))
            cols.append(_escape_markdown_cell(finding.get("recommendation", "-")))
            lines.append("| " + " | ".join(cols) + " |")
        lines.append("")
    return "\n".join(lines)


def _normalize_rule_name(category: str, title: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9]+", "-", f"{category}-{title}".strip().lower()).strip("-")
    return normalized or "finding"


def _rule_id_for_finding(finding: Dict[str, object]) -> str:
    category = str(finding.get("category", "general")).strip().lower() or "general"
    title = str(finding.get("title", "finding")).strip()
    suffix = hashlib.sha256(f"{category}||{title}".encode("utf-8")).hexdigest()[:10]
    return f"mco/{_normalize_rule_name(category, title)}/{suffix}"


def format_sarif(payload: Dict[str, object], findings: List[Dict[str, object]]) -> Dict[str, object]:
    rules_by_id: Dict[str, Dict[str, object]] = {}
    results: List[Dict[str, object]] = []

    for finding in findings:
        rule_id = _rule_id_for_finding(finding)
        title = str(finding.get("title", "Finding")).strip() or "Finding"
        recommendation = str(finding.get("recommendation", "")).strip()
        category = str(finding.get("category", "")).strip().lower()
        severity = str(finding.get("severity", "low")).strip().lower()
        level = _SARIF_LEVEL_BY_SEVERITY.get(severity, "note")
        consensus_score = finding.get("consensus_score")
        if isinstance(consensus_score, (int, float)):
            confidence_value = float(consensus_score)
        else:
            confidence = finding.get("confidence")
            confidence_value = float(confidence) if isinstance(confidence, (int, float)) else 0.0
        detected_by = finding.get("detected_by")
        if isinstance(detected_by, list):
            detected_by_value = [str(item) for item in detected_by if str(item)]
        else:
            provider = finding.get("provider")
            detected_by_value = [str(provider)] if isinstance(provider, str) and provider else []

        if rule_id not in rules_by_id:
            rule_payload: Dict[str, object] = {
                "id": rule_id,
                "name": _normalize_rule_name(category, title),
                "shortDescription": {"text": title},
                "properties": {"category": category},
            }
            if recommendation:
                rule_payload["help"] = {"text": recommendation}
            rules_by_id[rule_id] = rule_payload

        properties: Dict[str, object] = {
            "category": category,
            "severity": severity,
            "confidence": confidence_value,
            "consensus_level": str(finding.get("consensus_level", "unverified")),
            "detected_by": detected_by_value,
            "fingerprint": str(finding.get("fingerprint", "")),
        }
        diff_scope = finding.get("diff_scope")
        if diff_scope:
            properties["diff_scope"] = diff_scope

        result_payload: Dict[str, object] = {
            "ruleId": rule_id,
            "level": level,
            "message": {"text": title},
            "properties": properties,
        }

        evidence = finding.get("evidence")
        if isinstance(evidence, dict):
            file_path = str(evidence.get("file", "")).strip()
            line = evidence.get("line")
            snippet = str(evidence.get("snippet", "")).strip()
            if file_path:
                region: Dict[str, object] = {}
                if isinstance(line, int) and line > 0:
                    region["startLine"] = line
                if snippet:
                    region["snippet"] = {"text": snippet}
                location = {
                    "physicalLocation": {
                        "artifactLocation": {"uri": file_path},
                        "region": region,
                    }
                }
                result_payload["locations"] = [location]
        results.append(result_payload)

    return {
        "$schema": "https://json.schemastore.org/sarif-2.1.0.json",
        "version": "2.1.0",
        "runs": [
            {
                "tool": {
                    "driver": {
                        "name": "MCO",
                        "informationUri": "https://github.com/mco-org/mco",
                        "rules": list(rules_by_id.values()),
                    }
                },
                "properties": {
                    "decision": payload.get("decision"),
                    "terminal_state": payload.get("terminal_state"),
                    "findings_count": payload.get("findings_count"),
                },
                "results": results,
            }
        ],
    }


@dataclass
class _LiveProviderState:
    status: str = "queued"
    started_at: Optional[float] = None
    elapsed_seconds: float = 0.0
    findings_count: int = 0
    last_error: str = ""
    progress_bytes: int = 0


def _live_divider(title: str, width: int = 72) -> str:
    label = f" {title} "
    if len(label) >= width:
        return label
    side = max(2, (width - len(label)) // 2)
    line = "=" * side + label + "=" * side
    return line[:width]


def _format_elapsed(seconds: float) -> str:
    return f"{max(0.0, float(seconds)):.1f}s"


def _summarize_stream_error(event: Dict[str, object]) -> str:
    error_kind = str(event.get("error_kind", "")).strip()
    message = str(event.get("message", "")).strip()
    final_error = str(event.get("final_error", "")).strip()
    if error_kind in {"stall_timeout", "hard_deadline_exceeded", "executor_timeout"}:
        return "timeout"
    if final_error:
        return final_error.replace("_", " ")
    if error_kind:
        return error_kind.replace("_", " ")
    if message:
        return message
    return "unknown error"


def _ordered_findings(findings: Sequence[Dict[str, object]]) -> List[Dict[str, object]]:
    return sorted(
        list(findings),
        key=lambda item: (
            _SEVERITY_ORDER.index(str(item.get("severity", "low")).lower())
            if str(item.get("severity", "low")).lower() in _SEVERITY_ORDER
            else len(_SEVERITY_ORDER),
            _finding_location(item),
            str(item.get("title", "")),
        ),
    )


def format_live_findings_section(provider: str, findings: Sequence[Dict[str, object]]) -> str:
    lines = [_live_divider(f"{provider} findings")]
    ordered = _ordered_findings(findings)
    if not ordered:
        lines.append("No findings.")
        return "\n".join(lines)

    for finding in ordered:
        severity = str(finding.get("severity", "-")).upper()
        title = str(finding.get("title", "-")).strip() or "-"
        location = _finding_location(finding) or "-"
        lines.append(f"- {severity:8s} {title}  {location}")
    return "\n".join(lines)


def format_live_result_section(
    event: Dict[str, object],
    total_providers: int = 0,
    chain_mode: bool = False,
) -> str:
    findings = event.get("findings")
    findings_list = findings if isinstance(findings, list) else []
    ordered = _ordered_findings([item for item in findings_list if isinstance(item, dict)])
    lines = [_live_divider("Final Merged Result")]
    lines.append(
        "Decision: {} | Terminal: {} | Findings: {}".format(
            event.get("decision", "-"),
            event.get("terminal_state", "-"),
            event.get("findings_count", len(ordered)),
        )
    )
    lines.append("")
    lines.append("Merged findings")
    if not ordered:
        lines.append("No merged findings.")
    else:
        for finding in ordered:
            badge = _consensus_badge(
                finding.get("detected_by", []),
                total_providers,
                chain_mode=chain_mode,
            )
            suffix = f"  {badge}" if badge else ""
            lines.append(
                "- {severity:8s} {title}  {location}{suffix}".format(
                    severity=str(finding.get("severity", "-")).upper(),
                    title=str(finding.get("title", "-")).strip() or "-",
                    location=_finding_location(finding) or "-",
                    suffix=suffix,
                )
            )

    multi_provider = 0
    single_provider = 0
    for finding in ordered:
        detected_by = finding.get("detected_by", [])
        agreement_count = len(detected_by) if isinstance(detected_by, list) else 0
        if agreement_count >= 2:
            multi_provider += 1
        elif agreement_count == 1:
            single_provider += 1

    lines.append("")
    lines.append("Consensus analysis")
    lines.append(f"- multi-provider findings: {multi_provider}")
    lines.append(f"- single-provider findings: {single_provider}")
    debate_round = event.get("debate_round")
    if isinstance(debate_round, dict):
        debate_findings = debate_round.get("findings", [])
        if isinstance(debate_findings, list) and debate_findings:
            lines.append("")
            lines.append("Debate summary")
            for item in debate_findings:
                if not isinstance(item, dict):
                    continue
                vote_summary = item.get("vote_summary", {})
                if isinstance(vote_summary, dict):
                    votes = "A:{}/D:{}/R:{}".format(
                        vote_summary.get("agree", 0),
                        vote_summary.get("disagree", 0),
                        vote_summary.get("refine", 0),
                    )
                else:
                    votes = "A:0/D:0/R:0"
                lines.append(
                    "- {title}  {votes}  {before:.2f}->{after:.2f}".format(
                        title=str(item.get("title", "-")).strip() or "-",
                        votes=votes,
                        before=float(item.get("consensus_score_before", 0.0)),
                        after=float(item.get("consensus_score_after", 0.0)),
                    )
                )
    synthesis = event.get("synthesis")
    if isinstance(synthesis, dict):
        synthesis_text = str(synthesis.get("text", "")).strip()
        lines.append(
            "- synthesis: provider={}, success={}, reason={}".format(
                synthesis.get("provider"),
                synthesis.get("success"),
                synthesis.get("reason"),
            )
        )
        if synthesis_text:
            lines.append("")
            lines.append("Synthesis")
            lines.extend(synthesis_text.splitlines())

    return "\n".join(lines)


class LiveStreamRenderer:
    def __init__(
        self,
        stream: Optional[TextIO] = None,
        *,
        is_tty: Optional[bool] = None,
        clock: Optional[Callable[[], float]] = None,
        refresh_interval_seconds: float = 0.2,
        chain_mode: bool = False,
    ) -> None:
        self.stream = stream or sys.stdout
        self.is_tty = bool(getattr(self.stream, "isatty", lambda: False)()) if is_tty is None else bool(is_tty)
        self._clock = clock or time.monotonic
        self._refresh_interval_seconds = refresh_interval_seconds
        self._chain_mode = chain_mode
        self._lock = threading.RLock()
        self._stop_event = threading.Event()
        self._ticker: Optional[threading.Thread] = None
        self._provider_order: List[str] = []
        self._providers: Dict[str, _LiveProviderState] = {}
        self._status_line_count = 0
        self._finalized = False

    def handle_event(self, event: Dict[str, object]) -> None:
        with self._lock:
            event_type = str(event.get("type", "")).strip()
            if event_type == "run_started":
                self._provider_order = [
                    str(provider) for provider in event.get("providers", []) if str(provider).strip()
                ]
                for provider in self._provider_order:
                    self._providers.setdefault(provider, _LiveProviderState())
                self._start_ticker_locked()
                self._redraw_status_block_locked()
                return

            if event_type == "provider_started":
                state = self._state_for_provider_locked(str(event.get("provider", "")))
                state.status = "running"
                state.started_at = self._clock()
                state.elapsed_seconds = 0.0
                self._redraw_status_block_locked()
                return

            if event_type == "provider_progress":
                state = self._state_for_provider_locked(str(event.get("provider", "")))
                if state.status == "queued":
                    state.status = "running"
                    state.started_at = self._clock()
                output_bytes = event.get("total_output_bytes")
                if isinstance(output_bytes, int) and output_bytes >= 0:
                    state.progress_bytes = output_bytes
                self._redraw_status_block_locked()
                return

            if event_type == "provider_error":
                state = self._state_for_provider_locked(str(event.get("provider", "")))
                state.last_error = _summarize_stream_error(event)
                return

            if event_type == "provider_finished":
                provider = str(event.get("provider", ""))
                state = self._state_for_provider_locked(provider)
                wall_clock_seconds = event.get("wall_clock_seconds")
                if isinstance(wall_clock_seconds, (int, float)):
                    state.elapsed_seconds = float(wall_clock_seconds)
                elif state.started_at is not None:
                    state.elapsed_seconds = self._clock() - state.started_at
                findings_count = event.get("findings_count")
                if isinstance(findings_count, int):
                    state.findings_count = findings_count
                findings = event.get("findings")
                findings_list = findings if isinstance(findings, list) else []
                success = bool(event.get("success"))
                if success:
                    state.status = "done"
                else:
                    state.status = "error"
                    if not state.last_error:
                        state.last_error = _summarize_stream_error(event)
                self._replace_status_block_locked(
                    format_live_findings_section(
                        provider,
                        [item for item in findings_list if isinstance(item, dict)],
                    ),
                    include_status_block=True,
                )
                return

            if event_type == "debate_started":
                self._replace_status_block_locked(
                    _live_divider("Debate Round")
                    + "\n"
                    + "Starting debate round for {} findings across {} providers.".format(
                        event.get("findings_count", 0),
                        event.get("provider_count", 0),
                    ),
                    include_status_block=True,
                )
                return

            if event_type == "debate_finished":
                self._replace_status_block_locked(
                    _live_divider("Debate Round")
                    + "\n"
                    + "Finished debate round. providers_with_votes={}".format(
                        event.get("providers_with_votes", 0),
                    ),
                    include_status_block=True,
                )
                return

            if event_type == "result":
                self._finalized = True
                self._stop_ticker_locked()
                status_block = "\n".join(self._status_lines_locked())
                final_section = format_live_result_section(
                    event,
                    total_providers=len(self._provider_order),
                    chain_mode=self._chain_mode,
                )
                combined = final_section if not status_block else status_block + "\n\n" + final_section
                self._replace_status_block_locked(combined, include_status_block=False)
                return

            if event_type == "error":
                self._finalized = True
                self._stop_ticker_locked()
                message = "Stream error: {}".format(str(event.get("message", "")).strip() or str(event.get("code", "")))
                self._replace_status_block_locked(message, include_status_block=False)

    def close(self) -> None:
        with self._lock:
            self._finalized = True
            self._stop_ticker_locked()

    def _state_for_provider_locked(self, provider: str) -> _LiveProviderState:
        provider_name = provider.strip() or "unknown"
        if provider_name not in self._providers:
            self._providers[provider_name] = _LiveProviderState()
            self._provider_order.append(provider_name)
        return self._providers[provider_name]

    def _start_ticker_locked(self) -> None:
        if not self.is_tty or self._refresh_interval_seconds <= 0:
            return
        if self._ticker is not None and self._ticker.is_alive():
            return
        self._stop_event.clear()
        self._ticker = threading.Thread(target=self._tick, name="mco-live-stream", daemon=True)
        self._ticker.start()

    def _stop_ticker_locked(self) -> None:
        self._stop_event.set()
        ticker = self._ticker
        self._ticker = None
        if ticker is not None and ticker.is_alive() and threading.current_thread() is not ticker:
            ticker.join(timeout=0.5)

    def _tick(self) -> None:
        while not self._stop_event.wait(self._refresh_interval_seconds):
            with self._lock:
                if self._finalized:
                    return
                if any(state.status == "running" for state in self._providers.values()):
                    self._redraw_status_block_locked()

    def _status_lines_locked(self) -> List[str]:
        lines: List[str] = []
        for provider in self._provider_order:
            state = self._providers.get(provider, _LiveProviderState())
            if state.status == "done":
                lines.append(
                    f"[{provider}] ✓ done — {state.findings_count} findings ({_format_elapsed(state.elapsed_seconds)})"
                )
            elif state.status == "error":
                error_text = state.last_error or "unknown error"
                lines.append(
                    f"[{provider}] ✗ error — {error_text} ({_format_elapsed(state.elapsed_seconds)})"
                )
            elif state.status == "running":
                elapsed = state.elapsed_seconds
                if state.started_at is not None:
                    elapsed = self._clock() - state.started_at
                lines.append(f"[{provider}] ⏳ running... (elapsed {_format_elapsed(elapsed)})")
            else:
                lines.append(f"[{provider}] … waiting")
        return lines

    def _clear_status_block_locked(self) -> None:
        if not self.is_tty or self._status_line_count <= 0:
            return
        self.stream.write(f"\x1b[{self._status_line_count}F")
        for index in range(self._status_line_count):
            self.stream.write("\x1b[2K")
            if index < self._status_line_count - 1:
                self.stream.write("\x1b[1E")
        if self._status_line_count > 1:
            self.stream.write(f"\x1b[{self._status_line_count - 1}F")

    def _write_status_block_locked(self) -> None:
        lines = self._status_lines_locked()
        self._status_line_count = len(lines)
        if not lines:
            return
        self.stream.write("\n".join(lines) + "\n")

    def _redraw_status_block_locked(self) -> None:
        if self._finalized:
            return
        self._clear_status_block_locked()
        self._write_status_block_locked()
        self.stream.flush()

    def _replace_status_block_locked(self, text: str, *, include_status_block: bool) -> None:
        self._clear_status_block_locked()
        self._status_line_count = 0
        cleaned = text.rstrip()
        if cleaned:
            self.stream.write(cleaned + "\n")
        if include_status_block and not self._finalized:
            self._write_status_block_locked()
        self.stream.flush()
