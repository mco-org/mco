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
