# tests/test_acp_handlers.py
"""Tests for ACP fs/terminal request handlers."""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest

from runtime.acp.handlers import handle_fs_read, handle_fs_write


class TestFsReadHandler(unittest.TestCase):
    def test_read_existing_file(self) -> None:
        with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
            f.write("hello from file")
            f.flush()
            result = handle_fs_read(
                {"path": f.name},
                cwd=os.path.dirname(f.name),
                allow_paths=["."],
            )
            self.assertEqual(result["content"], "hello from file")
            os.unlink(f.name)

    def test_read_nonexistent_raises(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with self.assertRaises(FileNotFoundError):
                handle_fs_read(
                    {"path": "does_not_exist.txt"},
                    cwd=tmp,
                    allow_paths=["."],
                )


class TestFsWriteHandler(unittest.TestCase):
    def test_write_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "output.txt")
            handle_fs_write(
                {"path": path, "content": "written by handler"},
                cwd=tmp,
                allow_paths=["."],
            )
            self.assertEqual(open(path).read(), "written by handler")

    def test_write_outside_allow_paths_rejected(self) -> None:
        with self.assertRaises(PermissionError):
            handle_fs_write(
                {"path": "/etc/passwd", "content": "bad"},
                cwd="/tmp",
                allow_paths=["src"],
            )


class TestTerminalManager(unittest.TestCase):
    def test_create_and_output(self) -> None:
        from runtime.acp.handlers import TerminalManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = TerminalManager(cwd=tmp)
            tid = mgr.create("echo hello_terminal")
            mgr.wait_for_exit(tid, timeout=5)
            time.sleep(0.1)  # Let reader thread buffer
            output = mgr.output(tid)
            self.assertIn("hello_terminal", output)
            mgr.release(tid)

    def test_kill_running_process(self) -> None:
        from runtime.acp.handlers import TerminalManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = TerminalManager(cwd=tmp)
            tid = mgr.create("sleep 60")
            mgr.kill(tid)
            time.sleep(0.2)
            mgr.release(tid)

    def test_release_cleans_up(self) -> None:
        from runtime.acp.handlers import TerminalManager
        with tempfile.TemporaryDirectory() as tmp:
            mgr = TerminalManager(cwd=tmp)
            tid = mgr.create("echo done")
            mgr.wait_for_exit(tid, timeout=5)
            mgr.release(tid)
            self.assertNotIn(tid, mgr._terminals)


class TestTerminalDisabledByDefault(unittest.TestCase):
    """Terminal handlers must be explicitly enabled."""

    def test_terminal_not_registered_by_default(self) -> None:
        from runtime.acp.transport import JsonRpcTransport
        transport = JsonRpcTransport()
        # Without enable_terminal=True, no terminal handlers should be registered
        self.assertNotIn("terminal/create", transport._request_handlers)

    def test_fs_not_registered_without_allow_paths(self) -> None:
        """With empty allow_paths, fs handlers should not be registered."""
        from runtime.acp.client import AcpClient
        client = AcpClient(command=["echo"], cwd="/tmp")
        # Don't actually start — just verify the logic
        # allow_paths=[] means no fs handlers
        self.assertEqual(client._transport._request_handlers, {})


class TestTransportRequestDispatch(unittest.TestCase):
    """Integration test: transport routes agent-initiated requests to handlers."""

    def test_fs_read_via_transport(self) -> None:
        """Spawn a fake agent that sends fs/read_text_file request back to MCO."""
        from runtime.acp.transport import JsonRpcTransport

        agent_script = r'''
import json
import sys

for line in sys.stdin:
    msg = json.loads(line.strip())
    if "id" not in msg:
        continue
    method = msg.get("method", "")
    if method == "initialize":
        resp = {"jsonrpc": "2.0", "id": msg["id"], "result": {"agentInfo": {"name": "t", "version": "1"}}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
        # Now send a request BACK to MCO
        req = {"jsonrpc": "2.0", "id": 999, "method": "fs/read_text_file", "params": {"path": "test.txt"}}
        sys.stdout.write(json.dumps(req) + "\n")
        sys.stdout.flush()
        # Read MCO's response to our request
        resp_line = sys.stdin.readline()
        resp_data = json.loads(resp_line)
        # Echo it back as a notification so the test can verify
        notif = {"jsonrpc": "2.0", "method": "fs_result", "params": resp_data}
        sys.stdout.write(json.dumps(notif) + "\n")
        sys.stdout.flush()
'''
        with tempfile.TemporaryDirectory() as tmp:
            test_file = os.path.join(tmp, "test.txt")
            with open(test_file, "w") as f:
                f.write("file content here")

            transport = JsonRpcTransport()
            transport.register_handler(
                "fs/read_text_file",
                lambda params: {"content": open(os.path.join(tmp, params["path"])).read()},
            )
            transport.start(command=[sys.executable, "-c", agent_script], cwd=tmp)
            try:
                result = transport.send_request("initialize", timeout=5.0)
                self.assertEqual(result["agentInfo"]["name"], "t")
                # Wait for the agent's fs request to be handled and echoed back
                time.sleep(0.5)
                notif = transport.receive_notification(timeout=3.0)
                self.assertIsNotNone(notif)
                self.assertEqual(notif["method"], "fs_result")
                self.assertIn("file content here", notif["params"].get("result", {}).get("content", ""))
            finally:
                transport.close()
