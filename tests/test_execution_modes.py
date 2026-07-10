from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest

from runtime.cli import _resolve_config, build_parser, main
from runtime.execution_modes import execution_permissions


class ExecutionModeMappingTests(unittest.TestCase):
    def test_representative_provider_mappings(self) -> None:
        self.assertEqual(execution_permissions("claude", "read_only"), {"permission_mode": "plan"})
        self.assertEqual(execution_permissions("claude", "write"), {"permission_mode": "acceptEdits"})
        self.assertEqual(execution_permissions("claude", "yolo"), {"permission_mode": "bypassPermissions"})
        self.assertEqual(
            execution_permissions("codex", "write"),
            {"sandbox": "workspace-write", "approval_policy": "never"},
        )
        self.assertEqual(execution_permissions("pi", "write"), {"tool_profile": "write"})

    def test_hermes_requires_yolo_because_oneshot_bypasses_approvals(self) -> None:
        self.assertIsNone(execution_permissions("hermes", "read_only"))
        self.assertIsNone(execution_permissions("hermes", "write"))
        self.assertEqual(execution_permissions("hermes", "yolo"), {"yolo": "true"})


class ExecutionModeCliTests(unittest.TestCase):
    def test_config_execution_mode_applies_unless_cli_overrides_it(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--prompt", "Review", "--providers", "claude"])
        resolved = _resolve_config(args, {"policy": {"execution_mode": "write"}})
        self.assertEqual(resolved.policy.execution_mode, "write")
        self.assertEqual(
            resolved.policy.provider_permissions["claude"],
            {"permission_mode": "acceptEdits"},
        )

    def _dry_run(self, command: str, providers: str, mode: str = "") -> dict:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            argv = [
                command,
                "--repo", tmp,
                "--prompt", "Handle this repository.",
                "--providers", providers,
                "--dry-run",
                "--json",
            ]
            if mode:
                argv.extend(["--execution-mode", mode])
            with contextlib.redirect_stdout(stdout_buf):
                exit_code = main(argv)
        self.assertEqual(exit_code, 0)
        return json.loads(stdout_buf.getvalue())

    def test_run_defaults_to_write_commands(self) -> None:
        payload = self._dry_run("run", "claude,codex,pi")
        self.assertEqual(payload["execution_mode"], "write")
        details = payload["providers_detail"]
        self.assertIn("acceptEdits", details["claude"]["command_template"])
        self.assertIn("workspace-write", details["codex"]["command_template"])
        self.assertIn("never", details["codex"]["command_template"])
        pi_tools = details["pi"]["command_template"]
        self.assertIn("read,write,edit,grep,find,ls", pi_tools)
        self.assertNotIn("bash", pi_tools)

    def test_review_defaults_to_read_only_commands(self) -> None:
        payload = self._dry_run("review", "claude,codex,qwen,cursor")
        self.assertEqual(payload["execution_mode"], "read_only")
        details = payload["providers_detail"]
        self.assertIn("plan", details["claude"]["command_template"])
        self.assertIn("read-only", details["codex"]["command_template"])
        self.assertIn("plan", details["qwen"]["command_template"])
        self.assertIn("ask", details["cursor"]["command_template"])

    def test_read_only_command_and_risk_matrix(self) -> None:
        payload = self._dry_run(
            "run",
            "claude,codex,copilot,cursor,gemini,grok,opencode,pi,qwen",
            "read_only",
        )
        expected_fragments = {
            "claude": "--permission-mode plan",
            "codex": "--sandbox read-only",
            "copilot": "--deny-tool=write --deny-tool=shell",
            "cursor": "--mode ask --sandbox enabled",
            "gemini": "--approval-mode plan",
            "grok": "--permission-mode plan",
            "opencode": "--agent plan",
            "pi": "read,grep,find,ls",
            "qwen": "--approval-mode plan",
        }
        for provider, fragment in expected_fragments.items():
            with self.subTest(provider=provider):
                detail = payload["providers_detail"][provider]
                self.assertIn(fragment, " ".join(detail["command_template"]))
                self.assertEqual(detail["risk"]["level"], "read_only")

    def test_write_command_and_risk_matrix(self) -> None:
        payload = self._dry_run(
            "run",
            "claude,codex,copilot,cursor,gemini,grok,opencode,pi,qwen",
            "write",
        )
        expected = {
            "claude": ("--permission-mode acceptEdits", "workspace_write"),
            "codex": ("--sandbox workspace-write", "workspace_write"),
            "copilot": ("--allow-tool=write --deny-tool=shell", "workspace_write"),
            "cursor": ("--force --sandbox enabled", "approval_bypass"),
            "gemini": ("--approval-mode auto_edit", "workspace_write"),
            "grok": ("--permission-mode acceptEdits", "workspace_write"),
            "opencode": ("--agent build --auto", "approval_bypass"),
            "pi": ("read,write,edit,grep,find,ls", "workspace_write"),
            "qwen": ("--approval-mode auto-edit", "workspace_write"),
        }
        for provider, (fragment, risk) in expected.items():
            with self.subTest(provider=provider):
                detail = payload["providers_detail"][provider]
                self.assertIn(fragment, " ".join(detail["command_template"]))
                self.assertEqual(detail["risk"]["level"], risk)

    def test_yolo_maps_to_provider_specific_bypass_flags(self) -> None:
        payload = self._dry_run("run", "claude,codex,qwen,cursor", "yolo")
        details = payload["providers_detail"]
        self.assertIn("bypassPermissions", details["claude"]["command_template"])
        self.assertIn("--dangerously-bypass-approvals-and-sandbox", details["codex"]["command_template"])
        self.assertIn("yolo", details["qwen"]["command_template"])
        self.assertIn("--force", details["cursor"]["command_template"])
        self.assertIn("disabled", details["cursor"]["command_template"])

    def test_yolo_command_matrix_covers_all_builtin_providers(self) -> None:
        payload = self._dry_run(
            "run",
            "claude,codex,copilot,cursor,gemini,grok,hermes,opencode,pi,qwen",
            "yolo",
        )
        commands = {
            provider: " ".join(detail["command_template"])
            for provider, detail in payload["providers_detail"].items()
        }
        expected = {
            "claude": ("--permission-mode bypassPermissions", "approval_bypass"),
            "codex": ("--dangerously-bypass-approvals-and-sandbox", "elevated"),
            "copilot": ("--allow-all", "approval_bypass"),
            "cursor": ("--force --sandbox disabled", "elevated"),
            "gemini": ("--approval-mode yolo", "approval_bypass"),
            "grok": ("--permission-mode bypassPermissions", "approval_bypass"),
            "hermes": ("--yolo", "approval_bypass"),
            "opencode": ("--agent build --auto", "approval_bypass"),
            "pi": ("read,write,edit,bash,grep,find,ls", "approval_bypass"),
            "qwen": ("--approval-mode yolo", "approval_bypass"),
        }
        for provider, (fragment, risk) in expected.items():
            with self.subTest(provider=provider):
                self.assertIn(fragment, commands[provider])
                self.assertEqual(payload["providers_detail"][provider]["risk"]["level"], risk)

    def test_hermes_non_yolo_mode_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            stdout_buf = io.StringIO()
            with contextlib.redirect_stdout(stdout_buf):
                exit_code = main([
                    "run", "--repo", tmp, "--prompt", "Edit code.",
                    "--providers", "hermes", "--json",
                ])
        self.assertEqual(exit_code, 2)
        error = json.loads(stdout_buf.getvalue())["error"]
        self.assertEqual(error["subtype"], "config_error")
        self.assertIn("--execution-mode yolo", error["message"])


if __name__ == "__main__":
    unittest.main()
