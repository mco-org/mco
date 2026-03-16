"""Tests for session state persistence."""
from __future__ import annotations

import json
import tempfile
import unittest

from runtime.session.state import (
    SessionState,
    HistoryEntry,
    save_state,
    load_state,
    append_history,
    load_history,
    list_sessions,
    build_history_prompt,
    session_dir,
    _auto_name,
)


class TestSessionState(unittest.TestCase):
    def test_save_and_load_roundtrip(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            state = SessionState(name="test", provider="claude", pid=123)
            save_state(tmp, state)
            loaded = load_state(tmp, "test")
            self.assertIsNotNone(loaded)
            self.assertEqual(loaded.name, "test")
            self.assertEqual(loaded.provider, "claude")
            self.assertEqual(loaded.pid, 123)
            self.assertEqual(loaded.status, "active")

    def test_load_nonexistent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertIsNone(load_state(tmp, "nope"))

    def test_auto_timestamps(self) -> None:
        state = SessionState(name="t", provider="claude")
        self.assertTrue(state.created_at)
        self.assertEqual(state.created_at, state.last_active)

    def test_auto_name(self) -> None:
        name = _auto_name("claude")
        self.assertTrue(name.startswith("claude-"))
        self.assertEqual(len(name), len("claude-") + 4)


class TestHistory(unittest.TestCase):
    def test_append_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            append_history(tmp, "s1", HistoryEntry(role="user", content="hello"))
            append_history(tmp, "s1", HistoryEntry(role="assistant", content="hi"))
            entries = load_history(tmp, "s1")
            self.assertEqual(len(entries), 2)
            self.assertEqual(entries[0].role, "user")
            self.assertEqual(entries[0].content, "hello")
            self.assertEqual(entries[1].role, "assistant")

    def test_load_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            entries = load_history(tmp, "nope")
            self.assertEqual(entries, [])

    def test_append_creates_dir(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            append_history(tmp, "new-session", HistoryEntry(role="user", content="x"))
            self.assertTrue(session_dir(tmp, "new-session").exists())


class TestListSessions(unittest.TestCase):
    def test_list_multiple(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            save_state(tmp, SessionState(name="a", provider="claude"))
            save_state(tmp, SessionState(name="b", provider="codex"))
            sessions = list_sessions(tmp)
            names = [s.name for s in sessions]
            self.assertEqual(sorted(names), ["a", "b"])

    def test_list_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(list_sessions(tmp), [])


class TestBuildHistoryPrompt(unittest.TestCase):
    def test_no_history(self) -> None:
        result = build_history_prompt([], "do something")
        self.assertEqual(result, "do something")

    def test_with_history(self) -> None:
        history = [
            HistoryEntry(role="user", content="review auth.py"),
            HistoryEntry(role="assistant", content="Found 3 issues"),
        ]
        result = build_history_prompt(history, "now check tests")
        self.assertIn("Conversation History", result)
        self.assertIn("User: review auth.py", result)
        self.assertIn("Assistant: Found 3 issues", result)
        self.assertIn("Current Request", result)
        self.assertIn("now check tests", result)
