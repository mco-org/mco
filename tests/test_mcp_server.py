from __future__ import annotations

import asyncio
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from runtime.mcp_server import _ProgressBridge, _sync_review, _sync_run, run_server


try:
    from mcp import ClientSession
    from mcp.client.stdio import StdioServerParameters, stdio_client
    from mcp.server.fastmcp import FastMCP
except ImportError:
    ClientSession = None
    FastMCP = None


class McpInvocationTests(unittest.TestCase):
    def setUp(self) -> None:
        # Isolate from the developer's real ~/.mco/config.json so policy
        # assertions test the code, not whatever the host happens to configure.
        self._config_dir = tempfile.TemporaryDirectory(prefix="mco-test-config-")
        self.addCleanup(self._config_dir.cleanup)
        patcher = patch.dict(os.environ, {"MCO_CONFIG_DIR": self._config_dir.name})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_run_returns_operational_raw_output(self) -> None:
        expected = {
            "stage": "run",
            "task_id": "run-1",
            "status": "complete",
            "outputs": [{"status": "success", "output": "raw answer"}],
            "exit_code": 0,
            "artifact_root": None,
        }
        with tempfile.TemporaryDirectory() as repo, patch("runtime.invocation_runtime.run_invocation_workflow", return_value=expected) as workflow:
            result = _sync_run(repo, "task", "pi")

        self.assertTrue(result["ok"])
        self.assertEqual(result["data"], expected)
        self.assertEqual(workflow.call_args.kwargs["hard_timeout_seconds"], 180)

    def test_review_uses_read_only_execution_and_raw_output(self) -> None:
        expected = {
            "stage": "run",
            "task_id": "run-1",
            "status": "complete",
            "outputs": [{"status": "success", "output": "review answer"}],
            "exit_code": 0,
            "artifact_root": None,
        }
        with tempfile.TemporaryDirectory() as repo, patch("runtime.invocation_runtime.run_invocation_workflow", return_value=expected) as workflow:
            result = _sync_review(repo, "review", "pi")

        self.assertTrue(result["ok"])
        self.assertNotIn("findings", result["data"])
        self.assertEqual(workflow.call_args.kwargs["hard_timeout_seconds"], 180)


@unittest.skipIf(FastMCP is None, "mcp optional dependency is not installed")
class McpServerRegistrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_serve_registers_tools_and_starts_stdio_transport(self) -> None:
        with patch.object(FastMCP, "run_stdio_async", new_callable=AsyncMock) as run_stdio:
            await run_server()

        run_stdio.assert_awaited_once_with()

    async def test_serve_exposes_tools_without_context_in_client_schema(self) -> None:
        root = Path(__file__).resolve().parent.parent
        server = StdioServerParameters(
            command=sys.executable,
            args=[str(root / "mco"), "serve"],
            cwd=root,
        )

        with tempfile.TemporaryFile(mode="w+") as errlog:
            async with stdio_client(server, errlog=errlog) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    result = await session.list_tools()

        tools = {tool.name: tool for tool in result.tools}
        self.assertEqual(set(tools), {"mco_doctor", "mco_review", "mco_run"})
        self.assertNotIn("ctx", tools["mco_review"].inputSchema["properties"])
        self.assertNotIn("ctx", tools["mco_run"].inputSchema["properties"])


class McpPolicyTests(unittest.TestCase):
    """MCP calls must honour the same merged config the CLI reads."""

    def setUp(self) -> None:
        self._config_dir = tempfile.TemporaryDirectory(prefix="mco-test-config-")
        self.addCleanup(self._config_dir.cleanup)
        patcher = patch.dict(os.environ, {"MCO_CONFIG_DIR": self._config_dir.name})
        patcher.start()
        self.addCleanup(patcher.stop)
        self._workflow_result = {
            "stage": "run", "task_id": "run-9", "status": "complete",
            "outputs": [], "exit_code": 0, "artifact_root": None,
        }

    def _write_global_config(self, policy: dict) -> None:
        path = os.path.join(self._config_dir.name, "config.json")
        with open(path, "w", encoding="utf-8") as handle:
            json.dump({"policy": policy}, handle)

    def test_review_applies_configured_policy_and_global_deadline(self) -> None:
        self._write_global_config({
            "timeout_seconds": 600,
            "stall_timeout_seconds": 300,
            "review_hard_timeout_seconds": 1500,
            "max_provider_parallelism": 2,
            "provider_timeouts": {"claude": 420},
        })
        with tempfile.TemporaryDirectory() as repo, patch(
            "runtime.invocation_runtime.run_invocation_workflow", return_value=self._workflow_result,
        ) as workflow:
            _sync_review(repo, "review", "pi")

        kwargs = workflow.call_args.kwargs
        self.assertEqual(kwargs["hard_timeout_seconds"], 600)
        self.assertEqual(kwargs["timeout_seconds"], 300)
        self.assertEqual(kwargs["global_timeout_seconds"], 1500)
        self.assertEqual(kwargs["max_provider_parallelism"], 2)
        self.assertEqual(kwargs["provider_timeouts"], {"claude": 420})

    def test_run_applies_configured_policy_too(self) -> None:
        self._write_global_config({"timeout_seconds": 480})
        with tempfile.TemporaryDirectory() as repo, patch(
            "runtime.invocation_runtime.run_invocation_workflow", return_value=self._workflow_result,
        ) as workflow:
            _sync_run(repo, "task", "pi")

        self.assertEqual(workflow.call_args.kwargs["hard_timeout_seconds"], 480)

    def test_per_call_overrides_win_over_config(self) -> None:
        self._write_global_config({"timeout_seconds": 600, "review_hard_timeout_seconds": 1500})
        with tempfile.TemporaryDirectory() as repo, patch(
            "runtime.invocation_runtime.run_invocation_workflow", return_value=self._workflow_result,
        ) as workflow:
            _sync_review(repo, "review", "pi", ".", "read_only", 90, 240)

        kwargs = workflow.call_args.kwargs
        self.assertEqual(kwargs["hard_timeout_seconds"], 90)
        self.assertEqual(kwargs["global_timeout_seconds"], 240)

    def test_invalid_configured_values_fall_back_to_defaults(self) -> None:
        self._write_global_config({"timeout_seconds": -5, "provider_timeouts": {"claude": 0}})
        with tempfile.TemporaryDirectory() as repo, patch(
            "runtime.invocation_runtime.run_invocation_workflow", return_value=self._workflow_result,
        ) as workflow:
            _sync_review(repo, "review", "pi")

        kwargs = workflow.call_args.kwargs
        self.assertEqual(kwargs["hard_timeout_seconds"], 180)
        self.assertEqual(kwargs["provider_timeouts"], {})

    def test_review_uses_a_model_pinned_in_config(self) -> None:
        self._write_global_config({"provider_models": {"pi": {"model": "pi-pinned", "provider": "github-copilot"}}})
        with tempfile.TemporaryDirectory() as repo, patch(
            "runtime.invocation_runtime.run_invocation_workflow", return_value=self._workflow_result,
        ) as workflow:
            _sync_review(repo, "review", "pi")

        self.assertEqual(
            [item.model for item in workflow.call_args.kwargs["invocations"]], ["pi-pinned"],
        )
        self.assertEqual(workflow.call_args.kwargs["provider_models"]["pi"]["provider"], "github-copilot")

    def test_a_bare_string_is_accepted_as_the_documented_pin_shorthand(self) -> None:
        # The CLI accepts "pi": "pi-pinned"; the MCP path must not ignore it.
        self._write_global_config({"provider_models": {"pi": "pi-pinned"}})
        with tempfile.TemporaryDirectory() as repo, patch(
            "runtime.invocation_runtime.run_invocation_workflow", return_value=self._workflow_result,
        ) as workflow:
            _sync_review(repo, "review", "pi")

        self.assertEqual(
            [item.model for item in workflow.call_args.kwargs["invocations"]], ["pi-pinned"],
        )

    def test_without_a_pin_the_provider_default_is_used(self) -> None:
        with tempfile.TemporaryDirectory() as repo, patch(
            "runtime.invocation_runtime.run_invocation_workflow", return_value=self._workflow_result,
        ) as workflow:
            _sync_review(repo, "review", "pi")

        self.assertEqual(
            [item.model for item in workflow.call_args.kwargs["invocations"]], ["default"],
        )

    def test_registered_agent_timeouts_are_merged_like_the_cli(self) -> None:
        with tempfile.TemporaryDirectory() as repo:
            with open(os.path.join(repo, ".mcorc.yaml"), "w", encoding="utf-8") as handle:
                handle.write(
                    "policy:\n"
                    "  provider_timeouts:\n"
                    "    claude: 420\n"
                    "agents:\n"
                    "  - name: claude\n"
                    "    command: claude\n"
                    "    timeout: 60\n"
                    "  - name: slowpoke\n"
                    "    command: slowpoke\n"
                    "    timeout: 900\n",
                )
            with patch(
                "runtime.invocation_runtime.run_invocation_workflow",
                return_value=self._workflow_result,
            ) as workflow:
                _sync_review(repo, "review", "pi")

        # An explicit policy entry stays authoritative; an agent-only timeout is adopted.
        self.assertEqual(
            workflow.call_args.kwargs["provider_timeouts"], {"claude": 420, "slowpoke": 900},
        )


class ProgressBridgeTests(unittest.IsolatedAsyncioTestCase):
    class _RecordingContext:
        def __init__(self) -> None:
            self.calls: list[tuple[float, float, str]] = []

        async def report_progress(self, progress: float, total: float, message: str) -> None:
            self.calls.append((progress, total, message))

    class _FailingContext:
        def __init__(self) -> None:
            self.calls = 0

        async def report_progress(self, progress: float, total: float, message: str) -> None:
            self.calls += 1
            raise RuntimeError("no progressToken from host")

    async def _drain(self) -> None:
        # Notifications are scheduled from worker threads and their done
        # callbacks land a further loop iteration later; yield until settled.
        for _ in range(10):
            await asyncio.sleep(0.01)

    async def test_lifecycle_events_become_progress_notifications(self) -> None:
        ctx = self._RecordingContext()
        bridge = _ProgressBridge(ctx, asyncio.get_running_loop(), total=2, min_interval_seconds=0.0)
        bridge({"type": "invocation_started", "provider": "claude"})
        bridge({"type": "invocation_finished", "provider": "claude", "status": "success"})
        bridge({"type": "task_finished", "status": "complete"})
        await self._drain()

        self.assertEqual([call[2] for call in ctx.calls], [
            "claude: started", "claude: success", "run complete",
        ])
        self.assertEqual(ctx.calls[1][0], 1.0)
        self.assertEqual(ctx.calls[0][1], 2.0)

    async def test_output_deltas_are_throttled(self) -> None:
        ctx = self._RecordingContext()
        bridge = _ProgressBridge(ctx, asyncio.get_running_loop(), total=1, min_interval_seconds=3600.0)
        for _ in range(5):
            bridge({"type": "output_delta", "provider": "codex", "delta": "x"})
        await self._drain()

        self.assertEqual(len(ctx.calls), 1)

    async def test_first_output_delta_emits_on_a_young_monotonic_clock(self) -> None:
        # time.monotonic() has an arbitrary epoch. On a freshly booted machine it
        # can be smaller than the throttle interval, which must not swallow the
        # first heartbeat - that one matters most for keeping a host alive.
        ctx = self._RecordingContext()
        bridge = _ProgressBridge(ctx, asyncio.get_running_loop(), total=1, min_interval_seconds=3600.0)
        with patch("time.monotonic", return_value=1.5):
            bridge({"type": "output_delta", "provider": "codex", "delta": "x"})
            bridge({"type": "output_delta", "provider": "codex", "delta": "y"})
        await self._drain()

        self.assertEqual([call[2] for call in ctx.calls], ["codex: working"])

    async def test_unknown_events_are_dropped(self) -> None:
        ctx = self._RecordingContext()
        bridge = _ProgressBridge(ctx, asyncio.get_running_loop(), total=1, min_interval_seconds=0.0)
        bridge({"type": "some_future_event", "provider": "codex"})
        await self._drain()

        self.assertEqual(ctx.calls, [])

    async def test_host_without_progress_support_disables_bridge(self) -> None:
        ctx = self._FailingContext()
        bridge = _ProgressBridge(ctx, asyncio.get_running_loop(), total=1, min_interval_seconds=0.0)
        bridge({"type": "invocation_started", "provider": "claude"})
        await self._drain()
        bridge({"type": "invocation_finished", "provider": "claude", "status": "success"})
        await self._drain()

        # One failed attempt, then silence: a run must never break on progress.
        self.assertEqual(ctx.calls, 1)


if __name__ == "__main__":
    unittest.main()
