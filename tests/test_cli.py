from __future__ import annotations

import contextlib
import io
import unittest

from runtime.cli import (
    _parse_paths,
    _parse_provider_permissions_json,
    _parse_provider_timeouts,
    _parse_providers,
    build_parser,
    _resolve_config,
)


class CliTests(unittest.TestCase):
    def test_parse_providers_deduplicates_preserve_order(self) -> None:
        providers = _parse_providers("codex,claude,codex,gemini,claude")
        self.assertEqual(providers, ["codex", "claude", "gemini"])

    def test_parse_provider_timeouts_ignores_invalid(self) -> None:
        parsed = _parse_provider_timeouts("codex=90,claude=120")
        self.assertEqual(parsed, {"codex": 90, "claude": 120})

    def test_parse_provider_timeouts_rejects_invalid_entries(self) -> None:
        with self.assertRaises(ValueError):
            _parse_provider_timeouts("codex=90,broken")
        with self.assertRaises(ValueError):
            _parse_provider_timeouts("codex=abc")
        with self.assertRaises(ValueError):
            _parse_provider_timeouts("codex=0")

    def test_parse_paths_defaults_to_dot(self) -> None:
        self.assertEqual(_parse_paths(""), ["."])
        self.assertEqual(_parse_paths("src, tests"), ["src", "tests"])

    def test_parse_provider_permissions_json(self) -> None:
        raw = '{"codex":{"sandbox":"workspace-write"},"claude":{"permission_mode":"plan"}}'
        parsed = _parse_provider_permissions_json(raw)
        self.assertEqual(parsed.get("codex"), {"sandbox": "workspace-write"})
        self.assertEqual(parsed.get("claude"), {"permission_mode": "plan"})

    def test_parse_provider_permissions_json_rejects_invalid_payload(self) -> None:
        with self.assertRaises(ValueError):
            _parse_provider_permissions_json("{not-json}")
        with self.assertRaises(ValueError):
            _parse_provider_permissions_json('["x"]')
        with self.assertRaises(ValueError):
            _parse_provider_permissions_json('{"codex":"workspace-write"}')

    def test_resolve_config_applies_cli_overrides(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "review",
                "--prompt",
                "x",
                "--providers",
                "claude,codex,qwen",
                "--artifact-base",
                "reports/custom",
                "--max-provider-parallelism",
                "3",
                "--provider-timeouts",
                "codex=120,qwen=240",
                "--stall-timeout",
                "700",
                "--poll-interval",
                "2.0",
                "--review-hard-timeout",
                "3000",
                "--allow-paths",
                "src,tests",
                "--enforcement-mode",
                "best_effort",
                "--provider-permissions-json",
                '{"claude":{"permission_mode":"accept-edits"},"codex":{"sandbox":"read-only"}}',
                "--strict-contract",
            ]
        )
        resolved = _resolve_config(args)
        self.assertEqual(resolved.providers, ["claude", "codex", "qwen"])
        self.assertEqual(resolved.artifact_base, "reports/custom")
        self.assertEqual(resolved.policy.max_provider_parallelism, 3)
        self.assertEqual(resolved.policy.provider_timeouts.get("qwen"), 240)
        self.assertEqual(resolved.policy.provider_timeouts.get("codex"), 120)
        self.assertIsNone(resolved.policy.provider_timeouts.get("claude"))
        self.assertEqual(resolved.policy.stall_timeout_seconds, 700)
        self.assertEqual(resolved.policy.poll_interval_seconds, 2.0)
        self.assertEqual(resolved.policy.review_hard_timeout_seconds, 3000)
        self.assertEqual(resolved.policy.allow_paths, ["src", "tests"])
        self.assertEqual(resolved.policy.enforcement_mode, "best_effort")
        self.assertEqual(resolved.policy.provider_permissions.get("codex"), {"sandbox": "read-only"})
        self.assertEqual(
            resolved.policy.provider_permissions.get("claude"),
            {"permission_mode": "accept-edits"},
        )
        self.assertTrue(resolved.policy.enforce_findings_contract)

    def test_resolve_config_allows_cli_zero_to_force_full_parallel(self) -> None:
        parser = build_parser()
        args = parser.parse_args(
            [
                "review",
                "--prompt",
                "x",
                "--max-provider-parallelism",
                "0",
            ]
        )
        resolved = _resolve_config(args)
        self.assertEqual(resolved.policy.max_provider_parallelism, 0)

    def test_parser_accepts_run_subcommand(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--prompt", "x"])
        self.assertEqual(args.command, "run")
        self.assertEqual(args.result_mode, "stdout")
        self.assertFalse(args.save_artifacts)

    def test_parser_rejects_config_flag(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["review", "--prompt", "x", "--config", "mco.json"])

    def test_top_level_help_contains_positioning_and_examples(self) -> None:
        parser = build_parser()
        help_text = parser.format_help()
        self.assertIn("Any Prompt. Any Agent. Any IDE.", help_text)
        self.assertIn("Use `mco run -h` or `mco review -h`", help_text)
        self.assertIn("mco review --repo . --prompt", help_text)

    def test_review_help_contains_groups_examples_and_exit_codes(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            with contextlib.redirect_stdout(io.StringIO()) as output:
                parser.parse_args(["review", "-h"])
        help_text = output.getvalue()
        self.assertIn("Execution Scope:", help_text)
        self.assertIn("Timeout and Parallelism:", help_text)
        self.assertIn("Access and Contracts:", help_text)
        self.assertIn("Examples:", help_text)
        self.assertIn("Exit codes:", help_text)
        self.assertIn("INCONCLUSIVE", help_text)
        self.assertIn("(default: 900)", help_text)


if __name__ == "__main__":
    unittest.main()
