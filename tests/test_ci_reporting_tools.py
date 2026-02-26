from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path


class CiReportingToolsTests(unittest.TestCase):
    def test_render_step5_report_uses_fixed_template(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        template_path = repo_root / "docs" / "templates" / "step5-benchmark-report.md.tpl"
        script_path = repo_root / "scripts" / "render_step5_report.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp = Path(tmpdir)
            summary_path = tmp / "summary.json"
            output_path = tmp / "report.md"
            payload = {
                "generated_at": "2026-02-26T07:21:48Z",
                "providers": "claude,codex,gemini,opencode,qwen",
                "serial": {
                    "task_id": "serial",
                    "wall_time_seconds": 166,
                    "parse_success_count": 5,
                    "parse_failure_count": 0,
                    "providers_total": 5,
                    "parse_success_rate": 1,
                    "effective_findings_count": 4,
                    "zero_finding_provider_count": 1,
                    "command_exit_code": 0,
                },
                "parallel": {
                    "task_id": "parallel",
                    "wall_time_seconds": 79,
                    "parse_success_count": 5,
                    "parse_failure_count": 0,
                    "providers_total": 5,
                    "parse_success_rate": 1,
                    "effective_findings_count": 5,
                    "zero_finding_provider_count": 0,
                    "command_exit_code": 0,
                },
                "latency_reduction_percent": 52.4,
                "metric_note": "note",
            }
            summary_path.write_text(json.dumps(payload, ensure_ascii=True), encoding="utf-8")

            proc = subprocess.run(
                [
                    str(script_path),
                    "--template",
                    str(template_path),
                    "--summary-json",
                    str(summary_path),
                    "--output",
                    str(output_path),
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")
            report = output_path.read_text(encoding="utf-8")
            self.assertIn("effective findings: `4`", report)
            self.assertIn("parse success rate: `5/5 (100.0%)`", report)
            self.assertIn("Metrics note: note", report)

    def test_collect_ci_artifacts_merges_workflows(self) -> None:
        repo_root = Path(__file__).resolve().parents[1]
        script_path = repo_root / "scripts" / "collect_ci_artifacts.py"

        with tempfile.TemporaryDirectory() as tmpdir:
            report_root = Path(tmpdir) / "reports" / "adapter-contract" / "2026-02-26"
            report_root.mkdir(parents=True, exist_ok=True)
            (report_root / "runtime-gh-report.md").write_text("ok", encoding="utf-8")
            (report_root / "step5-parallel-benchmark.md").write_text("ok", encoding="utf-8")
            (report_root / "step5-parallel-benchmark-summary.json").write_text("{}", encoding="utf-8")

            first = subprocess.run(
                [
                    str(script_path),
                    "--report-root",
                    str(report_root),
                    "--workflow",
                    "gate",
                    "--run-id",
                    "100",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(first.returncode, 0, msg=f"stdout:\n{first.stdout}\nstderr:\n{first.stderr}")

            second = subprocess.run(
                [
                    str(script_path),
                    "--report-root",
                    str(report_root),
                    "--workflow",
                    "benchmark",
                    "--run-id",
                    "200",
                ],
                text=True,
                capture_output=True,
            )
            self.assertEqual(second.returncode, 0, msg=f"stdout:\n{second.stdout}\nstderr:\n{second.stderr}")

            index_path = report_root / "ci-artifact-index.json"
            markdown_path = report_root / "ci-artifact-index.md"
            self.assertTrue(index_path.exists())
            self.assertTrue(markdown_path.exists())

            index = json.loads(index_path.read_text(encoding="utf-8"))
            workflows = index.get("workflows", {})
            self.assertIn("gate", workflows)
            self.assertIn("benchmark", workflows)
            self.assertEqual(workflows["gate"]["run_id"], "100")
            self.assertEqual(workflows["benchmark"]["run_id"], "200")
            self.assertTrue(
                workflows["gate"]["key_artifacts"]["runtime_gate_report"]["exists"]
            )


if __name__ == "__main__":
    unittest.main()
