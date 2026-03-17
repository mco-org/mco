# tests/test_acp_rendering.py
"""Tests for structured ACP content rendering."""
from __future__ import annotations

import unittest

from runtime.acp.client import ContentAccumulator


class TestContentAccumulator(unittest.TestCase):
    def test_text_blocks(self) -> None:
        acc = ContentAccumulator()
        acc.add_block({"type": "text", "text": "hello world"})
        self.assertEqual(acc.collect_text(), "hello world")

    def test_thinking_blocks(self) -> None:
        acc = ContentAccumulator()
        acc.add_block({"type": "thinking", "text": "Let me think..."})
        rendered = acc.collect_rendered()
        self.assertIn("[Thinking]", rendered)
        self.assertIn("Let me think...", rendered)

    def test_tool_call_blocks(self) -> None:
        acc = ContentAccumulator()
        acc.add_block({
            "type": "tool_call",
            "name": "read_file",
            "arguments": {"path": "src/main.py"},
        })
        rendered = acc.collect_rendered()
        self.assertIn("[Tool: read_file]", rendered)

    def test_tool_result_blocks(self) -> None:
        acc = ContentAccumulator()
        acc.add_block({"type": "tool_result", "output": "file contents here"})
        rendered = acc.collect_rendered()
        self.assertIn("[Tool Result]", rendered)
        self.assertIn("file contents here", rendered)

    def test_diff_blocks(self) -> None:
        acc = ContentAccumulator()
        acc.add_block({"type": "diff", "path": "main.py", "content": "+added line"})
        rendered = acc.collect_rendered()
        self.assertIn("[Diff: main.py]", rendered)

    def test_collect_text_only_returns_text(self) -> None:
        acc = ContentAccumulator()
        acc.add_block({"type": "thinking", "text": "hmm"})
        acc.add_block({"type": "text", "text": "the answer"})
        self.assertEqual(acc.collect_text(), "the answer")

    def test_clear_resets(self) -> None:
        acc = ContentAccumulator()
        acc.add_block({"type": "text", "text": "old"})
        acc.clear()
        self.assertEqual(acc.collect_text(), "")
