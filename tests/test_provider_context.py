"""Tests for provider context policy (--provider-context-json)."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from runtime.adapters.claude import ClaudeAdapter
from runtime.adapters.codex import CodexAdapter
from runtime.adapters.hermes import HermesAdapter
from runtime.adapters.opencode import OpenCodeAdapter
from runtime.adapters.pi import PiAdapter
from runtime.cli import (
    _parse_provider_context_json,
    _merge_provider_context,
    _resolve_config,
    build_parser,
)
from runtime.config import ReviewConfig, ReviewPolicy
from runtime.contracts import (
    CapabilitySet,
    NormalizeContext,
    ProviderPresence,
    TaskInput,
    TaskRunRef,
    TaskStatus,
)
from runtime.review_engine import ReviewRequest, run_review


class ContextAwareFakeAdapter:
    def __init__(self, provider: str, supported_context_keys: list[str]) -> None:
        self.id = provider
        self._supported_context_keys = supported_context_keys
        self.last_metadata: dict | None = None

    def detect(self) -> ProviderPresence:
        return ProviderPresence(provider=self.id, detected=True, binary_path="/bin/fake", version="1.0", auth_ok=True)

    def capabilities(self) -> CapabilitySet:
        return CapabilitySet(
            tiers=["C0", "C1", "C2"],
            supports_native_async=False,
            supports_poll_endpoint=False,
            supports_resume_after_restart=False,
            supports_schema_enforcement=False,
            min_supported_version="1.0",
            tested_os=["macos"],
        )

    def supported_context_keys(self) -> list[str]:
        return list(self._supported_context_keys)

    def run(self, input_task: TaskInput) -> TaskRunRef:
        self.last_metadata = dict(input_task.metadata)
        artifact_root = Path(input_task.metadata["artifact_root"]) / input_task.task_id
        raw_dir = artifact_root / "raw"
        providers_dir = artifact_root / "providers"
        raw_dir.mkdir(parents=True, exist_ok=True)
        providers_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / f"{self.id}.stdout.log").write_text("OK", encoding="utf-8")
        (raw_dir / f"{self.id}.stderr.log").write_text("", encoding="utf-8")
        (providers_dir / f"{self.id}.json").write_text(json.dumps({"provider": self.id}), encoding="utf-8")
        return TaskRunRef(
            task_id=input_task.task_id,
            provider=self.id,
            run_id=f"{self.id}-run",
            artifact_path=str(artifact_root),
            started_at="2026-06-27T00:00:00Z",
            pid=123,
        )

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        return TaskStatus(
            task_id=ref.task_id,
            provider=ref.provider,
            run_id=ref.run_id,
            attempt_state="SUCCEEDED",
            completed=True,
            heartbeat_at="2026-06-27T00:00:01Z",
            output_path=f"{ref.artifact_path}/providers/{self.id}.json",
            error_kind=None,
            exit_code=0,
            message="completed",
        )

    def cancel(self, ref: TaskRunRef) -> None:
        _ = ref

    def normalize(self, raw: object, ctx: NormalizeContext):
        return []


class TestProviderContextConfig(unittest.TestCase):
    def test_review_policy_defaults(self) -> None:
        self.assertEqual(ReviewPolicy().provider_context, {})

    def test_review_policy_with_context(self) -> None:
        policy = ReviewPolicy(provider_context={"pi": {"skills": "disabled", "context_files": False}})
        self.assertEqual(policy.provider_context["pi"]["skills"], "disabled")
        self.assertFalse(policy.provider_context["pi"]["context_files"])

    def test_review_config_defaults(self) -> None:
        self.assertEqual(ReviewConfig().policy.provider_context, {})

    def test_parse_provider_context_json_skills_disabled(self) -> None:
        parsed = _parse_provider_context_json('{"pi":{"skills":"disabled","context_files":false}}')
        self.assertEqual(parsed["pi"]["skills"], "disabled")
        self.assertFalse(parsed["pi"]["context_files"])

    def test_parse_provider_context_json_skills_ambient(self) -> None:
        parsed = _parse_provider_context_json('{"pi":{"skills":"ambient"}}')
        self.assertEqual(parsed["pi"]["skills"], "ambient")

    def test_parse_provider_context_json_skills_list(self) -> None:
        parsed = _parse_provider_context_json('{"hermes":{"skills":["github-auth","my-skill"]}}')
        self.assertEqual(parsed["hermes"]["skills"], ["github-auth", "my-skill"])

    def test_parse_provider_context_json_rejects_skills_boolean(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be 'disabled', 'ambient', or a list"):
            _parse_provider_context_json('{"pi":{"skills":true}}')

    def test_parse_provider_context_json_rejects_skills_bad_string(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be 'disabled' or 'ambient'"):
            _parse_provider_context_json('{"pi":{"skills":"enabled"}}')

    def test_parse_provider_context_json_rejects_context_files_non_bool(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            _parse_provider_context_json('{"pi":{"context_files":"yes"}}')

    def test_parse_provider_context_json_rejects_extensions_non_bool(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a boolean"):
            _parse_provider_context_json('{"pi":{"extensions":1}}')

    def test_parse_provider_context_json_rejects_forbidden_key_tools(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbidden"):
            _parse_provider_context_json('{"pi":{"tools":"bash"}}')

    def test_parse_provider_context_json_rejects_forbidden_key_yolo(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbidden"):
            _parse_provider_context_json('{"hermes":{"yolo":true}}')

    def test_parse_provider_context_json_rejects_forbidden_key_accept_hooks(self) -> None:
        with self.assertRaisesRegex(ValueError, "forbidden"):
            _parse_provider_context_json('{"hermes":{"accept_hooks":true}}')

    def test_parse_provider_context_json_allows_provider_specific_key(self) -> None:
        parsed = _parse_provider_context_json('{"my-agent":{"custom_mode":"safe"}}')
        self.assertEqual(parsed["my-agent"]["custom_mode"], "safe")

    def test_parse_provider_context_json_rejects_control_chars_in_skill_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "control characters"):
            _parse_provider_context_json('{"hermes":{"skills":["bad\\u0001skill"]}}')

    def test_parse_provider_context_json_rejects_skill_name_starting_with_dash(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not start with '-'"):
            _parse_provider_context_json('{"hermes":{"skills":["--inject"]}}')

    def test_parse_provider_context_json_rejects_empty_skill_name(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not be empty"):
            _parse_provider_context_json('{"hermes":{"skills":[""]}}')

    def test_parse_provider_context_json_rejects_invalid_json(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be valid JSON"):
            _parse_provider_context_json("not json")

    def test_parse_provider_context_json_rejects_non_object_root(self) -> None:
        with self.assertRaisesRegex(ValueError, "root must be an object"):
            _parse_provider_context_json('["list"]')

    def test_parse_provider_context_json_rejects_non_object_provider_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be an object"):
            _parse_provider_context_json('{"pi":"disabled"}')

    # ── provider-specific key validation ──

    def test_parse_provider_context_json_rejects_empty_provider_specific_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "contains empty key"):
            _parse_provider_context_json('{"my-agent":{"":"on"}}')

    def test_parse_provider_context_json_rejects_control_chars_in_provider_specific_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "control characters"):
            _parse_provider_context_json('{"my-agent":{"bad\\u0001key":"on"}}')

    def test_parse_provider_context_json_rejects_option_looking_provider_specific_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "must not start with '-'"):
            _parse_provider_context_json('{"my-agent":{"--inject":"on"}}')

    def test_merge_provider_context(self) -> None:
        base = {"pi": {"skills": "disabled", "context_files": False}}
        override = {"pi": {"skills": "ambient"}, "hermes": {"skills": ["gh"]}}
        merged = _merge_provider_context(base, override)
        self.assertEqual(merged["pi"]["skills"], "ambient")
        self.assertFalse(merged["pi"]["context_files"])
        self.assertEqual(merged["hermes"]["skills"], ["gh"])

    def test_resolve_config_merges_file_and_cli_context(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "review",
            "--prompt", "review",
            "--provider-context-json",
            '{"pi":{"skills":"ambient"}}',
        ])
        cfg = _resolve_config(
            args,
            {
                "policy": {
                    "provider_context": {
                        "pi": {"skills": "disabled", "context_files": False},
                        "hermes": {"skills": ["gh"]},
                    }
                }
            },
        )
        self.assertEqual(cfg.policy.provider_context["pi"]["skills"], "ambient")
        self.assertFalse(cfg.policy.provider_context["pi"]["context_files"])
        self.assertEqual(cfg.policy.provider_context["hermes"]["skills"], ["gh"])


class TestAdapterContextFlags(unittest.TestCase):
    # ── Claude: absent provider_context → original command unchanged ──

    def test_claude_no_provider_context_keeps_original_command(self) -> None:
        adapter = ClaudeAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."])
        cmd = adapter._build_command(task)
        self.assertNotIn("--safe-mode", cmd)
        self.assertNotIn("--disable-slash-commands", cmd)

    def test_claude_with_empty_provider_context_adds_safe_mode(self) -> None:
        adapter = ClaudeAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {}})
        cmd = adapter._build_command(task)
        self.assertIn("--safe-mode", cmd)
        self.assertIn("--disable-slash-commands", cmd)

    def test_claude_context_files_enabled(self) -> None:
        adapter = ClaudeAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"context_files": True}})
        cmd = adapter._build_command(task)
        self.assertNotIn("--safe-mode", cmd)
        self.assertNotIn("--disable-slash-commands", cmd)

    def test_claude_supported_context_keys(self) -> None:
        self.assertEqual(ClaudeAdapter().supported_context_keys(), ["context_files"])

    # ── Codex: absent provider_context → original command unchanged ──

    def test_codex_no_provider_context_keeps_original_command(self) -> None:
        adapter = CodexAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."])
        cmd = adapter._build_command(task)
        self.assertNotIn("--ignore-user-config", cmd)
        self.assertNotIn("--ignore-rules", cmd)

    def test_codex_with_empty_provider_context_adds_ignore_flags(self) -> None:
        adapter = CodexAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {}})
        cmd = adapter._build_command(task)
        self.assertIn("--ignore-user-config", cmd)
        self.assertIn("--ignore-rules", cmd)

    def test_codex_context_files_enabled(self) -> None:
        adapter = CodexAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"context_files": True}})
        cmd = adapter._build_command(task)
        self.assertNotIn("--ignore-user-config", cmd)
        self.assertNotIn("--ignore-rules", cmd)

    def test_codex_supported_context_keys(self) -> None:
        self.assertEqual(CodexAdapter().supported_context_keys(), ["context_files"])

    # ── Hermes: absent provider_context → original command unchanged ──

    def test_hermes_no_provider_context_keeps_original_command(self) -> None:
        adapter = HermesAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."])
        cmd = adapter._build_command(task)
        self.assertNotIn("--safe-mode", cmd)

    def test_hermes_skills_only_does_not_add_safe_mode(self) -> None:
        """Skills only (no context_files) should NOT add --safe-mode."""
        adapter = HermesAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"skills": ["gh-auth"]}})
        cmd = adapter._build_command(task)
        self.assertNotIn("--safe-mode", cmd)
        self.assertIn("--skills", cmd)

    def test_hermes_skills_ambient_does_not_add_safe_mode(self) -> None:
        """Skills=ambient (no context_files) should NOT add --safe-mode."""
        adapter = HermesAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"skills": "ambient"}})
        cmd = adapter._build_command(task)
        self.assertNotIn("--safe-mode", cmd)

    def test_hermes_context_files_false_adds_safe_mode(self) -> None:
        adapter = HermesAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"context_files": False}})
        cmd = adapter._build_command(task)
        self.assertIn("--safe-mode", cmd)

    def test_hermes_context_files_enabled(self) -> None:
        adapter = HermesAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"context_files": True}})
        cmd = adapter._build_command(task)
        self.assertNotIn("--safe-mode", cmd)

    def test_hermes_skills_explicit_list(self) -> None:
        adapter = HermesAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"skills": ["gh-auth"]}})
        cmd = adapter._build_command(task)
        self.assertIn("--skills", cmd)
        skills_idx = cmd.index("--skills")
        self.assertEqual(cmd[skills_idx + 1], "gh-auth")

    def test_hermes_skills_plus_context_files_false_strict(self) -> None:
        """skills + context_files=False is incompatible; review_engine strict fails."""
        adapter = HermesAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {
                             "skills": "ambient", "context_files": False,
                         }})
        cmd = adapter._build_command(task)
        # Adapter still applies both (--safe-mode + skills), but review_engine
        # will detect the incompatibility at the policy level.
        self.assertIn("--safe-mode", cmd)

    def test_hermes_supported_context_keys(self) -> None:
        self.assertEqual(HermesAdapter().supported_context_keys(),
                         ["skills", "context_files"])

    # ── OpenCode: absent provider_context → original command unchanged ──

    def test_opencode_no_provider_context_keeps_original_command(self) -> None:
        adapter = OpenCodeAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."])
        cmd = adapter._build_command(task)
        self.assertNotIn("--pure", cmd)

    def test_opencode_plugins_false_adds_pure(self) -> None:
        adapter = OpenCodeAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"plugins": False}})
        cmd = adapter._build_command(task)
        self.assertIn("--pure", cmd)

    def test_opencode_plugins_true_no_pure(self) -> None:
        adapter = OpenCodeAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"plugins": True}})
        cmd = adapter._build_command(task)
        self.assertNotIn("--pure", cmd)

    def test_opencode_context_files_false_does_not_add_pure(self) -> None:
        adapter = OpenCodeAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"context_files": False}})
        cmd = adapter._build_command(task)
        self.assertNotIn("--pure", cmd)

    def test_opencode_supported_context_keys(self) -> None:
        self.assertEqual(OpenCodeAdapter().supported_context_keys(), ["plugins"])

    # ── Pi: original defaults are no-context/no-skills/no-extensions ──

    def test_pi_no_provider_context_keeps_original_defaults(self) -> None:
        adapter = PiAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."])
        cmd = adapter._build_command(task)
        self.assertIn("--no-context-files", cmd)
        self.assertIn("--no-skills", cmd)
        self.assertIn("--no-extensions", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "read,grep,find,ls")

    def test_pi_with_empty_provider_context_keeps_defaults(self) -> None:
        adapter = PiAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {}})
        cmd = adapter._build_command(task)
        self.assertIn("--no-context-files", cmd)
        self.assertIn("--no-skills", cmd)
        self.assertIn("--no-extensions", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "read,grep,find,ls")

    def test_pi_context_files_enabled(self) -> None:
        adapter = PiAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"context_files": True}})
        cmd = adapter._build_command(task)
        self.assertNotIn("--no-context-files", cmd)
        self.assertIn("--no-skills", cmd)
        self.assertIn("--no-extensions", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "read,grep,find,ls")

    def test_pi_skills_ambient(self) -> None:
        adapter = PiAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"skills": "ambient"}})
        cmd = adapter._build_command(task)
        self.assertNotIn("--no-skills", cmd)
        self.assertIn("--no-context-files", cmd)
        self.assertIn("--no-extensions", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "read,grep,find,ls")

    def test_pi_skills_explicit_list_omits_no_skills(self) -> None:
        adapter = PiAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"skills": ["s1", "s2"]}})
        cmd = adapter._build_command(task)
        self.assertIn("--skill", cmd)
        s1_idx = cmd.index("--skill")
        self.assertEqual(cmd[s1_idx + 1], "s1")
        self.assertNotIn("--no-skills", cmd)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "read,grep,find,ls")

    def test_pi_extensions_always_disabled(self) -> None:
        """Pi extensions are always --no-extensions, even with extensions in context."""
        adapter = PiAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {"extensions": True}})
        cmd = adapter._build_command(task)
        self.assertIn("--no-extensions", cmd)

    def test_pi_tools_always_locked(self) -> None:
        adapter = PiAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."],
                         metadata={"provider_context": {
                             "skills": "ambient", "context_files": True,
                         }})
        cmd = adapter._build_command(task)
        self.assertEqual(cmd[cmd.index("--tools") + 1], "read,grep,find,ls")
        self.assertNotIn("bash", cmd)
        self.assertNotIn("edit", cmd)
        self.assertNotIn("write", cmd)
        self.assertNotIn("--approve", cmd)

    def test_pi_supported_context_keys(self) -> None:
        self.assertEqual(PiAdapter().supported_context_keys(),
                         ["skills", "context_files"])


class TestReviewEngineContextPolicy(unittest.TestCase):
    def test_supported_context_is_passed_to_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ContextAwareFakeAdapter("pi", ["skills", "context_files"])
            req = ReviewRequest(
                repo_root=tmpdir, prompt="run task", providers=["pi"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0,
                    provider_context={"pi": {"skills": "ambient", "context_files": False}},
                ),
            )
            result = run_review(req, adapters={"pi": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")
            ctx = adapter.last_metadata["provider_context"]
            self.assertEqual(ctx["skills"], "ambient")
            self.assertFalse(ctx["context_files"])
            self.assertEqual(
                result.provider_results["pi"]["applied_context"],
                {"skills": "ambient", "context_files": False},
            )

    def test_strict_mode_rejects_unknown_context_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ContextAwareFakeAdapter("pi", ["skills"])
            req = ReviewRequest(
                repo_root=tmpdir, prompt="run task", providers=["pi"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0, enforcement_mode="strict",
                    provider_context={"pi": {"skills": "disabled", "extensions": True}},
                ),
            )
            result = run_review(req, adapters={"pi": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "FAILED")
            self.assertEqual(result.provider_results["pi"]["reason"],
                             "context_policy_enforcement_failed")
            self.assertEqual(result.provider_results["pi"]["unknown_context_keys"],
                             ["extensions"])

    def test_best_effort_drops_unknown_context_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ContextAwareFakeAdapter("pi", ["skills"])
            req = ReviewRequest(
                repo_root=tmpdir, prompt="run task", providers=["pi"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0, enforcement_mode="best_effort",
                    provider_context={"pi": {"skills": "disabled", "extensions": True}},
                ),
            )
            result = run_review(req, adapters={"pi": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")
            ctx = adapter.last_metadata["provider_context"]
            self.assertEqual(ctx["skills"], "disabled")
            self.assertNotIn("extensions", ctx)
            self.assertEqual(result.provider_results["pi"]["unknown_context_keys"],
                             ["extensions"])

    def test_provider_results_include_context_audit_fields(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ContextAwareFakeAdapter("pi", ["skills", "context_files"])
            req = ReviewRequest(
                repo_root=tmpdir, prompt="run task", providers=["pi"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0,
                    provider_context={"pi": {"skills": "ambient", "context_files": True}},
                ),
            )
            result = run_review(req, adapters={"pi": adapter}, review_mode=False)
            pr = result.provider_results["pi"]
            self.assertIn("requested_context", pr)
            self.assertIn("applied_context", pr)
            self.assertIn("unknown_context_keys", pr)
            self.assertIn("supported_context_keys", pr)
            self.assertIn("incompatible_context_keys", pr)
            self.assertIn("dropped_context_keys", pr)

    def test_empty_context_policy_is_noop(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ContextAwareFakeAdapter("pi", ["skills", "context_files"])
            req = ReviewRequest(
                repo_root=tmpdir, prompt="run task", providers=["pi"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(max_retries=0),
            )
            result = run_review(req, adapters={"pi": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")
            self.assertIsNone(result.provider_results["pi"]["requested_context"])
            self.assertIsNone(result.provider_results["pi"]["applied_context"])

    def test_hermes_incompatible_skills_plus_context_files_false_strict(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ContextAwareFakeAdapter("hermes", ["skills", "context_files"])
            req = ReviewRequest(
                repo_root=tmpdir, prompt="run task", providers=["hermes"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0, enforcement_mode="strict",
                    provider_context={"hermes": {"skills": "ambient", "context_files": False}},
                ),
            )
            result = run_review(req, adapters={"hermes": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "FAILED")
            pr = result.provider_results["hermes"]
            self.assertEqual(pr["reason"], "context_policy_enforcement_failed")
            self.assertIn("skills", pr["incompatible_context_keys"])
            self.assertIn("context_files", pr["incompatible_context_keys"])

    def test_hermes_incompatible_skills_plus_context_files_false_best_effort(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ContextAwareFakeAdapter("hermes", ["skills", "context_files"])
            req = ReviewRequest(
                repo_root=tmpdir, prompt="run task", providers=["hermes"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0, enforcement_mode="best_effort",
                    provider_context={"hermes": {"skills": "ambient", "context_files": False}},
                ),
            )
            result = run_review(req, adapters={"hermes": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")
            pr = result.provider_results["hermes"]
            self.assertIn("skills", pr["incompatible_context_keys"])
            self.assertIn("context_files", pr["incompatible_context_keys"])
            self.assertIn("skills", pr["dropped_context_keys"])
            self.assertIn("context_files", pr["dropped_context_keys"])
            self.assertNotIn("skills", pr["applied_context"] or {})
            self.assertNotIn("context_files", pr["applied_context"] or {})

    def test_run_payload_includes_provider_context_and_hash(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ContextAwareFakeAdapter("pi", ["skills", "context_files"])
            req = ReviewRequest(
                repo_root=tmpdir, prompt="run task", providers=["pi"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0,
                    provider_context={"pi": {"skills": "ambient", "context_files": True}},
                ),
            )
            result = run_review(req, adapters={"pi": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")
            # Check run.json was written with provider_context and context_hash
            run_json_path = Path(tmpdir) / "artifacts" / result.task_id / "run.json"
            self.assertTrue(run_json_path.exists())
            run_payload = json.loads(run_json_path.read_text())
            self.assertIn("provider_context", run_payload)
            self.assertIn("context_hash", run_payload)
            self.assertEqual(run_payload["provider_context"],
                             {"pi": {"skills": "ambient", "context_files": True}})
            self.assertIsInstance(run_payload["context_hash"], str)
            self.assertTrue(len(run_payload["context_hash"]) > 0)

    def test_help_example_pi_strict_passes(self) -> None:
        """Help example {"pi":{"skills":"disabled","context_files":false}} passes strict."""
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ContextAwareFakeAdapter("pi", ["skills", "context_files"])
            req = ReviewRequest(
                repo_root=tmpdir, prompt="run task", providers=["pi"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0, enforcement_mode="strict",
                    provider_context={"pi": {"skills": "disabled", "context_files": False}},
                ),
            )
            result = run_review(req, adapters={"pi": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")


if __name__ == "__main__":
    unittest.main()
