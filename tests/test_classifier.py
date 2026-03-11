from __future__ import annotations

import unittest

from runtime.bridge.classifier import CATEGORY_SIGNALS, classify_task


class TestClassifyTask(unittest.TestCase):
    def test_security_prompt_classified(self):
        result = classify_task("Review for security vulnerabilities", findings=[])
        self.assertEqual(result, "security")

    def test_findings_distribution_overrides_prompt(self):
        findings = [
            {"category": "performance"},
            {"category": "performance"},
            {"category": "performance"},
            {"category": "security"},
        ]
        result = classify_task(
            "Review for security vulnerabilities",
            findings=findings,
        )
        self.assertEqual(result, "performance")

    def test_empty_input_defaults_to_general(self):
        result = classify_task("please review this code", findings=[])
        self.assertEqual(result, "general")

    def test_mixed_signals(self):
        findings = [
            {"category": "logic"},
            {"category": "logic"},
        ]
        result = classify_task(
            "check for bugs and race conditions",
            findings=findings,
        )
        self.assertEqual(result, "logic")

    def test_category_signals_keys(self):
        expected = {"security", "performance", "logic", "architecture", "style"}
        self.assertEqual(set(CATEGORY_SIGNALS.keys()), expected)


if __name__ == "__main__":
    unittest.main()
