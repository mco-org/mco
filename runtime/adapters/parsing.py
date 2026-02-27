from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional, Tuple

from ..contracts import Evidence, NormalizedFinding, NormalizeContext, ProviderId

ALLOWED_SEVERITY = {"critical", "high", "medium", "low"}
ALLOWED_CATEGORY = {"bug", "security", "performance", "maintainability", "test-gap"}


def _decode_json_fragments(text: str) -> List[Any]:
    decoder = json.JSONDecoder()
    payloads: List[Any] = []
    index = 0
    while index < len(text):
        match = re.search(r"[\{\[]", text[index:])
        if not match:
            break
        start = index + match.start()
        try:
            payload, end = decoder.raw_decode(text, start)
        except json.JSONDecodeError:
            index = start + 1
            continue
        payloads.append(payload)
        index = end
    return payloads


def _iter_nested_strings(payload: Any) -> List[str]:
    nested_strings: List[str] = []
    stack = [payload]
    while stack:
        node = stack.pop()
        if isinstance(node, dict):
            for value in node.values():
                if isinstance(value, str):
                    nested_strings.append(value)
                elif isinstance(value, (dict, list)):
                    stack.append(value)
        elif isinstance(node, list):
            for value in node:
                if isinstance(value, str):
                    nested_strings.append(value)
                elif isinstance(value, (dict, list)):
                    stack.append(value)
    return nested_strings


def _looks_like_nested_json_blob(value: str) -> bool:
    stripped = value.strip()
    if not stripped:
        return False
    lowered = stripped.lower()
    if stripped.startswith("{") or stripped.startswith("["):
        return True
    if "```json" in lowered:
        return True
    if "findings" in lowered and ("{" in stripped or "}" in stripped):
        return True
    return False


def _append_text_candidate(candidates: List[str], value: str) -> None:
    normalized = value.strip()
    if not normalized:
        return
    if normalized.startswith("```") and normalized.endswith("```"):
        normalized = normalized.strip("`").strip()
    if not normalized:
        return
    if candidates and candidates[-1] == normalized:
        return
    candidates.append(normalized)


def _text_candidate_score(value: str) -> int:
    normalized = value.strip()
    if not normalized:
        return -100

    score = 0
    length = len(normalized)
    if length >= 24:
        score += 1
    if length >= 80:
        score += 2
    if " " in normalized or "\n" in normalized:
        score += 1
    if re.search(r"[.!?。；;:]", normalized):
        score += 1
    if normalized.startswith("<path>") or "<content>" in normalized:
        score -= 3
    if re.fullmatch(r"[A-Za-z0-9_./*:-]+", normalized) and length < 40:
        score -= 3
    if "\n" not in normalized and " " not in normalized and length < 24:
        score -= 3
    return score


def _select_best_text_candidate(candidates: List[str]) -> str:
    best_index = 0
    best_score = _text_candidate_score(candidates[0])
    for index, candidate in enumerate(candidates[1:], start=1):
        score = _text_candidate_score(candidate)
        if score > best_score or (score == best_score and index > best_index):
            best_index = index
            best_score = score
    return candidates[best_index]


def _collect_final_text_candidates(payload: Any, candidates: List[str]) -> None:
    if isinstance(payload, dict):
        payload_type = payload.get("type")
        if isinstance(payload_type, str):
            payload_type = payload_type.lower()
            if payload_type == "text" and isinstance(payload.get("text"), str):
                _append_text_candidate(candidates, payload.get("text", ""))
            if payload_type in ("result", "final", "completion", "assistant", "message"):
                for key in ("result", "final_text", "text", "content", "message", "response", "output"):
                    value = payload.get(key)
                    if isinstance(value, str):
                        _append_text_candidate(candidates, value)

        for key in ("final_text", "result", "text", "content", "message", "response", "output", "output_text"):
            value = payload.get(key)
            if isinstance(value, str):
                if _looks_like_nested_json_blob(value):
                    for nested_payload in _decode_json_fragments(value):
                        _collect_final_text_candidates(nested_payload, candidates)
                else:
                    _append_text_candidate(candidates, value)

        for value in payload.values():
            if isinstance(value, (dict, list)):
                _collect_final_text_candidates(value, candidates)
    elif isinstance(payload, list):
        for item in payload:
            if isinstance(item, (dict, list)):
                _collect_final_text_candidates(item, candidates)
            elif isinstance(item, str):
                if _looks_like_nested_json_blob(item):
                    for nested_payload in _decode_json_fragments(item):
                        _collect_final_text_candidates(nested_payload, candidates)
                else:
                    _append_text_candidate(candidates, item)


def extract_final_text_from_output(text: str) -> str:
    """
    Best-effort extraction of a user-facing final answer from provider output.
    Falls back to trimmed raw text when no structured candidates are detected.
    """
    raw = text.strip()
    if not raw:
        return ""

    payloads = extract_json_payloads(text)
    if not payloads:
        return raw

    candidates: List[str] = []
    for payload in payloads:
        _collect_final_text_candidates(payload, candidates)

    return _select_best_text_candidate(candidates) if candidates else raw


def extract_json_payloads(text: str) -> List[Any]:
    payloads: List[Any] = []
    seen_signatures = set()

    def add_payload(payload: Any) -> bool:
        try:
            signature = json.dumps(payload, sort_keys=True, ensure_ascii=True)
        except Exception:
            signature = repr(payload)
        if signature in seen_signatures:
            return False
        seen_signatures.add(signature)
        payloads.append(payload)
        return True

    stripped = text.strip()
    if not stripped:
        return payloads

    for payload in _decode_json_fragments(stripped):
        add_payload(payload)

    for match in re.findall(r"```json\s*(.*?)\s*```", text, flags=re.DOTALL | re.IGNORECASE):
        for payload in _decode_json_fragments(match):
            add_payload(payload)

    for line in text.splitlines():
        candidate = line.strip()
        if not candidate:
            continue
        for payload in _decode_json_fragments(candidate):
            add_payload(payload)

    # Recursively extract contract payloads from event-stream text fields.
    index = 0
    while index < len(payloads):
        payload = payloads[index]
        index += 1
        for nested_text in _iter_nested_strings(payload):
            if not _looks_like_nested_json_blob(nested_text):
                continue
            for nested_payload in _decode_json_fragments(nested_text):
                add_payload(nested_payload)

    return payloads


def _validate_finding_item(item: Any) -> Tuple[bool, Optional[Dict[str, Any]]]:
    if not isinstance(item, dict):
        return (False, None)
    required = {"finding_id", "severity", "category", "title", "evidence", "recommendation", "confidence", "fingerprint"}
    if not required.issubset(item.keys()):
        return (False, None)
    if item.get("severity") not in ALLOWED_SEVERITY:
        return (False, None)
    if item.get("category") not in ALLOWED_CATEGORY:
        return (False, None)
    if not isinstance(item.get("title"), str):
        return (False, None)
    if not isinstance(item.get("recommendation"), str):
        return (False, None)
    if not isinstance(item.get("confidence"), (int, float)):
        return (False, None)
    evidence = item.get("evidence")
    if not isinstance(evidence, dict):
        return (False, None)
    if not isinstance(evidence.get("file"), str):
        return (False, None)
    if not isinstance(evidence.get("snippet"), str):
        return (False, None)
    line = evidence.get("line")
    if line is not None and not isinstance(line, int):
        return (False, None)
    symbol = evidence.get("symbol")
    if symbol is not None and not isinstance(symbol, str):
        return (False, None)
    return (True, item)


def inspect_contract_output(text: str) -> Dict[str, Any]:
    """
    Strict contract validation for output shaped as:
    {"findings": [ ... ]}.
    """
    candidates: List[Dict[str, Any]] = []

    for index, payload in enumerate(extract_json_payloads(text)):
        if not isinstance(payload, dict):
            continue
        if "findings" not in payload:
            continue

        valid_findings: List[Dict[str, Any]] = []
        dropped_count = 0
        findings = payload.get("findings")
        if not isinstance(findings, list):
            dropped_count += 1
        else:
            for item in findings:
                ok, normalized = _validate_finding_item(item)
                if ok and normalized is not None:
                    valid_findings.append(normalized)
                else:
                    dropped_count += 1

        candidates.append(
            {
                "index": index,
                "valid_findings": valid_findings,
                "valid_count": len(valid_findings),
                "dropped_count": dropped_count,
                "parse_ok": dropped_count == 0,
            }
        )

    has_contract_envelope = len(candidates) > 0
    if not has_contract_envelope:
        return {
            "parse_ok": False,
            "has_contract_envelope": False,
            "schema_valid_count": 0,
            "dropped_count": 0,
            "findings": [],
            "parse_reason": "no_contract_envelope",
            "candidate_count": 0,
        }

    best = max(
        candidates,
        key=lambda item: (
            1 if item["parse_ok"] else 0,
            int(item["valid_count"]),
            -int(item["dropped_count"]),
            int(item["index"]),
        ),
    )
    parse_reason = "ok" if best["parse_ok"] else ("schema_invalid" if best["dropped_count"] > 0 else "no_valid_findings")

    return {
        "parse_ok": bool(best["parse_ok"]),
        "has_contract_envelope": True,
        "schema_valid_count": int(best["valid_count"]),
        "dropped_count": int(best["dropped_count"]),
        "findings": list(best["valid_findings"]),
        "parse_reason": parse_reason,
        "candidate_count": len(candidates),
    }


def _extract_findings(payload: Any) -> List[Dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        findings = payload.get("findings")
        if isinstance(findings, list):
            return [item for item in findings if isinstance(item, dict)]
        if all(k in payload for k in ("severity", "category", "title")):
            return [payload]
    return []


def _as_optional_int(value: Any) -> Optional[int]:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and value.isdigit():
        return int(value)
    return None


def normalize_findings_from_text(text: str, ctx: NormalizeContext, provider: ProviderId) -> List[NormalizedFinding]:
    normalized: List[NormalizedFinding] = []
    seen_ids = set()

    contract_info = inspect_contract_output(text)
    findings_source = contract_info["findings"] if contract_info["has_contract_envelope"] else []

    if findings_source:
        source_items = findings_source
    else:
        source_items = []
        for payload in extract_json_payloads(text):
            source_items.extend(_extract_findings(payload))

    for item in source_items:
        severity = item.get("severity")
        category = item.get("category")
        title = item.get("title")
        evidence = item.get("evidence")
        recommendation = item.get("recommendation")
        confidence = item.get("confidence")

        if not isinstance(severity, str) or not isinstance(category, str) or not isinstance(title, str):
            continue
        if severity not in ALLOWED_SEVERITY or category not in ALLOWED_CATEGORY:
            continue
        if not isinstance(evidence, dict):
            continue
        if not isinstance(recommendation, str):
            recommendation = ""
        if not isinstance(confidence, (int, float)):
            confidence = 0.0

        file_path = evidence.get("file")
        snippet = evidence.get("snippet")
        if not isinstance(file_path, str) or not isinstance(snippet, str):
            continue

        finding_id = str(item.get("finding_id") or item.get("id") or "")
        if not finding_id:
            finding_id = f"{provider}:{len(normalized) + 1}"
        if finding_id in seen_ids:
            continue
        seen_ids.add(finding_id)

        fingerprint = str(item.get("fingerprint") or f"{provider}:{title}:{file_path}:{evidence.get('line')}")

        normalized.append(
            NormalizedFinding(
                task_id=ctx.task_id,
                provider=provider,
                finding_id=finding_id,
                severity=severity,  # type: ignore[arg-type]
                category=category,  # type: ignore[arg-type]
                title=title,
                evidence=Evidence(
                    file=file_path,
                    line=_as_optional_int(evidence.get("line")),
                    snippet=snippet,
                    symbol=evidence.get("symbol") if isinstance(evidence.get("symbol"), str) else None,
                ),
                recommendation=recommendation,
                confidence=max(0.0, min(1.0, float(confidence))),
                fingerprint=fingerprint,
                raw_ref=ctx.raw_ref,
            )
        )

    return normalized
