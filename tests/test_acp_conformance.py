"""Data-driven ACP protocol conformance tests.

Reads scenario definitions from acp_conformance/scenarios.json,
spawns fake agents with the specified behavior, and validates
the ACP client against each scenario's assertions.
"""
from __future__ import annotations

import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from typing import Any, Dict, List, Optional

from runtime.acp.client import AcpClient
from runtime.acp.transport import JsonRpcError, TransportClosed

from tests.acp_conformance.agents import get_agent_script


_SCENARIOS_PATH = Path(__file__).parent / "acp_conformance" / "scenarios.json"


def _load_scenarios() -> List[Dict[str, Any]]:
    return json.loads(_SCENARIOS_PATH.read_text(encoding="utf-8"))


class _ScenarioRunner:
    """Executes a single conformance scenario against a fake ACP agent."""

    def __init__(self, scenario: Dict[str, Any], test_case: unittest.TestCase) -> None:
        self.scenario = scenario
        self.tc = test_case
        self.tmp = tempfile.mkdtemp()
        behavior = scenario.get("agent_behavior", "standard")
        self.agent_script = get_agent_script(behavior)
        self.client: Optional[AcpClient] = None
        self.session_id: str = ""
        self.last_result: Any = None

    def run(self) -> None:
        self.client = AcpClient(
            command=[sys.executable, "-c", self.agent_script],
            cwd=self.tmp,
        )
        self.client.start()
        try:
            for step in self.scenario["steps"]:
                self._execute_step(step)
        finally:
            self.client.close()
            import shutil
            shutil.rmtree(self.tmp, ignore_errors=True)

    def _execute_step(self, step: Dict[str, Any]) -> None:
        action = step["action"]

        if action == "initialize":
            self.client.initialize(timeout=5.0)
            return

        if action == "new_session":
            self.session_id = self.client.new_session(timeout=5.0)
            return

        if action == "send":
            method = step["method"]
            params = dict(step.get("params", {}))
            # Inject sessionId for session-scoped methods
            if method.startswith("session/") and method != "session/new":
                if "sessionId" not in params:
                    params["sessionId"] = self.session_id

            # Use high-level client.prompt() for session/prompt to get
            # proper notification collection (including post-RPC drain).
            if method == "session/prompt":
                content = params.get("content", [])
                text = content[0].get("text", "") if content else ""
                try:
                    self.client.prompt(self.session_id, text, timeout=10.0)
                    self.last_result = {}
                except JsonRpcError as exc:
                    self.last_result = exc
            else:
                try:
                    self.last_result = self.client._transport.send_request(
                        method=method, params=params, timeout=10.0,
                    )
                except JsonRpcError as exc:
                    self.last_result = exc
            return

        if action == "expect_result":
            self.tc.assertNotIsInstance(
                self.last_result, JsonRpcError,
                "Expected success result but got error: {}".format(self.last_result),
            )
            if "has_keys" in step:
                for key in step["has_keys"]:
                    self.tc.assertIn(
                        key, self.last_result or {},
                        "Result missing key '{}'".format(key),
                    )
            if "agentInfo_has" in step:
                info = (self.last_result or {}).get("agentInfo", {})
                for key in step["agentInfo_has"]:
                    self.tc.assertIn(key, info, "agentInfo missing '{}'".format(key))
            return

        if action == "expect_error":
            self.tc.assertIsInstance(
                self.last_result, JsonRpcError,
                "Expected JSON-RPC error but got success",
            )
            if "code" in step:
                self.tc.assertEqual(
                    self.last_result.code, step["code"],
                    "Expected error code {} but got {}".format(
                        step["code"], self.last_result.code,
                    ),
                )
            return

        if action == "expect_text_collected":
            # Drain any remaining notifications
            time.sleep(0.2)
            self.client.drain_updates()
            text = self.client.collect_text()
            if "contains" in step:
                self.tc.assertIn(
                    step["contains"], text.lower(),
                    "Collected text does not contain '{}'. Got: '{}'".format(
                        step["contains"], text[:200],
                    ),
                )
            return

        self.tc.fail("Unknown action: {}".format(action))


def _make_test(scenario: Dict[str, Any]):
    """Create a test method for a scenario."""
    def test_method(self: unittest.TestCase) -> None:
        runner = _ScenarioRunner(scenario, self)
        runner.run()
    test_method.__doc__ = scenario.get("description", scenario["id"])
    return test_method


class AcpConformanceTests(unittest.TestCase):
    """Auto-generated conformance tests from scenarios.json."""
    pass


# Dynamically generate test methods from scenarios
for _scenario in _load_scenarios():
    _test_name = "test_{}".format(_scenario["id"])
    setattr(AcpConformanceTests, _test_name, _make_test(_scenario))
