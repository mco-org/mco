"""Tests for ACP CLI integration."""
from __future__ import annotations

import unittest

from runtime.cli import build_parser
from runtime.adapters import adapter_registry


class TestTransportFlag(unittest.TestCase):
    def test_run_default_transport_is_shim(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--prompt", "test", "--providers", "claude"])
        # With argparse.SUPPRESS, transport is absent when not passed
        self.assertEqual(getattr(args, "transport", "shim"), "shim")

    def test_run_transport_acp(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["run", "--prompt", "test", "--providers", "claude", "--transport", "acp"])
        self.assertEqual(args.transport, "acp")

    def test_review_transport_acp(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--prompt", "test", "--providers", "claude", "--transport", "acp"])
        self.assertEqual(args.transport, "acp")

    def test_transport_invalid_rejected(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["run", "--prompt", "test", "--transport", "invalid"])


class TestAdapterRegistryTransport(unittest.TestCase):
    def test_shim_registry(self) -> None:
        reg = adapter_registry(transport="shim")
        self.assertIn("claude", reg)
        # Should be a ShimAdapterBase subclass
        self.assertTrue(hasattr(reg["claude"], "_build_command"))

    def test_acp_registry(self) -> None:
        reg = adapter_registry(transport="acp")
        self.assertIn("claude", reg)
        # Claude should be an AcpAdapter (has _acp_command attribute)
        self.assertTrue(hasattr(reg["claude"], "_acp_command"))
        # Providers without ACP still get shim adapters
        self.assertIn("opencode", reg)
        self.assertIn("qwen", reg)
