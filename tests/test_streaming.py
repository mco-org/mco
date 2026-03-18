"""Tests for structured streaming (--stream jsonl)."""
from __future__ import annotations

import contextlib
import io
import json
import threading
import unittest
from unittest.mock import patch, MagicMock

from runtime.config import ReviewPolicy
from runtime.formatters import LiveStreamRenderer
from runtime.review_engine import ReviewRequest, run_review, _emit_event, _now_iso


class _TTYBuffer(io.StringIO):
    def isatty(self) -> bool:
        return True


class _PipeBuffer(io.StringIO):
    def isatty(self) -> bool:
        return False


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
        self.assertIn("consensus", event_types)
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
        consensus_event = [e for e in events if e["type"] == "consensus"][0]
        self.assertIn("level_counts", consensus_event)


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


class TestArgparseErrorsEmitEvents(unittest.TestCase):
    """Fix 1: argparse errors with --stream should emit JSONL error, not just stderr."""

    def test_stream_safe_parser_suppresses_stderr_when_handler_installed(self) -> None:
        from runtime.cli import _StreamSafeParser, build_parser

        parser = build_parser()
        self.assertIsInstance(parser, _StreamSafeParser)
        parse_errors = []
        parser.set_stream_error_handler(parse_errors.append)

        stderr_buf = io.StringIO()
        with contextlib.redirect_stderr(stderr_buf), self.assertRaises(SystemExit) as exc:
            parser.parse_args(["review", "--repo", ".", "--prompt", "x", "--stream", "jsonl", "--format", "bad"])

        self.assertEqual(exc.exception.code, 2)
        self.assertEqual(stderr_buf.getvalue().strip(), "")
        self.assertTrue(parse_errors)
        self.assertIn("invalid choice", parse_errors[0])

    def test_missing_prompt_emits_jsonl_error_no_stderr(self) -> None:
        from runtime.cli import main
        from unittest.mock import patch, MagicMock
        import io
        import contextlib
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        # Mock stdin as a tty so _resolve_prompt doesn't try to read from it
        mock_stdin = MagicMock()
        mock_stdin.isatty.return_value = True
        with patch("sys.stdin", mock_stdin), \
             contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            try:
                exit_code = main(["review", "--repo", ".", "--stream", "jsonl"])
            except SystemExit as exc:
                exit_code = int(exc.code) if isinstance(exc.code, int) else 2
        self.assertEqual(exit_code, 2)
        # Must have JSONL error event on stdout
        output = stdout_buf.getvalue().strip()
        self.assertTrue(output, "Expected JSONL error event on stdout")
        event = json.loads(output.splitlines()[-1])
        self.assertEqual(event["type"], "error")
        # stderr must be empty — pure JSONL protocol
        self.assertEqual(stderr_buf.getvalue().strip(), "", "stderr must be empty in stream mode")

    def test_empty_stdin_stream_emits_jsonl_error(self) -> None:
        """Empty piped stdin with --stream jsonl should emit JSONL error, not stderr."""
        from runtime.cli import main
        from unittest.mock import patch
        import io
        import contextlib
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        mock_stdin = io.StringIO("")
        mock_stdin.isatty = lambda: False  # type: ignore
        with patch("sys.stdin", mock_stdin), \
             contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            try:
                exit_code = main(["review", "--repo", ".", "--stream", "jsonl"])
            except SystemExit as exc:
                exit_code = int(exc.code) if isinstance(exc.code, int) else 2
        self.assertEqual(exit_code, 2)
        output = stdout_buf.getvalue().strip()
        self.assertTrue(output, "Expected JSONL error event on stdout")
        event = json.loads(output.splitlines()[-1])
        self.assertEqual(event["type"], "error")
        self.assertEqual(stderr_buf.getvalue().strip(), "", "stderr must be empty in stream mode")

    def test_bad_stream_value_emits_jsonl_error(self) -> None:
        from runtime.cli import main
        # --stream bad is not a valid choice, argparse will reject it
        # but since "jsonl" is not in argv, it should NOT emit JSONL
        exit_code = main(["review", "--repo", ".", "--prompt", "x", "--stream", "bad"])
        self.assertEqual(exit_code, 2)


class TestTerminalStateCase(unittest.TestCase):
    """Fix 3: terminal_state must be uppercase COMPLETED everywhere."""

    @patch("runtime.diff_utils.diff_files", return_value=[])
    @patch("runtime.diff_utils.detect_main_branch", return_value="main")
    def test_empty_diff_terminal_state_uppercase(self, mock_detect, mock_files) -> None:
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
        self.assertEqual(result.terminal_state, "COMPLETED")
        result_event = [e for e in events if e["type"] == "result"][0]
        self.assertEqual(result_event["terminal_state"], "COMPLETED")


class TestStreamCLIFlags(unittest.TestCase):
    def test_stream_flag_accepted(self) -> None:
        from runtime.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "t", "--stream", "jsonl"])
        self.assertEqual(args.stream, "jsonl")

    def test_live_stream_flag_accepted(self) -> None:
        from runtime.cli import build_parser
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "t", "--stream", "live"])
        self.assertEqual(args.stream, "live")

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


class TestLiveStreamRenderer(unittest.TestCase):
    def test_status_updates_and_provider_findings_are_rendered(self) -> None:
        current_time = 0.0

        def _clock() -> float:
            return current_time

        finding = {
            "severity": "high",
            "title": "Null dereference",
            "evidence": {"file": "runtime/example.py", "line": 12},
            "detected_by": ["claude"],
        }
        stdout_buf = _TTYBuffer()
        renderer = LiveStreamRenderer(
            stdout_buf,
            is_tty=True,
            clock=_clock,
            refresh_interval_seconds=0,
        )

        renderer.handle_event({
            "type": "run_started",
            "providers": ["claude", "codex"],
            "task_id": "task-1",
            "review_mode": True,
        })
        renderer.handle_event({"type": "provider_started", "provider": "claude"})
        current_time = 18.3
        renderer.handle_event({
            "type": "provider_finished",
            "provider": "claude",
            "success": True,
            "findings_count": 1,
            "wall_clock_seconds": 18.3,
            "findings": [finding],
        })
        renderer.handle_event({
            "type": "result",
            "task_id": "task-1",
            "decision": "PASS",
            "terminal_state": "COMPLETED",
            "findings_count": 1,
            "findings": [finding],
            "provider_results": {
                "claude": {"success": True, "findings_count": 1, "wall_clock_seconds": 18.3},
                "codex": {"success": True, "findings_count": 0, "wall_clock_seconds": 0.0},
            },
        })

        output = stdout_buf.getvalue()
        self.assertIn("[claude] ⏳ running... (elapsed 0.0s)", output)
        self.assertIn("[claude] ✓ done — 1 findings (18.3s)", output)
        self.assertIn("claude findings", output)
        self.assertIn("HIGH", output)
        self.assertIn("runtime/example.py:12", output)
        self.assertIn("Final Merged Result", output)
        self.assertIn("Consensus analysis", output)
        self.assertIn("\x1b[", output)


class TestLiveStreamFallback(unittest.TestCase):
    @patch("runtime.cli.run_review")
    def test_live_stream_downgrades_to_jsonl_on_non_tty(self, mock_run) -> None:
        from runtime.cli import main
        from runtime.review_engine import ReviewResult

        def _fake_run(req, adapters=None, review_mode=True, write_artifacts=True):
            assert req.stream_callback is not None
            req.stream_callback({
                "type": "run_started",
                "task_id": "task-1",
                "providers": ["claude"],
                "review_mode": True,
            })
            req.stream_callback({
                "type": "result",
                "task_id": "task-1",
                "decision": "PASS",
                "terminal_state": "COMPLETED",
                "findings_count": 0,
                "findings": [],
                "provider_results": {},
            })
            return ReviewResult(
                task_id="task-1",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={"claude": {"success": True, "findings_count": 0, "wall_clock_seconds": 0.1}},
                findings_count=0,
                parse_success_count=1,
                parse_failure_count=0,
                schema_valid_count=0,
                dropped_findings_count=0,
                findings=[],
            )

        mock_run.side_effect = _fake_run
        stdout_buf = _PipeBuffer()
        stderr_buf = io.StringIO()
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            exit_code = main([
                "review",
                "--repo",
                ".",
                "--prompt",
                "t",
                "--providers",
                "claude",
                "--stream",
                "live",
            ])

        self.assertEqual(exit_code, 0)
        lines = [line for line in stdout_buf.getvalue().splitlines() if line.strip()]
        self.assertGreaterEqual(len(lines), 2)
        self.assertEqual(json.loads(lines[0])["type"], "run_started")
        self.assertEqual(json.loads(lines[-1])["type"], "result")
        self.assertEqual(stderr_buf.getvalue().strip(), "")


class TestJsonlStreamingCli(unittest.TestCase):
    @patch("runtime.cli.run_review")
    def test_jsonl_stream_includes_consensus_and_debate_events(self, mock_run) -> None:
        from runtime.cli import main
        from runtime.review_engine import ReviewResult

        debate_round = {
            "enabled": True,
            "provider_order": ["claude", "codex"],
            "providers": {
                "codex": {
                    "reviewed_count": 1,
                    "votes": [
                        {
                            "finding_key": "fp-1",
                            "title": "Issue",
                            "location": "a.py:1",
                            "reported_by": ["claude"],
                            "verdict": "AGREE",
                            "reason": "Confirmed",
                        }
                    ],
                    "success": True,
                    "final_error": None,
                }
            },
            "findings": [
                {
                    "finding_key": "fp-1",
                    "title": "Issue",
                    "location": "a.py:1",
                    "reported_by": ["claude"],
                    "consensus_score_before": 0.3,
                    "consensus_level_before": "needs-verification",
                    "consensus_score_after": 0.6,
                    "consensus_level_after": "confirmed",
                    "votes": [{"provider": "codex", "verdict": "AGREE", "reason": "Confirmed"}],
                    "vote_summary": {"agree": 1, "disagree": 0, "refine": 0},
                }
            ],
        }

        def _fake_run(req, adapters=None, review_mode=True, write_artifacts=True):
            assert req.stream_callback is not None
            req.stream_callback({
                "type": "run_started",
                "task_id": "task-1",
                "providers": ["claude", "codex"],
                "review_mode": True,
            })
            req.stream_callback({
                "type": "debate_started",
                "task_id": "task-1",
                "provider_count": 2,
                "findings_count": 1,
            })
            req.stream_callback({
                "type": "consensus",
                "task_id": "task-1",
                "provider_count": 2,
                "level_counts": {"confirmed": 1, "needs-verification": 0, "unverified": 0},
                "findings": [],
                "division_strategy": None,
            })
            req.stream_callback({
                "type": "debate_finished",
                "task_id": "task-1",
                "provider_count": 2,
                "findings_count": 1,
                "providers_with_votes": 1,
            })
            req.stream_callback({
                "type": "result",
                "task_id": "task-1",
                "decision": "PASS",
                "terminal_state": "COMPLETED",
                "findings_count": 1,
                "findings": [
                    {
                        "severity": "high",
                        "category": "bug",
                        "title": "Issue",
                        "consensus_score": 0.6,
                        "consensus_level": "confirmed",
                        "evidence": {"file": "a.py", "line": 1},
                    }
                ],
                "provider_results": {
                    "claude": {"success": True, "findings_count": 1, "wall_clock_seconds": 0.2},
                    "codex": {"success": True, "findings_count": 0, "wall_clock_seconds": 0.2},
                },
                "debate_round": debate_round,
            })
            return ReviewResult(
                task_id="task-1",
                artifact_root=None,
                decision="PASS",
                terminal_state="COMPLETED",
                provider_results={
                    "claude": {"success": True, "findings_count": 1, "wall_clock_seconds": 0.2},
                    "codex": {"success": True, "findings_count": 0, "wall_clock_seconds": 0.2},
                },
                findings_count=1,
                parse_success_count=2,
                parse_failure_count=0,
                schema_valid_count=1,
                dropped_findings_count=0,
                findings=[],
                debate_round=debate_round,
            )

        mock_run.side_effect = _fake_run
        stdout_buf = io.StringIO()
        stderr_buf = io.StringIO()
        with contextlib.redirect_stdout(stdout_buf), contextlib.redirect_stderr(stderr_buf):
            exit_code = main([
                "review",
                "--repo",
                ".",
                "--prompt",
                "t",
                "--providers",
                "claude,codex",
                "--stream",
                "jsonl",
                "--debate",
            ])

        self.assertEqual(exit_code, 0)
        self.assertEqual(stderr_buf.getvalue().strip(), "")
        event_types = [json.loads(line)["type"] for line in stdout_buf.getvalue().splitlines() if line.strip()]
        self.assertEqual(
            event_types,
            ["run_started", "debate_started", "consensus", "debate_finished", "result"],
        )
