from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.adapters.codex import CodexAdapter
from runtime.adapters.hermes import HermesAdapter
from runtime.adapters.pi import PiAdapter
from runtime.cli import _parse_provider_models_json, _resolve_config, build_parser
from runtime.config import ReviewConfig, ReviewPolicy
from runtime.contracts import CapabilitySet, NormalizeContext, ProviderPresence, TaskInput, TaskRunRef, TaskStatus
from runtime.models import (
    _hermes_default_model,
    _parse_codex_models,
    _parse_hermes_catalog,
    _parse_pi_models,
    discover_models,
)
from runtime.review_engine import ReviewRequest, run_review


class ModelAwareFakeAdapter:
    def __init__(self, provider: str, supported_model_keys: list[str]) -> None:
        self.id = provider
        self._supported_model_keys = supported_model_keys
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

    def supported_model_keys(self) -> list[str]:
        return list(self._supported_model_keys)

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


class TestProviderModelsConfig(unittest.TestCase):
    def test_review_policy_defaults(self) -> None:
        self.assertEqual(ReviewPolicy().provider_models, {})

    def test_review_policy_with_models(self) -> None:
        policy = ReviewPolicy(provider_models={"codex": {"model": "gpt-5.4"}})
        self.assertEqual(policy.provider_models["codex"], {"model": "gpt-5.4"})

    def test_review_config_defaults(self) -> None:
        self.assertEqual(ReviewConfig().policy.provider_models, {})

    def test_parse_provider_models_json_accepts_shorthand_and_object(self) -> None:
        parsed = _parse_provider_models_json(
            '{"codex":"gpt-5.4","pi":{"provider":"seal","model":"deepseek-v4-pro"}}'
        )
        self.assertEqual(parsed["codex"], {"model": "gpt-5.4"})
        self.assertEqual(parsed["pi"], {"provider": "seal", "model": "deepseek-v4-pro"})

    def test_parse_provider_models_json_rejects_unknown_key(self) -> None:
        with self.assertRaisesRegex(ValueError, "only supports 'model' and 'provider'"):
            _parse_provider_models_json('{"pi":{"tools":"bash"}}')

    def test_parse_provider_models_json_rejects_non_string_value(self) -> None:
        with self.assertRaisesRegex(ValueError, "must be a string"):
            _parse_provider_models_json('{"codex":{"model":123}}')

    def test_parse_provider_models_json_rejects_control_characters(self) -> None:
        with self.assertRaisesRegex(ValueError, "control characters"):
            _parse_provider_models_json('{"codex":"gpt\\u0001bad"}')

    def test_resolve_config_merges_file_and_cli_models(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "review",
            "--prompt", "review",
            "--provider-models-json",
            '{"pi":{"model":"deepseek-v4-pro"},"codex":"gpt-5.4"}',
        ])
        cfg = _resolve_config(
            args,
            {
                "policy": {
                    "provider_models": {
                        "pi": {"provider": "seal", "model": "old"},
                        "hermes": "gemini-3.5-flash",
                    }
                }
            },
        )
        self.assertEqual(cfg.policy.provider_models["pi"], {"provider": "seal", "model": "deepseek-v4-pro"})
        self.assertEqual(cfg.policy.provider_models["codex"], {"model": "gpt-5.4"})
        self.assertEqual(cfg.policy.provider_models["hermes"], {"model": "gemini-3.5-flash"})


class TestAdapterModelFlags(unittest.TestCase):
    def test_codex_model_flag(self) -> None:
        adapter = CodexAdapter()
        task = TaskInput("task", "Review", "/tmp", ["."], metadata={"model": "gpt-5.4"})
        cmd = adapter._build_command(task)
        self.assertEqual(cmd[cmd.index("--model") + 1], "gpt-5.4")
        self.assertEqual(adapter.supported_model_keys(), ["model"])

    def test_codex_does_not_accept_provider_model_key(self) -> None:
        self.assertNotIn("provider", CodexAdapter().supported_model_keys())

    def test_hermes_model_and_provider_flags(self) -> None:
        adapter = HermesAdapter()
        task = TaskInput(
            "task",
            "Review",
            "/tmp",
            ["."],
            metadata={"model": "gemini-3.5-flash", "provider": "codewiz-gemini"},
        )
        cmd = adapter._build_command(task)
        self.assertEqual(cmd[cmd.index("--model") + 1], "gemini-3.5-flash")
        self.assertEqual(cmd[cmd.index("--provider") + 1], "codewiz-gemini")
        self.assertEqual(adapter.supported_model_keys(), ["model", "provider"])

    def test_pi_model_provider_flags_do_not_change_read_only_tools(self) -> None:
        adapter = PiAdapter()
        task = TaskInput(
            "task",
            "Review",
            "/tmp",
            ["."],
            metadata={"model": "deepseek-v4-pro", "provider": "seal", "tools": "bash"},
        )
        cmd = adapter._build_command(task)
        self.assertEqual(cmd[cmd.index("--model") + 1], "deepseek-v4-pro")
        self.assertEqual(cmd[cmd.index("--provider") + 1], "seal")
        self.assertEqual(cmd[cmd.index("--tools") + 1], "read,grep,find,ls")
        self.assertNotIn("--approve", cmd)
        self.assertEqual(adapter.supported_model_keys(), ["model", "provider"])


class TestReviewEngineModelSelection(unittest.TestCase):
    def test_supported_model_config_is_passed_to_adapter(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ModelAwareFakeAdapter("pi", ["model", "provider"])
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="run task",
                providers=["pi"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0,
                    provider_models={"pi": {"provider": "seal", "model": "deepseek-v4-pro"}},
                ),
            )
            result = run_review(req, adapters={"pi": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")
            self.assertEqual(adapter.last_metadata["model"], "deepseek-v4-pro")
            self.assertEqual(adapter.last_metadata["provider"], "seal")
            self.assertEqual(
                result.provider_results["pi"]["applied_model"],
                {"provider": "seal", "model": "deepseek-v4-pro"},
            )

    def test_strict_mode_rejects_unknown_model_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ModelAwareFakeAdapter("codex", ["model"])
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="run task",
                providers=["codex"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0,
                    enforcement_mode="strict",
                    provider_models={"codex": {"model": "gpt-5.4", "provider": "openai"}},
                ),
            )
            result = run_review(req, adapters={"codex": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "FAILED")
            self.assertEqual(result.provider_results["codex"]["reason"], "model_selection_failed")
            self.assertEqual(result.provider_results["codex"]["unknown_model_keys"], ["provider"])

    def test_best_effort_drops_unknown_model_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmpdir:
            adapter = ModelAwareFakeAdapter("codex", ["model"])
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="run task",
                providers=["codex"],
                artifact_base=f"{tmpdir}/artifacts",
                policy=ReviewPolicy(
                    max_retries=0,
                    enforcement_mode="best_effort",
                    provider_models={"codex": {"model": "gpt-5.4", "provider": "openai"}},
                ),
            )
            result = run_review(req, adapters={"codex": adapter}, review_mode=False)
            self.assertEqual(result.terminal_state, "COMPLETED")
            self.assertEqual(adapter.last_metadata["model"], "gpt-5.4")
            self.assertNotIn("provider", adapter.last_metadata)
            self.assertEqual(result.provider_results["codex"]["unknown_model_keys"], ["provider"])


class TestModelParsing(unittest.TestCase):
    def test_parse_codex_models_debug_json(self) -> None:
        stdout = json.dumps({
            "models": [
                {
                    "slug": "gpt-5.5",
                    "display_name": "GPT-5.5",
                    "default_reasoning_level": "high",
                    "supported_reasoning_levels": [{"effort": "medium"}, {"effort": "high"}],
                    "visibility": "public",
                },
                {"id": "gpt-5.4"},
            ]
        })
        models = _parse_codex_models(stdout)
        self.assertEqual(models[0]["id"], "gpt-5.5")
        self.assertEqual(models[0]["display_name"], "GPT-5.5")
        self.assertEqual(models[0]["supported_reasoning_levels"], ["medium", "high"])
        self.assertEqual(models[1]["id"], "gpt-5.4")

    def test_parse_pi_models(self) -> None:
        stdout = (
            "provider           model              context  max-out  thinking  images\n"
            "openai-codex       gpt-5.4            272K     128K     yes       yes\n"
            "seal               deepseek-v4-pro    1M       32K      yes       no"
        )
        models = _parse_pi_models(stdout)
        self.assertEqual(models[0]["id"], "gpt-5.4")
        self.assertEqual(models[0]["provider"], "openai-codex")
        self.assertEqual(models[1]["id"], "deepseek-v4-pro")
        self.assertEqual(models[1]["provider"], "seal")

    def test_parse_hermes_catalog(self) -> None:
        models = _parse_hermes_catalog({
            "openrouter": [
                {"id": "openai/gpt-5.5"},
                {"id": "anthropic/claude-sonnet-4.6"},
            ],
            "codewiz-gemini": {"models": [{"model": "gemini-3.5-flash"}]},
        })
        ids = {item["id"] for item in models}
        self.assertIn("openai/gpt-5.5", ids)
        self.assertIn("anthropic/claude-sonnet-4.6", ids)
        self.assertIn("gemini-3.5-flash", ids)

    @patch("runtime.models._read_text")
    def test_parse_hermes_default_model_from_top_level_model_block(self, mock_read_text) -> None:
        mock_read_text.return_value = (
            "---\n"
            "model:\n"
            "  default: gemini-3.5-flash\n"
            "  provider: codewiz-gemini\n"
            "providers:\n"
            "  codewiz-gemini:\n"
            "    default_model: should-not-win\n"
        )
        self.assertEqual(
            _hermes_default_model(),
            {"provider": "codewiz-gemini", "model": "gemini-3.5-flash"},
        )


class TestModelDiscoveryFailSoft(unittest.TestCase):
    @patch("runtime.models._codex_default_model", return_value={"model": "gpt-5.5"})
    @patch("runtime.models._run_model_probe")
    def test_codex_discovery_uses_debug_models(self, mock_probe, _mock_default) -> None:
        mock_probe.return_value = {"ok": True, "stdout": '{"models":[{"slug":"gpt-5.4"}]}'}
        result = discover_models("codex")
        self.assertTrue(result["ok"])
        self.assertEqual(result["models"][0]["id"], "gpt-5.4")
        mock_probe.assert_called_once_with("codex", ["debug", "models"], timeout=20)

    @patch("runtime.models._pi_default_model", return_value={"provider": "seal", "model": "deepseek-v4-pro"})
    @patch("runtime.models._run_model_probe")
    def test_pi_discovery_uses_list_models(self, mock_probe, _mock_default) -> None:
        mock_probe.return_value = {"ok": True, "stdout": "provider model\nseal deepseek-v4-pro"}
        result = discover_models("pi")
        self.assertTrue(result["ok"])
        self.assertEqual(result["models"][0]["id"], "deepseek-v4-pro")
        mock_probe.assert_called_once_with("pi", ["--list-models"], timeout=30)

    @patch("runtime.models._hermes_default_model", return_value={"provider": "codewiz-gemini", "model": "gemini-3.5-flash"})
    @patch("runtime.models._read_text")
    def test_hermes_discovery_reads_catalog_cache(self, mock_read_text, _mock_default) -> None:
        mock_read_text.return_value = json.dumps({"openrouter": [{"id": "openai/gpt-5.5"}]})
        result = discover_models("hermes")
        self.assertTrue(result["ok"])
        self.assertEqual(result["models"][0]["id"], "openai/gpt-5.5")

    @patch("runtime.models._run_model_probe", return_value={"ok": False, "error": "binary_not_found"})
    def test_codex_discovery_fails_soft(self, _mock_probe) -> None:
        result = discover_models("codex")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "binary_not_found")
        self.assertEqual(result["models"], [])

    def test_unsupported_provider(self) -> None:
        result = discover_models("claude")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"], "model_discovery_not_supported")


if __name__ == "__main__":
    unittest.main()
