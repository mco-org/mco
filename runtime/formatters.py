from __future__ import annotations

import hashlib
import re
from typing import Dict, List


_SEVERITY_ORDER = ("critical", "high", "medium", "low")
_SARIF_LEVEL_BY_SEVERITY = {
    "critical": "error",
    "high": "warning",
    "medium": "note",
    "low": "note",
}


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


def format_markdown_pr(payload: Dict[str, object], findings: List[Dict[str, object]]) -> str:
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
    lines.append("### Findings")
    lines.append("")
    if not findings:
        lines.append("_No findings reported._")
        return "\n".join(lines)

    lines.extend(
        [
            "| Severity | Category | Title | Location | Confidence | Recommendation |",
            "|---|---|---|---|---:|---|",
        ]
    )
    ordered_findings = sorted(
        findings,
        key=lambda item: (
            _SEVERITY_ORDER.index(str(item.get("severity", "low")).lower())
            if str(item.get("severity", "low")).lower() in _SEVERITY_ORDER
            else len(_SEVERITY_ORDER),
            _finding_location(item),
            str(item.get("title", "")),
        ),
    )
    for finding in ordered_findings:
        confidence_value = finding.get("confidence")
        if isinstance(confidence_value, (int, float)):
            confidence_text = f"{float(confidence_value):.2f}"
        else:
            confidence_text = "-"
        lines.append(
            "| "
            + " | ".join(
                [
                    f"`{_escape_markdown_cell(str(finding.get('severity', '-')).lower())}`",
                    _escape_markdown_cell(finding.get("category", "-")),
                    _escape_markdown_cell(finding.get("title", "-")),
                    f"`{_escape_markdown_cell(_finding_location(finding))}`",
                    confidence_text,
                    _escape_markdown_cell(finding.get("recommendation", "-")),
                ]
            )
            + " |"
        )
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

        result_payload: Dict[str, object] = {
            "ruleId": rule_id,
            "level": level,
            "message": {"text": title},
            "properties": {
                "category": category,
                "severity": severity,
                "confidence": confidence_value,
                "detected_by": detected_by_value,
                "fingerprint": str(finding.get("fingerprint", "")),
            },
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
