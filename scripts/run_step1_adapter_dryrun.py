#!/usr/bin/env python3
from __future__ import annotations

import json
import sys
import time
from datetime import date
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from runtime.adapters import ClaudeAdapter, CodexAdapter
from runtime.contracts import TaskInput


PROMPT = "Reply with exactly OK"


def run_one(adapter: object, repo_root: str, artifact_root: str) -> dict:
    adapter_id = adapter.id  # type: ignore[attr-defined]
    task_id = f"step1-{adapter_id}-{int(time.time())}"
    task = TaskInput(
        task_id=task_id,
        prompt=PROMPT,
        repo_root=repo_root,
        target_paths=["README.md"],
        metadata={"artifact_root": artifact_root},
    )
    ref = adapter.run(task)  # type: ignore[attr-defined]

    started = time.time()
    status = None
    while time.time() - started < 180:
        status = adapter.poll(ref)  # type: ignore[attr-defined]
        if status.completed:
            break
        time.sleep(0.5)
    if status is None or not status.completed:
        raise RuntimeError(f"{adapter_id} dry-run timeout")

    stdout_path = Path(ref.artifact_path) / "raw" / f"{adapter_id}.stdout.log"
    raw = stdout_path.read_text(encoding="utf-8") if stdout_path.exists() else ""
    transport = adapter.decode_transport(raw)  # type: ignore[attr-defined]

    return {
        "provider": adapter_id,
        "task_id": task_id,
        "run_id": ref.run_id,
        "attempt_state": status.attempt_state,
        "completed": status.completed,
        "error_kind": status.error_kind.value if status.error_kind else None,
        "exit_code": status.exit_code,
        "transport_status": transport.status,
        "answer_chars": len(transport.final_answer),
        "usage": transport.usage,
        "artifact_path": ref.artifact_path,
        "provider_output": status.output_path,
    }


def main() -> int:
    repo_root = str(ROOT_DIR)
    day = str(date.today())
    report_dir = Path(repo_root) / "reports" / "adapter-contract" / day
    report_dir.mkdir(parents=True, exist_ok=True)
    artifact_root = str(report_dir / "step1-adapter-dryrun-artifacts")

    results = []
    for adapter in (ClaudeAdapter(), CodexAdapter()):
        results.append(run_one(adapter, repo_root, artifact_root))

    result_json = report_dir / "step1-adapter-dryrun.json"
    result_json.write_text(json.dumps(results, ensure_ascii=True, indent=2), encoding="utf-8")

    md_lines = [f"# Step1 Adapter Dry-run ({day})", "", "- Providers: claude + codex", ""]
    for item in results:
        md_lines.append(f"## {item['provider']}")
        md_lines.append(f"- attempt_state: {item['attempt_state']}")
        md_lines.append(f"- completed: {item['completed']}")
        md_lines.append(f"- exit_code: {item['exit_code']}")
        md_lines.append(f"- error_kind: {item['error_kind']}")
        md_lines.append(f"- transport_status: {item['transport_status']}")
        md_lines.append(f"- answer_chars: {item['answer_chars']}")
        md_lines.append(f"- usage: {item['usage']}")
        md_lines.append(f"- artifact_path: `{item['artifact_path']}`")
        md_lines.append("")

    report_md = report_dir / "step1-adapter-dryrun.md"
    report_md.write_text("\n".join(md_lines), encoding="utf-8")

    for item in results:
        if not item["completed"] or item["attempt_state"] != "SUCCEEDED":
            raise RuntimeError(f"{item['provider']} dry-run failed")

    print(f"Dry-run report: {report_md}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
