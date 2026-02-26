#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
from string import Template
from typing import Any, Dict


def _percent_text(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value * 100:.1f}%"


def _reduction_text(value: Any) -> str:
    if not isinstance(value, (int, float)):
        return "n/a"
    return f"{value:.1f}%"


def _ratio_text(success: Any, total: Any, rate: Any) -> str:
    success_text = str(success if isinstance(success, (int, float)) else 0)
    total_text = str(total if isinstance(total, (int, float)) else 0)
    return f"{success_text}/{total_text} ({_percent_text(rate)})"


def _value(payload: Dict[str, Any], key: str, default: Any) -> Any:
    value = payload.get(key)
    return default if value is None else value


def build_render_context(summary: Dict[str, Any], summary_json_path: str) -> Dict[str, str]:
    serial = summary.get("serial", {}) if isinstance(summary.get("serial"), dict) else {}
    parallel = summary.get("parallel", {}) if isinstance(summary.get("parallel"), dict) else {}

    return {
        "date": str(summary.get("generated_at", ""))[:10],
        "providers": str(summary.get("providers", "unknown")),
        "serial_task_id": str(_value(serial, "task_id", "unknown")),
        "serial_wall_time": f"{_value(serial, 'wall_time_seconds', 0)}s",
        "serial_parse_success": str(_value(serial, "parse_success_count", 0)),
        "serial_parse_failure": str(_value(serial, "parse_failure_count", 0)),
        "serial_parse_ratio": _ratio_text(
            _value(serial, "parse_success_count", 0),
            _value(serial, "providers_total", 0),
            _value(serial, "parse_success_rate", None),
        ),
        "serial_effective_findings": str(_value(serial, "effective_findings_count", 0)),
        "serial_zero_finding_providers": str(_value(serial, "zero_finding_provider_count", 0)),
        "serial_exit_code": str(_value(serial, "command_exit_code", 999)),
        "parallel_task_id": str(_value(parallel, "task_id", "unknown")),
        "parallel_wall_time": f"{_value(parallel, 'wall_time_seconds', 0)}s",
        "parallel_parse_success": str(_value(parallel, "parse_success_count", 0)),
        "parallel_parse_failure": str(_value(parallel, "parse_failure_count", 0)),
        "parallel_parse_ratio": _ratio_text(
            _value(parallel, "parse_success_count", 0),
            _value(parallel, "providers_total", 0),
            _value(parallel, "parse_success_rate", None),
        ),
        "parallel_effective_findings": str(_value(parallel, "effective_findings_count", 0)),
        "parallel_zero_finding_providers": str(_value(parallel, "zero_finding_provider_count", 0)),
        "parallel_exit_code": str(_value(parallel, "command_exit_code", 999)),
        "latency_reduction": _reduction_text(summary.get("latency_reduction_percent")),
        "metric_note": str(summary.get("metric_note", "")),
        "summary_json_path": summary_json_path,
    }


def render_report(template_path: Path, summary_path: Path, output_path: Path) -> None:
    template_text = template_path.read_text(encoding="utf-8")
    summary = json.loads(summary_path.read_text(encoding="utf-8"))
    context = build_render_context(summary, str(summary_path))
    rendered = Template(template_text).substitute(context)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(rendered, encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Render Step5 benchmark report from fixed template.")
    parser.add_argument("--template", required=True, help="Path to markdown template")
    parser.add_argument("--summary-json", required=True, help="Path to benchmark summary json")
    parser.add_argument("--output", required=True, help="Path to output markdown report")
    args = parser.parse_args()

    render_report(Path(args.template), Path(args.summary_json), Path(args.output))
    print(f"Rendered report: {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
