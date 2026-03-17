# tests/test_session_retry.py
"""Tests for session dispatch retry logic with error classification."""
from __future__ import annotations

import json
import os
import socket
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from runtime.session.state import SessionState, save_state
from runtime.session.daemon import (
    run_daemon, _socket_path, _dispatch_prompt,
    _RETRYABLE_ERROR_KINDS, _read_output, _extract_response,
)


def _send_prompt_request(sock_path: str, prompt: str, timeout: float = 30.0) -> dict:
    """Send a prompt and read both queued ack and final result."""
    client = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    client.settimeout(timeout)
    client.connect(sock_path)
    client.sendall(json.dumps({"action": "send", "prompt": prompt}).encode("utf-8") + b"\n")
    responses = []
    buf = b""
    while len(responses) < 2:
        chunk = client.recv(65536)
        if not chunk:
            break
        buf += chunk
        while b"\n" in buf:
            line, buf = buf.split(b"\n", 1)
            if line.strip():
                responses.append(json.loads(line.decode("utf-8")))
    client.close()
    return responses[-1] if responses else {}


class TestRetryableErrorKinds(unittest.TestCase):
    def test_retryable_set_matches_orchestrator(self) -> None:
        """Session retryable errors should match orchestrator's RETRYABLE_ERRORS."""
        from runtime.orchestrator import RETRYABLE_ERRORS
        orchestrator_kinds = {e.value for e in RETRYABLE_ERRORS}
        self.assertEqual(_RETRYABLE_ERROR_KINDS, orchestrator_kinds)


class TestErrorClassification(unittest.TestCase):
    def test_timeout_classified_as_retryable(self) -> None:
        from runtime.errors import classify_error
        kind = classify_error(124, "command timed out")
        self.assertEqual(kind.value, "retryable_timeout")

    def test_rate_limit_classified_as_retryable(self) -> None:
        from runtime.errors import classify_error
        kind = classify_error(1, "rate limit exceeded 429")
        self.assertEqual(kind.value, "retryable_rate_limit")

    def test_auth_classified_as_non_retryable(self) -> None:
        from runtime.errors import classify_error
        kind = classify_error(1, "invalid api key")
        self.assertEqual(kind.value, "non_retryable_auth")


class TestDispatchWithRetry(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    @patch("runtime.cli._doctor_adapter_registry")
    def test_retries_on_timeout(self, mock_registry) -> None:
        """Dispatch should retry on retryable_timeout."""
        call_count = {"n": 0}
        mock_adapter = MagicMock()
        mock_adapter.detect.return_value = MagicMock(detected=True, auth_ok=True)

        def fake_run(task_input):
            call_count["n"] += 1
            ref = MagicMock()
            ref.artifact_path = self.tmp
            return ref

        def fake_poll(ref):
            status = MagicMock()
            if call_count["n"] <= 1:
                # First attempt: simulate immediate completion with failure
                status.completed = True
                status.attempt_state = "FAILED"
                status.message = "timed out"
                status.exit_code = 124
            else:
                # Second attempt: success
                status.completed = True
                status.attempt_state = "SUCCEEDED"
            return status

        mock_adapter.run.side_effect = fake_run
        mock_adapter.poll.side_effect = fake_poll
        mock_registry.return_value = {"claude": mock_adapter}

        result = _dispatch_prompt("claude", self.tmp, "test prompt")
        self.assertTrue(result["success"])
        self.assertEqual(result["attempts"], 2)

    @patch("runtime.cli._doctor_adapter_registry")
    def test_no_retry_on_auth_error(self, mock_registry) -> None:
        """Auth errors should not be retried."""
        mock_adapter = MagicMock()
        mock_adapter.detect.return_value = MagicMock(detected=True, auth_ok=True)

        def fake_run(task_input):
            ref = MagicMock()
            ref.artifact_path = self.tmp
            return ref

        def fake_poll(ref):
            status = MagicMock()
            status.completed = True
            status.attempt_state = "FAILED"
            status.message = "invalid api key"
            status.exit_code = 1
            return status

        mock_adapter.run.side_effect = fake_run
        mock_adapter.poll.side_effect = fake_poll
        mock_registry.return_value = {"claude": mock_adapter}

        # Create fake stderr with auth error
        raw_dir = os.path.join(self.tmp, "raw")
        os.makedirs(raw_dir, exist_ok=True)
        with open(os.path.join(raw_dir, "claude.stderr.log"), "w") as f:
            f.write("invalid api key")

        result = _dispatch_prompt("claude", self.tmp, "test prompt")
        self.assertFalse(result["success"])
        self.assertEqual(result["attempts"], 1)  # No retry
        self.assertEqual(result["error_kind"], "non_retryable_auth")

    @patch("runtime.cli._doctor_adapter_registry")
    def test_partial_output_preserved_on_timeout(self, mock_registry) -> None:
        """Partial output should be preserved when timeout occurs."""
        mock_adapter = MagicMock()
        mock_adapter.detect.return_value = MagicMock(detected=True, auth_ok=True)

        def fake_run(task_input):
            ref = MagicMock()
            ref.artifact_path = self.tmp
            # Write partial output
            raw_dir = os.path.join(self.tmp, "raw")
            os.makedirs(raw_dir, exist_ok=True)
            with open(os.path.join(raw_dir, "claude.stdout.log"), "w") as f:
                f.write("Partial analysis: found 2 issues so far...")
            return ref

        def fake_poll(ref):
            status = MagicMock()
            status.completed = True
            status.attempt_state = "FAILED"
            status.message = "command timed out"
            status.exit_code = 124
            return status

        mock_adapter.run.side_effect = fake_run
        mock_adapter.poll.side_effect = fake_poll
        mock_registry.return_value = {"claude": mock_adapter}

        # Write stderr for classification
        raw_dir = os.path.join(self.tmp, "raw")
        os.makedirs(raw_dir, exist_ok=True)
        with open(os.path.join(raw_dir, "claude.stderr.log"), "w") as f:
            f.write("command timed out")

        result = _dispatch_prompt("claude", self.tmp, "test prompt")
        # Should have partial output even though it failed
        self.assertIn("Partial analysis", result.get("response", ""))

    @patch("runtime.cli._doctor_adapter_registry")
    def test_attempts_count_in_result(self, mock_registry) -> None:
        """Result should include attempt count."""
        mock_adapter = MagicMock()
        mock_adapter.detect.return_value = MagicMock(detected=True, auth_ok=True)

        def fake_run(task_input):
            ref = MagicMock()
            ref.artifact_path = self.tmp
            return ref

        def fake_poll(ref):
            status = MagicMock()
            status.completed = True
            status.attempt_state = "SUCCEEDED"
            return status

        mock_adapter.run.side_effect = fake_run
        mock_adapter.poll.side_effect = fake_poll
        mock_registry.return_value = {"claude": mock_adapter}

        result = _dispatch_prompt("claude", self.tmp, "test prompt")
        self.assertIn("attempts", result)
        self.assertEqual(result["attempts"], 1)


class TestReadOutputHelpers(unittest.TestCase):
    def test_read_output_missing_files(self) -> None:
        tmp = tempfile.mkdtemp()
        stdout, stderr = _read_output(tmp, "claude")
        self.assertEqual(stdout, "")
        self.assertEqual(stderr, "")
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)

    def test_read_output_with_content(self) -> None:
        tmp = tempfile.mkdtemp()
        raw_dir = os.path.join(tmp, "raw")
        os.makedirs(raw_dir)
        with open(os.path.join(raw_dir, "claude.stdout.log"), "w") as f:
            f.write("hello world")
        stdout, stderr = _read_output(tmp, "claude")
        self.assertEqual(stdout, "hello world")
        self.assertEqual(stderr, "")
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
