from __future__ import annotations

import json
import unittest
from dataclasses import fields
from pathlib import Path

from runtime.adapters import (
    ClaudeAdapter,
    CodexAdapter,
    CopilotAdapter,
    CursorAdapter,
    GeminiAdapter,
    GrokAdapter,
    HermesAdapter,
    OpenCodeAdapter,
    PiAdapter,
    QwenAdapter,
)
from runtime.artifacts import ARTIFACT_LAYOUT_VERSION, ROOT_DIRS, ROOT_FILES, expected_paths, validate_task_id
from runtime.contracts import CAPABILITY_TIERS, PROVIDER_IDS, ProviderAdapter
from runtime.types import RUN_RESULT_FIELDS, RUN_RESULT_SCHEMA_VERSION, RunResult


class ContractFreezeTests(unittest.TestCase):
    def test_provider_and_capability_sets_are_frozen(self) -> None:
        self.assertEqual(tuple(PROVIDER_IDS), ("claude", "codex", "gemini", "opencode", "qwen", "hermes", "pi", "copilot", "grok", "cursor"))
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
        self.assertEqual(CodexAdapter().supported_permission_keys(), ["sandbox", "approval_policy", "bypass"])
        self.assertEqual(GeminiAdapter().supported_permission_keys(), ["approval_mode"])
        self.assertEqual(OpenCodeAdapter().supported_permission_keys(), ["agent_mode", "auto"])
        self.assertEqual(QwenAdapter().supported_permission_keys(), ["approval_mode"])
        self.assertEqual(HermesAdapter().supported_permission_keys(), ["yolo"])
        self.assertEqual(PiAdapter().supported_permission_keys(), ["tool_profile"])
        self.assertEqual(CopilotAdapter().supported_permission_keys(), ["access"])
        self.assertEqual(GrokAdapter().supported_permission_keys(), ["permission_mode", "approval_mode"])
        self.assertEqual(CursorAdapter().supported_permission_keys(), ["mode", "force", "sandbox"])

    def test_provider_contract_docs_list_all_builtin_providers(self) -> None:
        repo_root = Path(__file__).resolve().parent.parent
        documents = [
            repo_root / "docs" / "implementation" / "step0-interface-freeze.md",
            repo_root / "docs" / "contracts" / "provider-permissions-v0.1.x.md",
        ]
        for document in documents:
            text = document.read_text(encoding="utf-8")
            for provider in PROVIDER_IDS:
                with self.subTest(document=document.name, provider=provider):
                    self.assertIn(provider, text)

    def test_validate_task_id_rejects_absolute_path(self) -> None:
        with self.assertRaises(ValueError):
            validate_task_id("/etc/passwd")

    def test_validate_task_id_rejects_dot_dot(self) -> None:
        with self.assertRaises(ValueError):
            validate_task_id("../etc")

    def test_validate_task_id_rejects_path_separator(self) -> None:
        with self.assertRaises(ValueError):
            validate_task_id("task/123")

    def test_validate_task_id_rejects_empty(self) -> None:
        with self.assertRaises(ValueError):
            validate_task_id("")

    def test_validate_task_id_rejects_control_chars(self) -> None:
        with self.assertRaises(ValueError):
            validate_task_id("task\x00evil")

    def test_validate_task_id_accepts_valid(self) -> None:
        validate_task_id("task-123")
        validate_task_id("session-debate-123.abc_456")
        validate_task_id("my.task.v1")

    def test_validate_task_id_rejects_backslash_separator(self) -> None:
        with self.assertRaises(ValueError):
            validate_task_id("task\\123")

    def test_validate_task_id_rejects_whitespace_only(self) -> None:
        with self.assertRaises(ValueError):
            validate_task_id("   ")

    def test_validate_task_id_rejects_single_dot(self) -> None:
        with self.assertRaises(ValueError):
            validate_task_id(".")

    def test_claude_default_permission_is_plan(self) -> None:
        """Claude adapter default --permission-mode must be 'plan'."""
        from runtime.contracts import TaskInput
        adapter = ClaudeAdapter()
        task = TaskInput(
            task_id="test", prompt="review", repo_root="/tmp",
            target_paths=["."], timeout_seconds=60,
        )
        cmd = adapter._build_command(task)
        self.assertIn("--permission-mode", cmd)
        mode_idx = cmd.index("--permission-mode")
        self.assertEqual(cmd[mode_idx + 1], "plan",
                         "Claude default permission mode must be 'plan'")

    def test_claude_permission_override(self) -> None:
        """Claude adapter respects provider_permissions override."""
        from runtime.contracts import TaskInput
        adapter = ClaudeAdapter()
        task = TaskInput(
            task_id="test", prompt="review", repo_root="/tmp",
            target_paths=["."], timeout_seconds=60,
            metadata={"provider_permissions": {"permission_mode": "accept-edits"}},
        )
        cmd = adapter._build_command(task)
        mode_idx = cmd.index("--permission-mode")
        self.assertEqual(cmd[mode_idx + 1], "accept-edits",
                         "Claude permission mode should be overridden")

    def test_codex_default_sandbox_is_workspace_write(self) -> None:
        """Codex adapter default --sandbox must be 'workspace-write'."""
        from runtime.contracts import TaskInput
        adapter = CodexAdapter()
        task = TaskInput(
            task_id="test", prompt="review", repo_root="/tmp",
            target_paths=["."], timeout_seconds=60,
        )
        cmd = adapter._build_command(task)
        self.assertIn("--sandbox", cmd)
        sandbox_idx = cmd.index("--sandbox")
        self.assertEqual(cmd[sandbox_idx + 1], "workspace-write",
                         "Codex default sandbox must be 'workspace-write'")

    def test_codex_sandbox_override(self) -> None:
        """Codex adapter respects provider_permissions override."""
        from runtime.contracts import TaskInput
        adapter = CodexAdapter()
        task = TaskInput(
            task_id="test", prompt="review", repo_root="/tmp",
            target_paths=["."], timeout_seconds=60,
            metadata={"provider_permissions": {"sandbox": "read-only"}},
        )
        cmd = adapter._build_command(task)
        sandbox_idx = cmd.index("--sandbox")
        self.assertEqual(cmd[sandbox_idx + 1], "read-only",
                         "Codex sandbox should be overridden")

    def test_review_findings_schema_is_openai_strict_compatible(self) -> None:
        schema_path = Path(__file__).resolve().parent.parent / "runtime" / "schemas" / "review_findings.schema.json"
        schema = json.loads(schema_path.read_text())

        def _check(obj: dict, path: str) -> None:
            if isinstance(obj, dict):
                if "properties" in obj:
                    self.assertIn("additionalProperties", obj, f"{path}: missing additionalProperties")
                    self.assertFalse(obj["additionalProperties"], f"{path}: additionalProperties must be false")
                if "type" in obj and isinstance(obj["type"], list):
                    self.fail(f"{path}: type must not be an array, got {obj['type']}")
                if "required" in obj:
                    props = set(obj.get("properties", {}))
                    for req in obj["required"]:
                        self.assertIn(req, props, f"{path}: required key '{req}' not in properties")
                for key, val in obj.get("properties", {}).items():
                    _check(val, f"{path}.properties.{key}")
                if "items" in obj:
                    _check(obj["items"], f"{path}.items")

        _check(schema, "root")


if __name__ == "__main__":
    unittest.main()
