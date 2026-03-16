"""Fake ACP agent scripts for conformance testing.

Each function returns a Python script string that implements a specific
agent behavior pattern over JSON-RPC stdio.
"""

# Standard compliant agent: notifications before RPC response
STANDARD_AGENT = r'''
import json
import sys

session_counter = 0
for line in sys.stdin:
    msg = json.loads(line.strip())
    if "id" not in msg:
        continue
    method = msg.get("method", "")
    params = msg.get("params", {})
    msg_id = msg["id"]

    if method == "initialize":
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "0.1",
            "agentInfo": {"name": "conformance-agent", "version": "1.0.0"},
            "capabilities": {}
        }}
    elif method == "session/new":
        session_counter += 1
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {
            "sessionId": "sess-{}".format(session_counter)
        }}
    elif method == "session/prompt":
        sid = params.get("sessionId", "")
        content = params.get("content", [])
        text = content[0].get("text", "") if content else ""
        # Send working notification
        working = {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": sid, "state": "working",
            "content": [{"type": "text", "text": "Processing: " + text}]
        }}
        sys.stdout.write(json.dumps(working) + "\n")
        sys.stdout.flush()
        # Send idle notification with result
        idle = {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": sid, "state": "idle",
            "content": [{"type": "text", "text": "Result: " + text}]
        }}
        sys.stdout.write(json.dumps(idle) + "\n")
        sys.stdout.flush()
        # Then RPC response
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    elif method == "session/cancel":
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    else:
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
'''

# Agent that sends RPC response BEFORE session/update (reverse order)
REVERSE_ORDER_AGENT = r'''
import json
import sys
import time

session_counter = 0
for line in sys.stdin:
    msg = json.loads(line.strip())
    if "id" not in msg:
        continue
    method = msg.get("method", "")
    params = msg.get("params", {})
    msg_id = msg["id"]

    if method == "initialize":
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "0.1",
            "agentInfo": {"name": "reverse-agent", "version": "1.0.0"},
            "capabilities": {}
        }}
    elif method == "session/new":
        session_counter += 1
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {
            "sessionId": "sess-{}".format(session_counter)
        }}
    elif method == "session/prompt":
        sid = params.get("sessionId", "")
        content = params.get("content", [])
        text = content[0].get("text", "") if content else ""
        # Send RPC response FIRST
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        sys.stdout.write(json.dumps(resp) + "\n")
        sys.stdout.flush()
        # Delay then send notification
        time.sleep(1.0)
        update = {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": sid, "state": "idle",
            "content": [{"type": "text", "text": "Late result: " + text}]
        }}
        sys.stdout.write(json.dumps(update) + "\n")
        sys.stdout.flush()
        continue
    elif method == "session/cancel":
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    else:
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}

    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
'''

# Agent that returns JSON-RPC error for unknown methods
ERROR_ON_UNKNOWN_AGENT = r'''
import json
import sys

session_counter = 0
for line in sys.stdin:
    msg = json.loads(line.strip())
    if "id" not in msg:
        continue
    method = msg.get("method", "")
    params = msg.get("params", {})
    msg_id = msg["id"]

    if method == "initialize":
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {
            "protocolVersion": "0.1",
            "agentInfo": {"name": "strict-agent", "version": "1.0.0"},
            "capabilities": {}
        }}
    elif method == "session/new":
        session_counter += 1
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {
            "sessionId": "sess-{}".format(session_counter)
        }}
    elif method == "session/prompt":
        sid = params.get("sessionId", "")
        content = params.get("content", [])
        text = content[0].get("text", "") if content else ""
        update = {"jsonrpc": "2.0", "method": "session/update", "params": {
            "sessionId": sid, "state": "idle",
            "content": [{"type": "text", "text": "Result: " + text}]
        }}
        sys.stdout.write(json.dumps(update) + "\n")
        sys.stdout.flush()
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    elif method == "session/cancel":
        resp = {"jsonrpc": "2.0", "id": msg_id, "result": {}}
    else:
        resp = {"jsonrpc": "2.0", "id": msg_id, "error": {
            "code": -32601, "message": "Method not found: {}".format(method)
        }}

    sys.stdout.write(json.dumps(resp) + "\n")
    sys.stdout.flush()
'''


def get_agent_script(behavior: str = "standard") -> str:
    """Return the agent script for a given behavior pattern."""
    agents = {
        "standard": STANDARD_AGENT,
        "response_before_notification": REVERSE_ORDER_AGENT,
        "error_on_unknown": ERROR_ON_UNKNOWN_AGENT,
    }
    return agents.get(behavior, STANDARD_AGENT)
