"""Test that memory misconfiguration produces clear, actionable error messages."""
from __future__ import annotations

import io
import os
import sys
import unittest
from unittest.mock import patch, AsyncMock, MagicMock


class TestMemoryErrorUX(unittest.TestCase):
    def test_space_without_memory_shows_message(self):
        """--space without --memory prints clear error to stderr."""
        from runtime.cli import main
        captured = io.StringIO()
        with patch("sys.stderr", captured):
            exit_code = main(["review", "--repo", ".", "--prompt", "test", "--space", "my-repo"])
        self.assertEqual(exit_code, 2)
        self.assertIn("--space requires --memory", captured.getvalue())

    def test_space_with_colon_shows_slug_hint(self):
        """--space 'coding:foo' prints hint about slug-only format."""
        from runtime.cli import main
        captured = io.StringIO()
        with patch("sys.stderr", captured):
            exit_code = main(["review", "--repo", ".", "--prompt", "test", "--memory", "--space", "coding:foo"])
        self.assertEqual(exit_code, 2)
        self.assertIn("slug", captured.getvalue())

    def test_memory_without_api_key_shows_message(self):
        """--memory without EVERMEMOS_API_KEY shows actionable install hint."""
        env_backup = os.environ.pop("EVERMEMOS_API_KEY", None)
        try:
            from runtime.bridge.evermemos_client import EverMemosClient
            with self.assertRaises(ValueError) as ctx:
                EverMemosClient(api_key="")
            self.assertIn("EVERMEMOS_API_KEY", str(ctx.exception))
        finally:
            if env_backup is not None:
                os.environ["EVERMEMOS_API_KEY"] = env_backup

    def test_memory_without_mcp_sdk_shows_install_hint(self):
        """Missing MCP SDK should mention pip install mco[memory]."""
        from runtime.bridge.evermemos_client import EverMemosClient
        client = EverMemosClient(api_key="fake-key")

        # Mock mcp import to fail
        import builtins
        original_import = builtins.__import__

        def mock_import(name, *args, **kwargs):
            if name == "mcp" or name.startswith("mcp."):
                raise ImportError("No module named 'mcp'")
            return original_import(name, *args, **kwargs)

        with patch("builtins.__import__", side_effect=mock_import):
            with self.assertRaises(ImportError) as ctx:
                client._ensure_mcp_sdk()
            self.assertIn("pip install mco[memory]", str(ctx.exception))

    def test_uvx_not_found_surfaces_file_not_found(self):
        """If uvx binary is missing, _call_tool_sync should raise with context."""
        from runtime.bridge.evermemos_client import EverMemosClient
        client = EverMemosClient(api_key="fake-key")

        # Mock _ensure_mcp_sdk to pass, but mock _call_tool to raise FileNotFoundError
        # (simulating uvx not being on PATH)
        async def failing_call_tool(name, arguments):
            raise FileNotFoundError("[Errno 2] No such file or directory: 'uvx'")

        with patch.object(client, "_ensure_mcp_sdk"), \
             patch.object(client, "_call_tool", side_effect=failing_call_tool):
            with self.assertRaises(FileNotFoundError) as ctx:
                client._call_tool_sync("list_spaces", {})
            self.assertIn("uvx", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
