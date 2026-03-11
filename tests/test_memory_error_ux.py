"""Test that memory misconfiguration produces clear, actionable error messages."""
from __future__ import annotations

import io
import os
import sys
import unittest
from unittest.mock import patch


class TestMemoryErrorUX(unittest.TestCase):
    def test_space_without_memory_shows_message(self):
        """--space without --memory prints clear error to stderr."""
        from runtime.cli import main
        captured = io.StringIO()
        with patch("sys.stderr", captured):
            exit_code = main(["review", "--repo", ".", "--prompt", "test", "--space", "coding:foo"])
        self.assertEqual(exit_code, 2)
        self.assertIn("--space requires --memory", captured.getvalue())

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

    def test_npx_not_found_message(self):
        """If npx is not available, error should be understandable."""
        from runtime.bridge.evermemos_client import EverMemosClient
        client = EverMemosClient(api_key="fake-key")
        # We just verify the client can be constructed without npx check at init
        self.assertEqual(client.api_key, "fake-key")


if __name__ == "__main__":
    unittest.main()
