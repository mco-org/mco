"""Tests for ACP adapter (ProviderAdapter interface)."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

from runtime.acp.adapter import AcpAdapter
from runtime.contracts import TaskInput


# ACP echo agent for adapter tests
_ACP_AGENT = '''
import json
import sys

for line in sys.stdin:
    msg = json.loads(line.strip())
    if "id" not in msg:
        continue
    method = msg.get("method", "")
    params = msg.get("params", {})

    if method == "initialize":
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocolVersion": "0.1",
            "agentInfo": {"name": "test", "version": "1.0"},
            "capabilities": {}
        }}
    elif method == "session/new":
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"sessionId": "s1"}}
    elif method == "session/prompt":
        text = params.get("content", [{}])[0].get("text", "")
        update = {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "s1", "state": "idle",
            "content": [{"type": "text", "text": "Found 3 issues in " + text.split()[-1] if text else "ok"}]
        }}
        sys.stdout.write(json.dumps(update) + "\\n")
        sys.stdout.flush()
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
    elif method == "session/cancel":
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
    else:
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}

    sys.stdout.write(json.dumps(resp) + "\\n")
    sys.stdout.flush()
'''


class TestAcpAdapter(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.adapter = AcpAdapter(
            provider_id="claude",
            binary_name=sys.executable,
            acp_command=[sys.executable, "-c", _ACP_AGENT],
        )

    def tearDown(self) -> None:
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_detect_with_valid_binary(self) -> None:
        presence = self.adapter.detect()
        self.assertTrue(presence.detected)
        self.assertTrue(presence.auth_ok)
        self.assertEqual(presence.reason, "acp_transport")

    def test_preview_command_applies_permission_flags(self) -> None:
        adapter = AcpAdapter(
            provider_id="claude",
            binary_name="claude",
            acp_command=["claude", "code", "--transport", "stdio"],
            permission_flags={"permission_mode": "--permission-mode"},
        )

        self.assertEqual(
            adapter.preview_command({"permission_mode": "plan"}),
            ["claude", "code", "--transport", "stdio", "--permission-mode", "plan"],
        )

    def test_run_poll_lifecycle(self) -> None:
        task = TaskInput(
            task_id="test-acp-001",
            prompt="review auth.py",
            repo_root=self.tmp,
            target_paths=["."],
            timeout_seconds=30,
            metadata={"artifact_root": self.tmp},
        )
        ref = self.adapter.run(task)
        self.assertIn("acp", ref.run_id)
        self.assertIsNotNone(ref.pid)

        # Poll until complete
        for _ in range(60):
            status = self.adapter.poll(ref)
            if status.completed:
                break
            time.sleep(0.1)

        self.assertTrue(status.completed)
        self.assertEqual(status.attempt_state, "SUCCEEDED")

        # Check artifact files were written
        stdout_path = os.path.join(ref.artifact_path, "raw", "claude.stdout.log")
        self.assertTrue(os.path.exists(stdout_path))
        content = open(stdout_path).read()
        self.assertIn("auth.py", content)

    def test_cancel(self) -> None:
        task = TaskInput(
            task_id="test-acp-cancel",
            prompt="slow task",
            repo_root=self.tmp,
            target_paths=["."],
            timeout_seconds=30,
            metadata={"artifact_root": self.tmp},
        )
        ref = self.adapter.run(task)
        time.sleep(0.5)
        # Cancel should not raise
        self.adapter.cancel(ref)

    def test_poll_unknown_run(self) -> None:
        from runtime.contracts import TaskRunRef
        fake_ref = TaskRunRef(
            task_id="x",
            provider="claude",
            run_id="nonexistent",
            artifact_path="/tmp",
            started_at="",
        )
        status = self.adapter.poll(fake_ref)
        self.assertTrue(status.completed)
        self.assertEqual(status.attempt_state, "EXPIRED")

    def test_poll_failure_uses_valid_error_kind(self) -> None:
        """When ACP poll sees a failed run, error_kind must be a valid ErrorKind member."""
        from runtime.types import ErrorKind
        task = TaskInput(
            task_id="test-acp-fail",
            prompt="fail",
            repo_root=self.tmp,
            target_paths=["."],
            timeout_seconds=5,
            metadata={"artifact_root": self.tmp},
        )
        ref = self.adapter.run(task)
        # Wait for prompt thread to complete, then force failure
        handle = self.adapter._runs.get(ref.run_id)
        if handle and handle.prompt_thread:
            handle.prompt_thread.join(timeout=5)
        if handle:
            handle.success = False
            handle.error_message = "test failure"
            handle.completed = True
        # Poll should return a valid error_kind
        status = self.adapter.poll(ref)
        self.assertTrue(status.completed)
        self.assertEqual(status.attempt_state, "FAILED")
        self.assertIsNotNone(status.error_kind)
        # Verify it's a valid ErrorKind member
        self.assertIn(status.error_kind, list(ErrorKind))


class TestAcpAdapterDetectMissingBinary(unittest.TestCase):
    def test_detect_missing_binary(self) -> None:
        adapter = AcpAdapter(
            provider_id="claude",
            binary_name="nonexistent-binary-xxxxx",
        )
        presence = adapter.detect()
        self.assertFalse(presence.detected)
        self.assertEqual(presence.reason, "binary_not_found")
