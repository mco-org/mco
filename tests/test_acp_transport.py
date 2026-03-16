"""Tests for ACP JSON-RPC transport."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from unittest.mock import patch, MagicMock

from runtime.acp.transport import JsonRpcTransport, JsonRpcError, TransportClosed


# A simple echo agent script that speaks JSON-RPC
_ECHO_AGENT = '''
import json
import sys

for line in sys.stdin:
    msg = json.loads(line.strip())
    if "id" in msg:
        method = msg.get("method", "")
        if method == "initialize":
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"agentInfo": {"name": "echo", "version": "1.0"}}}
        elif method == "session/new":
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"sessionId": "test-session-1"}}
        elif method == "session/prompt":
            # Send a notification first, then respond
            notif = {"jsonrpc": "2.0", "method": "session/update", "params": {"sessionId": "test-session-1", "state": "idle", "content": [{"type": "text", "text": "Echo: " + msg["params"]["content"][0]["text"]}]}}
            sys.stdout.write(json.dumps(notif) + "\\n")
            sys.stdout.flush()
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
        elif method == "session/cancel":
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
        elif method == "error_test":
            resp = {"jsonrpc": "2.0", "id": msg["id"], "error": {"code": -32601, "message": "Method not found"}}
        else:
            resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {}}
        sys.stdout.write(json.dumps(resp) + "\\n")
        sys.stdout.flush()
'''


class TestJsonRpcTransport(unittest.TestCase):
    def setUp(self) -> None:
        self.transport = JsonRpcTransport()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self) -> None:
        self.transport.close()
        import shutil
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _start_echo(self) -> None:
        self.transport.start(
            command=[sys.executable, "-c", _ECHO_AGENT],
            cwd=self.tmp,
        )

    def test_start_and_alive(self) -> None:
        self._start_echo()
        self.assertTrue(self.transport.alive)
        self.assertIsNotNone(self.transport.pid)

    def test_send_request_and_response(self) -> None:
        self._start_echo()
        result = self.transport.send_request("initialize", timeout=5.0)
        self.assertEqual(result["agentInfo"]["name"], "echo")

    def test_send_multiple_requests(self) -> None:
        self._start_echo()
        r1 = self.transport.send_request("initialize", timeout=5.0)
        r2 = self.transport.send_request("session/new", timeout=5.0)
        self.assertEqual(r1["agentInfo"]["name"], "echo")
        self.assertEqual(r2["sessionId"], "test-session-1")

    def test_notification_received(self) -> None:
        self._start_echo()
        self.transport.send_request("initialize", timeout=5.0)
        self.transport.send_request("session/new", timeout=5.0)
        self.transport.send_request(
            "session/prompt",
            params={
                "sessionId": "test-session-1",
                "content": [{"type": "text", "text": "hello"}],
            },
            timeout=5.0,
        )
        # The echo agent sends a notification before the response
        time.sleep(0.1)
        notif = self.transport.receive_notification(timeout=2.0)
        self.assertIsNotNone(notif)
        self.assertEqual(notif["method"], "session/update")
        self.assertIn("Echo: hello", notif["params"]["content"][0]["text"])

    def test_error_response_raises(self) -> None:
        self._start_echo()
        with self.assertRaises(JsonRpcError) as ctx:
            self.transport.send_request("error_test", timeout=5.0)
        self.assertEqual(ctx.exception.code, -32601)

    def test_close_terminates_process(self) -> None:
        self._start_echo()
        pid = self.transport.pid
        self.transport.close()
        self.assertFalse(self.transport.alive)

    def test_send_after_close_raises(self) -> None:
        self._start_echo()
        self.transport.close()
        with self.assertRaises(TransportClosed):
            self.transport.send_request("initialize", timeout=1.0)

    def test_stderr_captured(self) -> None:
        stderr_path = os.path.join(self.tmp, "stderr.log")
        agent_with_stderr = 'import sys; sys.stderr.write("debug info\\n"); sys.stderr.flush()\n' + _ECHO_AGENT
        self.transport.start(
            command=[sys.executable, "-c", agent_with_stderr],
            cwd=self.tmp,
            stderr_path=stderr_path,
        )
        self.transport.send_request("initialize", timeout=5.0)
        self.transport.close()
        time.sleep(0.2)
        self.assertTrue(os.path.exists(stderr_path))
        content = open(stderr_path).read()
        self.assertIn("debug info", content)

    def test_drain_notifications(self) -> None:
        self._start_echo()
        self.transport.send_request("initialize", timeout=5.0)
        self.transport.send_request("session/new", timeout=5.0)
        self.transport.send_request(
            "session/prompt",
            params={
                "sessionId": "test-session-1",
                "content": [{"type": "text", "text": "test"}],
            },
            timeout=5.0,
        )
        time.sleep(0.1)
        items = self.transport.drain_notifications()
        self.assertGreaterEqual(len(items), 1)


class TestTransportEdgeCases(unittest.TestCase):
    def test_start_twice_raises(self) -> None:
        transport = JsonRpcTransport()
        transport.start(command=[sys.executable, "-c", "import time; time.sleep(5)"], cwd=".")
        with self.assertRaises(RuntimeError):
            transport.start(command=[sys.executable, "-c", "pass"], cwd=".")
        transport.close()

    def test_timeout_raises(self) -> None:
        # Agent that never responds
        transport = JsonRpcTransport()
        transport.start(
            command=[sys.executable, "-c", "import time; time.sleep(60)"],
            cwd=".",
        )
        with self.assertRaises(TimeoutError):
            transport.send_request("initialize", timeout=0.5)
        transport.close()
