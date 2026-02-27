from __future__ import annotations

import unittest
from dataclasses import fields

from runtime.adapters import ClaudeAdapter, CodexAdapter, GeminiAdapter, OpenCodeAdapter, QwenAdapter
from runtime.artifacts import ARTIFACT_LAYOUT_VERSION, ROOT_DIRS, ROOT_FILES, expected_paths
from runtime.contracts import CAPABILITY_TIERS, PROVIDER_IDS, ProviderAdapter
from runtime.types import RUN_RESULT_FIELDS, RUN_RESULT_SCHEMA_VERSION, RunResult


class ContractFreezeTests(unittest.TestCase):
    def test_provider_and_capability_sets_are_frozen(self) -> None:
        self.assertEqual(tuple(PROVIDER_IDS), ("claude", "codex", "gemini", "opencode", "qwen"))
        self.assertEqual(tuple(CAPABILITY_TIERS), ("C0", "C1", "C2", "C3", "C4", "C5", "C6"))

    def test_provider_adapter_protocol_shape(self) -> None:
        for method in ("detect", "capabilities", "run", "poll", "cancel", "normalize"):
            self.assertIn(method, ProviderAdapter.__dict__)

    def test_run_result_fields_are_frozen(self) -> None:
        names = tuple(field.name for field in fields(RunResult))
        self.assertEqual(names, RUN_RESULT_FIELDS)
        self.assertEqual(RUN_RESULT_SCHEMA_VERSION, "stage-a-v2")

    def test_artifact_layout_contract(self) -> None:
        self.assertEqual(ARTIFACT_LAYOUT_VERSION, "stage-a-v1")
        self.assertEqual(ROOT_FILES, ("summary.md", "decision.md", "findings.json", "run.json"))
        self.assertEqual(ROOT_DIRS, ("providers", "raw"))

        paths = expected_paths("/tmp/artifacts", "task-123", ("claude", "codex"))
        self.assertTrue(str(paths["summary.md"]).endswith("/task-123/summary.md"))
        self.assertTrue(str(paths["providers/claude.json"]).endswith("/task-123/providers/claude.json"))
        self.assertTrue(str(paths["raw/codex.stderr.log"]).endswith("/task-123/raw/codex.stderr.log"))

    def test_provider_permission_key_matrix_contract(self) -> None:
        self.assertEqual(ClaudeAdapter().supported_permission_keys(), ["permission_mode"])
        self.assertEqual(CodexAdapter().supported_permission_keys(), ["sandbox"])
        self.assertEqual(GeminiAdapter().supported_permission_keys(), [])
        self.assertEqual(OpenCodeAdapter().supported_permission_keys(), [])
        self.assertEqual(QwenAdapter().supported_permission_keys(), [])


if __name__ == "__main__":
    unittest.main()
