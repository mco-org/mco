"""Tests for ACP CLI integration."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.cli import build_parser
from runtime.adapters import adapter_registry
from runtime.acp.adapter import AcpAdapter
from runtime.adapters.codex import CodexAdapter
from runtime.contracts import TaskInput


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


class TestAcpContextAllowlist(unittest.TestCase):
    def test_adapter_forwards_context_directory_as_read_only(self) -> None:
        class RecordingClient:
            started = []

            def __init__(self, **_kwargs: object) -> None:
                self.pid = None

            def start(self, **kwargs: object) -> None:
                type(self).started.append(kwargs)

            def initialize(self, **_kwargs: object) -> object:
                return object()

            def new_session(self, **_kwargs: object) -> str:
                return "session"

            def prompt(self, *_args: object, **_kwargs: object) -> None:
                return None

            def collect_text(self) -> str:
                return ""

            def close(self) -> None:
                return None

        with tempfile.TemporaryDirectory() as tmp:
            context_dir = Path(tmp) / "context"
            context_dir.mkdir()
            with patch("runtime.acp.adapter.AcpClient", RecordingClient):
                adapter = AcpAdapter("claude", "claude", acp_command=["claude", "acp"])
                adapter.run(TaskInput(
                    task_id="context",
                    prompt="read context",
                    repo_root=tmp,
                    target_paths=["."],
                    timeout_seconds=5,
                    metadata={
                        "artifact_root": tmp,
                        "allow_paths": ["."],
                        "context_read_only_paths": [str(context_dir)],
                        "provider_permissions": {"terminal": "enabled"},
                    },
                ))

        self.assertEqual(RecordingClient.started[-1]["read_only_paths"], [str(context_dir)])
        self.assertIn(str(context_dir), RecordingClient.started[-1]["allow_paths"])
        self.assertFalse(RecordingClient.started[-1]["enable_terminal"])


class TestCodexContextSandbox(unittest.TestCase):
    def test_context_stage_uses_read_only_sandbox_without_writable_directory_grant(self) -> None:
        adapter = CodexAdapter()
        task = TaskInput(
            task_id="context",
            prompt="read context",
            repo_root="/repo",
            target_paths=["."],
            timeout_seconds=5,
            metadata={
                "context_read_only_paths": ["/tmp/mco-context"],
                "provider_permissions": {"bypass": "true"},
            },
        )

        command = adapter._build_command(task)

        sandbox_index = command.index("--sandbox")
        self.assertEqual(command[sandbox_index + 1], "read-only")
        self.assertNotIn("--add-dir", command)
        self.assertNotIn("--dangerously-bypass-approvals-and-sandbox", command)
