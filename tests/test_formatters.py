from __future__ import annotations

import unittest

from runtime.formatters import format_markdown_pr, format_sarif


class FormatterTests(unittest.TestCase):
    def test_markdown_pr_escapes_cells_and_includes_summary(self) -> None:
        payload = {
            "decision": "PASS",
            "terminal_state": "COMPLETED",
            "provider_success_count": 2,
            "provider_failure_count": 0,
            "findings_count": 1,
        }
        findings = [
            {
                "severity": "high",
                "category": "security",
                "title": "Unsafe | shell usage",
                "recommendation": "Use allowlist\nand avoid interpolation",
                "confidence": 0.8,
                "evidence": {"file": "a.py", "line": 10, "snippet": "x"},
            }
        ]
        text = format_markdown_pr(payload, findings)
        self.assertIn("## MCO Review Summary", text)
        self.assertIn("Unsafe \\| shell usage", text)
        self.assertIn("allowlist<br>and avoid interpolation", text)
        self.assertIn("`a.py:10`", text)

    def test_markdown_pr_handles_empty_findings(self) -> None:
        payload = {
            "decision": "PASS",
            "terminal_state": "COMPLETED",
            "provider_success_count": 1,
            "provider_failure_count": 0,
            "findings_count": 0,
        }
        text = format_markdown_pr(payload, [])
        self.assertIn("_No findings reported._", text)

    def test_sarif_maps_severity_and_locations(self) -> None:
        payload = {"decision": "PASS", "terminal_state": "COMPLETED", "findings_count": 1}
        findings = [
            {
                "severity": "high",
                "category": "security",
                "title": "Unsafe shell",
                "recommendation": "Use allowlist",
                "confidence": 0.9,
                "fingerprint": "fp-1",
                "detected_by": ["claude", "qwen"],
                "evidence": {"file": "runtime/cli.py", "line": 12, "snippet": "os.system(x)"},
            }
        ]
        sarif = format_sarif(payload, findings)
        self.assertEqual(sarif.get("version"), "2.1.0")
        runs = sarif.get("runs", [])
        self.assertEqual(len(runs), 1)
        results = runs[0].get("results", [])
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0].get("level"), "warning")
        self.assertEqual(
            results[0]["locations"][0]["physicalLocation"]["artifactLocation"]["uri"],  # type: ignore[index]
            "runtime/cli.py",
        )
        self.assertEqual(results[0]["properties"]["detected_by"], ["claude", "qwen"])  # type: ignore[index]

    def test_sarif_handles_empty_findings(self) -> None:
        sarif = format_sarif({"decision": "PASS", "terminal_state": "COMPLETED", "findings_count": 0}, [])
        runs = sarif.get("runs", [])
        self.assertEqual(len(runs), 1)
        self.assertEqual(runs[0].get("results"), [])


if __name__ == "__main__":
    unittest.main()
