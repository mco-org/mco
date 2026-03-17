# tests/test_custom_agent.py
"""Tests for --agent custom ACP server."""
from __future__ import annotations

import unittest

from runtime.cli import build_parser
from runtime.adapters import adapter_registry


class TestAgentFlag(unittest.TestCase):
    def test_agent_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args([
            "run", "--prompt", "test",
            "--agent", "mybot", "mybot --acp --stdio",
            "--transport", "acp",
        ])
        self.assertEqual(args.agent, ["mybot", "mybot --acp --stdio"])

    def test_agent_flag_optional(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--prompt", "test", "--providers", "claude"])
        self.assertIsNone(args.agent)


class TestAcpPermissionKeys(unittest.TestCase):
    def test_claude_acp_inherits_permission_mode(self) -> None:
        reg = adapter_registry(transport="acp")
        claude = reg.get("claude")
        if claude is None:
            self.skipTest("claude not in ACP registry")
        keys = claude.supported_permission_keys()
        self.assertIn("permission_mode", keys)
        self.assertIn("terminal", keys)

    def test_codex_acp_inherits_sandbox(self) -> None:
        reg = adapter_registry(transport="acp")
        codex = reg.get("codex")
        if codex is None:
            self.skipTest("codex not in ACP registry")
        keys = codex.supported_permission_keys()
        self.assertIn("sandbox", keys)
        self.assertIn("terminal", keys)
        self.assertNotIn("permission_mode", keys)

    def test_custom_agent_gets_only_terminal(self) -> None:
        reg = adapter_registry(
            transport="acp",
            extra_agents={"mybot": ["mybot", "--acp"]},
        )
        keys = reg["mybot"].supported_permission_keys()
        self.assertEqual(keys, ["terminal"])

    def test_claude_acp_has_permission_mode_flag(self) -> None:
        """claude ACP adapter should map permission_mode to --permission-mode CLI flag."""
        reg = adapter_registry(transport="acp")
        claude = reg.get("claude")
        if claude is None:
            self.skipTest("claude not in ACP registry")
        self.assertEqual(claude._permission_flags.get("permission_mode"), "--permission-mode")

    def test_codex_acp_has_sandbox_flag(self) -> None:
        """codex ACP adapter should map sandbox to --sandbox CLI flag."""
        reg = adapter_registry(transport="acp")
        codex = reg.get("codex")
        if codex is None:
            self.skipTest("codex not in ACP registry")
        self.assertEqual(codex._permission_flags.get("sandbox"), "--sandbox")


class TestCustomAgentRegistry(unittest.TestCase):
    def test_extra_agent_injected(self) -> None:
        reg = adapter_registry(
            transport="acp",
            extra_agents={"mybot": ["mybot", "--acp"]},
        )
        self.assertIn("mybot", reg)
        self.assertTrue(hasattr(reg["mybot"], "_acp_command"))

    def test_extra_agent_does_not_clobber_builtin(self) -> None:
        reg = adapter_registry(
            transport="acp",
            extra_agents={"custom": ["custom", "--acp"]},
        )
        self.assertIn("claude", reg)
        self.assertIn("custom", reg)
