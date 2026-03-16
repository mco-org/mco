"""Tests for ACP client (high-level protocol)."""
from __future__ import annotations

import json
import sys
import tempfile
import time
import unittest

from runtime.acp.client import AcpClient, AgentInfo, SessionUpdate


# Full ACP echo agent
_ACP_ECHO_AGENT = '''
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
            "agentInfo": {"name": "test-agent", "version": "0.1.0"},
            "capabilities": {}
        }}
    elif method == "session/new":
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"sessionId": "sess-001"}}
    elif method == "session/prompt":
        prompt_text = params.get("content", [{}])[0].get("text", "")
        # Emit session/update notification
        update = {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": params.get("sessionId", ""),
            "state": "working",
            "content": [{"type": "text", "text": "Processing: " + prompt_text}]
        }}
        sys.stdout.write(json.dumps(update) + "\\n")
        sys.stdout.flush()
        # Emit idle notification
        idle = {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": params.get("sessionId", ""),
            "state": "idle",
            "content": [{"type": "text", "text": "Result for: " + prompt_text}]
        }}
        sys.stdout.write(json.dumps(idle) + "\\n")
        sys.stdout.flush()
        # Respond to the request
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
    elif method == "session/cancel":
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
    else:
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}

    sys.stdout.write(json.dumps(resp) + "\\n")
    sys.stdout.flush()
'''


class TestAcpClient(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.mkdtemp()
        self.client = AcpClient(
            command=[sys.executable, "-c", _ACP_ECHO_AGENT],
            cwd=self.tmp,
        )
        self.client.start()

    def tearDown(self) -> None:
        self.client.close()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_initialize(self) -> None:
        info = self.client.initialize(timeout=5.0)
        self.assertEqual(info.name, "test-agent")
        self.assertEqual(info.version, "0.1.0")

    def test_new_session(self) -> None:
        self.client.initialize(timeout=5.0)
        session_id = self.client.new_session(timeout=5.0)
        self.assertEqual(session_id, "sess-001")

    def test_prompt_and_collect_text(self) -> None:
        self.client.initialize(timeout=5.0)
        session_id = self.client.new_session(timeout=5.0)
        self.client.prompt(session_id, "review auth.py", timeout=5.0)
        # Drain updates
        time.sleep(0.1)
        self.client.drain_updates()
        text = self.client.collect_text()
        self.assertIn("review auth.py", text)

    def test_cancel(self) -> None:
        self.client.initialize(timeout=5.0)
        session_id = self.client.new_session(timeout=5.0)
        # Cancel should not raise
        self.client.cancel(session_id, timeout=5.0)

    def test_agent_info_stored(self) -> None:
        self.client.initialize(timeout=5.0)
        self.assertIsNotNone(self.client.agent_info)
        self.assertEqual(self.client.agent_info.name, "test-agent")

    def test_pid_and_alive(self) -> None:
        self.assertIsNotNone(self.client.pid)
        self.assertTrue(self.client.alive)
        self.client.close()
        self.assertFalse(self.client.alive)


class TestAcpClientNotificationOrder(unittest.TestCase):
    """Test that prompt() collects text even when RPC response arrives before notifications."""

    # Agent that sends RPC response BEFORE the session/update notification
    _REVERSE_ORDER_AGENT = '''
import json
import sys
import time

for line in sys.stdin:
    msg = json.loads(line.strip())
    if "id" not in msg:
        continue
    method = msg.get("method", "")
    params = msg.get("params", {})

    if method == "initialize":
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {
            "protocolVersion": "0.1",
            "agentInfo": {"name": "reverse-agent", "version": "0.1.0"},
            "capabilities": {}
        }}
    elif method == "session/new":
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"sessionId": "sess-rev"}}
    elif method == "session/prompt":
        prompt_text = params.get("content", [{}])[0].get("text", "")
        # Send RPC response FIRST
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
        # THEN send notification after a small delay
        time.sleep(0.1)
        update = {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": "sess-rev", "state": "idle",
            "content": [{"type": "text", "text": "Late result for: " + prompt_text}]
        }}
        sys.stdout.write(json.dumps(update) + "\\n")
        sys.stdout.flush()
        continue  # Already sent response above
    else:
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}

    sys.stdout.write(json.dumps(resp) + "\\n")
    sys.stdout.flush()
'''

    def test_prompt_collects_late_notifications(self) -> None:
        """Text should be collected even when notifications arrive after RPC response."""
        tmp = tempfile.mkdtemp()
        client = AcpClient(
            command=[sys.executable, "-c", self._REVERSE_ORDER_AGENT],
            cwd=tmp,
        )
        try:
            client.start()
            client.initialize(timeout=5.0)
            session_id = client.new_session(timeout=5.0)
            client.prompt(session_id, "test reverse order", timeout=10.0)
            text = client.collect_text()
            self.assertIn("Late result for: test reverse order", text)
        finally:
            client.close()
            import shutil
            shutil.rmtree(tmp, ignore_errors=True)


class TestAcpClientLifecycle(unittest.TestCase):
    def test_close_is_idempotent(self) -> None:
        tmp = tempfile.mkdtemp()
        client = AcpClient(
            command=[sys.executable, "-c", _ACP_ECHO_AGENT],
            cwd=tmp,
        )
        client.start()
        client.close()
        client.close()  # Should not raise
        import shutil
        shutil.rmtree(tmp, ignore_errors=True)
