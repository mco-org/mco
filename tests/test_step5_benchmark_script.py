from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
import textwrap
import unittest
from datetime import date
from pathlib import Path


class Step5BenchmarkScriptTests(unittest.TestCase):
    def test_script_keeps_parse_and_findings_metrics_separate(self) -> None:
        if shutil.which("jq") is None:
            self.skipTest("jq is required for benchmark script")

        repo_root = Path(__file__).resolve().parents[1]
        source_script = repo_root / "scripts" / "run_step5_parallel_benchmark.sh"

        with tempfile.TemporaryDirectory() as tmpdir:
            fake_root = Path(tmpdir)
            (fake_root / "scripts").mkdir(parents=True, exist_ok=True)
            target_script = fake_root / "scripts" / "run_step5_parallel_benchmark.sh"
            target_script.write_text(source_script.read_text(encoding="utf-8"), encoding="utf-8")
            target_script.chmod(0o755)

            fake_mco = fake_root / "mco"
            fake_mco.write_text(
                textwrap.dedent(
                    """\
                    #!/usr/bin/env python3
                    import json
                    import os
                    import pathlib
                    import sys

                    def get_arg(name: str, default: str = "") -> str:
                        if name in sys.argv:
                            idx = sys.argv.index(name)
                            if idx + 1 < len(sys.argv):
                                return sys.argv[idx + 1]
                        return default

                    parallelism = int(get_arg("--max-provider-parallelism", "0"))
                    task_id = get_arg("--task-id", "task-smoke")
                    repo_root = get_arg("--repo", os.getcwd())
                    artifact_root = os.path.join(repo_root, "reports", "review", task_id)
                    pathlib.Path(os.path.join(artifact_root, "providers")).mkdir(parents=True, exist_ok=True)

                    providers = ["claude", "codex", "gemini", "opencode", "qwen"]
                    if parallelism == 1:
                        provider_results = {
                            "claude": {"parse_ok": True, "findings_count": 1},
                            "codex": {"parse_ok": True, "findings_count": 1},
                            "gemini": {"parse_ok": True, "findings_count": 1},
                            "opencode": {"parse_ok": True, "findings_count": 1},
                            "qwen": {"parse_ok": True, "findings_count": 0},
                        }
                        payload = {
                            "task_id": task_id,
                            "artifact_root": artifact_root,
                            "decision": "PASS",
                            "terminal_state": "COMPLETED",
                            "findings_count": 4,
                            "parse_success_count": 5,
                            "parse_failure_count": 0,
                            "schema_valid_count": 4,
                            "dropped_findings_count": 0,
                        }
                    else:
                        provider_results = {provider: {"parse_ok": True, "findings_count": 1} for provider in providers}
                        payload = {
                            "task_id": task_id,
                            "artifact_root": artifact_root,
                            "decision": "PASS",
                            "terminal_state": "COMPLETED",
                            "findings_count": 5,
                            "parse_success_count": 5,
                            "parse_failure_count": 0,
                            "schema_valid_count": 5,
                            "dropped_findings_count": 0,
                        }

                    run_payload = {
                        "task_id": task_id,
                        "provider_results": provider_results,
                    }
                    pathlib.Path(artifact_root).mkdir(parents=True, exist_ok=True)
                    pathlib.Path(os.path.join(artifact_root, "run.json")).write_text(
                        json.dumps(run_payload, ensure_ascii=True), encoding="utf-8"
                    )

                    print(json.dumps(payload, ensure_ascii=True))
                    """
                ),
                encoding="utf-8",
            )
            fake_mco.chmod(0o755)

            proc = subprocess.run(
                [str(target_script)],
                cwd=str(fake_root),
                text=True,
                capture_output=True,
            )
            self.assertEqual(proc.returncode, 0, msg=f"stdout:\n{proc.stdout}\nstderr:\n{proc.stderr}")

            date_str = date.today().isoformat()
            summary_path = fake_root / "reports" / "adapter-contract" / date_str / "step5-parallel-benchmark-summary.json"
            self.assertTrue(summary_path.exists())

            summary = json.loads(summary_path.read_text(encoding="utf-8"))
            self.assertTrue(summary["benchmark_ok"])

            serial = summary["serial"]
            parallel = summary["parallel"]

            self.assertEqual(serial["parse_success_count"], 5)
            self.assertEqual(serial["effective_findings_count"], 4)
            self.assertEqual(serial["providers_total"], 5)
            self.assertEqual(serial["zero_finding_provider_count"], 1)
            self.assertEqual(serial["command_exit_code"], 0)
            self.assertAlmostEqual(float(serial["parse_success_rate"]), 1.0)

            self.assertEqual(parallel["parse_success_count"], 5)
            self.assertEqual(parallel["effective_findings_count"], 5)
            self.assertEqual(parallel["providers_total"], 5)
            self.assertEqual(parallel["zero_finding_provider_count"], 0)
            self.assertEqual(parallel["command_exit_code"], 0)
            self.assertAlmostEqual(float(parallel["parse_success_rate"]), 1.0)


if __name__ == "__main__":
    unittest.main()
