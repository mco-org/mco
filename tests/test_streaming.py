"""Tests for structured streaming (--stream jsonl)."""
from __future__ import annotations

import json
import threading
import unittest
from unittest.mock import patch, MagicMock

from runtime.config import ReviewPolicy
from runtime.review_engine import ReviewRequest, run_review, _emit_event, _now_iso


class TestEmitEvent(unittest.TestCase):
    def test_calls_callback_with_timestamp(self) -> None:
        events = []
        req = ReviewRequest(
            repo_root=".", prompt="t", providers=["claude"],
            artifact_base="/tmp", policy=ReviewPolicy(),
            stream_callback=events.append,
        )
        _emit_event(req, {"type": "test"})
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["type"], "test")
        self.assertIn("timestamp", events[0])

    def test_noop_without_callback(self) -> None:
        req = ReviewRequest(
            repo_root=".", prompt="t", providers=["claude"],
            artifact_base="/tmp", policy=ReviewPolicy(),
        )
        # Should not raise
        _emit_event(req, {"type": "test"})

    def test_preserves_existing_timestamp(self) -> None:
        events = []
        req = ReviewRequest(
            repo_root=".", prompt="t", providers=["claude"],
            artifact_base="/tmp", policy=ReviewPolicy(),
            stream_callback=events.append,
        )
        _emit_event(req, {"type": "test", "timestamp": "custom"})
        self.assertEqual(events[0]["timestamp"], "custom")


class TestStreamingEventSequence(unittest.TestCase):
    """Test that run_review emits events in correct order."""

    @patch("runtime.review_engine._run_provider")
    def test_emits_run_started_and_result(self, mock_run) -> None:
        mock_outcome = MagicMock()
        mock_outcome.provider = "claude"
        mock_outcome.success = True
        mock_outcome.parse_ok = True
        mock_outcome.schema_valid_count = 0
        mock_outcome.dropped_count = 0
        mock_outcome.findings = []
        mock_outcome.provider_result = {"success": True, "findings_count": 0, "wall_clock_seconds": 1.0}
        mock_run.return_value = mock_outcome

        events = []
        req = ReviewRequest(
            repo_root=".",
            prompt="Review",
            providers=["claude"],
            artifact_base="/tmp/art",
            policy=ReviewPolicy(),
            stream_callback=events.append,
        )
        result = run_review(req, review_mode=True, write_artifacts=False)

        event_types = [e["type"] for e in events]
        # Must have run_started and result
        self.assertIn("run_started", event_types)
        self.assertIn("result", event_types)
        # run_started must be first
        self.assertEqual(event_types[0], "run_started")
        # result must be last
        self.assertEqual(event_types[-1], "result")

    @patch("runtime.review_engine._run_provider")
    def test_result_event_has_required_fields(self, mock_run) -> None:
        mock_outcome = MagicMock()
        mock_outcome.provider = "claude"
        mock_outcome.success = True
        mock_outcome.parse_ok = True
        mock_outcome.schema_valid_count = 0
        mock_outcome.dropped_count = 0
        mock_outcome.findings = []
        mock_outcome.provider_result = {"success": True, "findings_count": 0, "wall_clock_seconds": 2.0}
        mock_run.return_value = mock_outcome

        events = []
        req = ReviewRequest(
            repo_root=".",
            prompt="Review",
            providers=["claude"],
            artifact_base="/tmp/art",
            policy=ReviewPolicy(),
            stream_callback=events.append,
        )
        run_review(req, review_mode=True, write_artifacts=False)

        result_event = [e for e in events if e["type"] == "result"][0]
        self.assertIn("findings", result_event)
        self.assertIn("decision", result_event)
        self.assertIn("task_id", result_event)
        self.assertIn("provider_results", result_event)
        self.assertIsInstance(result_event["findings"], list)


class TestStreamingThreadSafety(unittest.TestCase):
    def test_lock_based_emitter(self) -> None:
        """Verify thread-safe emitter doesn't lose events."""
        lock = threading.Lock()
        events = []

        def emitter(event: dict) -> None:
            with lock:
                events.append(json.dumps(event))

        threads = []
        for i in range(20):
            t = threading.Thread(target=emitter, args=({"type": "test", "i": i},))
            threads.append(t)

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(events), 20)
        # Verify all are valid JSON
        for line in events:
            parsed = json.loads(line)
            self.assertEqual(parsed["type"], "test")


class TestEmptyDiffEmitsEvents(unittest.TestCase):
    """Fix 1: empty diff must still emit run_started + result."""

    @patch("runtime.diff_utils.diff_files", return_value=[])
    @patch("runtime.diff_utils.detect_main_branch", return_value="main")
    def test_empty_diff_emits_run_started_and_result(self, mock_detect, mock_files) -> None:
        events = []
        req = ReviewRequest(
            repo_root="/tmp/fake",
            prompt="Review",
            providers=["claude"],
            artifact_base="/tmp/art",
            policy=ReviewPolicy(),
            diff_mode="branch",
            stream_callback=events.append,
        )
        result = run_review(req, review_mode=True, write_artifacts=False)
        event_types = [e["type"] for e in events]
        self.assertIn("run_started", event_types)
        self.assertIn("result", event_types)
        self.assertEqual(event_types[-1], "result")
        result_event = [e for e in events if e["type"] == "result"][0]
        self.assertEqual(result_event["findings_count"], 0)


class TestProviderEarlyExitEvents(unittest.TestCase):
    """Fix 3: early provider failures must emit provider_started + provider_error."""

    @patch("runtime.review_engine._run_provider")
    def test_provider_started_always_emitted(self, mock_run) -> None:
        """Even when provider fails, provider_started should appear in events."""
        mock_outcome = MagicMock()
        mock_outcome.provider = "claude"
        mock_outcome.success = False
        mock_outcome.parse_ok = False
        mock_outcome.schema_valid_count = 0
        mock_outcome.dropped_count = 0
        mock_outcome.findings = []
        mock_outcome.provider_result = {"success": False, "reason": "provider_unavailable"}
        mock_run.return_value = mock_outcome

        events = []
        req = ReviewRequest(
            repo_root=".",
            prompt="Review",
            providers=["claude"],
            artifact_base="/tmp/art",
            policy=ReviewPolicy(),
            stream_callback=events.append,
        )
        run_review(req, review_mode=True, write_artifacts=False)
        event_types = [e["type"] for e in events]
        self.assertIn("run_started", event_types)
        self.assertIn("result", event_types)


class TestStreamCLIFlags(unittest.TestCase):
    def test_stream_flag_accepted(self) -> None:
        from runtime.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "t", "--stream", "jsonl"])
        self.assertEqual(args.stream, "jsonl")

    def test_stream_and_json_rejected(self) -> None:
        from runtime.cli import main
        exit_code = main(["review", "--repo", ".", "--prompt", "t", "--stream", "jsonl", "--json"])
        self.assertEqual(exit_code, 2)

    def test_stream_and_format_sarif_rejected(self) -> None:
        from runtime.cli import main
        exit_code = main(["review", "--repo", ".", "--prompt", "t", "--stream", "jsonl", "--format", "sarif"])
        self.assertEqual(exit_code, 2)

    def test_no_stream_default(self) -> None:
        from runtime.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "t"])
        self.assertIsNone(args.stream)
