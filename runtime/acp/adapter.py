"""ACP adapter — implements ProviderAdapter using ACP transport.

Falls back to the underlying shim adapter when the agent doesn't support ACP.
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from ..artifacts import expected_paths
from ..contracts import (
    CapabilitySet,
    NormalizeContext,
    NormalizedFinding,
    ProviderId,
    ProviderPresence,
    TaskInput,
    TaskRunRef,
    TaskStatus,
)
from ..types import ErrorKind
from .client import AcpClient
from .transport import JsonRpcError, TransportClosed


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# Known ACP launch commands per provider.
# Each agent may support ACP via a specific flag or mode.
_ACP_COMMANDS: Dict[str, List[str]] = {
    "claude": ["claude", "code", "--transport", "stdio"],
    "codex": ["codex", "--acp"],
    "gemini": ["gemini", "--acp"],
}


@dataclass
class _AcpRunHandle:
    """Tracks an in-flight ACP prompt."""
    client: AcpClient
    session_id: str
    completed: bool = False
    success: bool = False
    response_text: str = ""
    error_message: str = ""
    started_at: float = 0.0
    prompt_thread: Optional[threading.Thread] = None


class AcpAdapter:
    """Provider adapter using ACP (Agent Client Protocol) transport.

    Spawns the agent in ACP mode, communicates via JSON-RPC over stdio.
    Each run() creates a fresh agent process + session.
    """

    def __init__(
        self,
        provider_id: str,
        binary_name: str,
        acp_command: Optional[List[str]] = None,
        capability_set: Optional[CapabilitySet] = None,
    ) -> None:
        self.id = provider_id
        self._binary_name = binary_name
        self._acp_command = acp_command or _ACP_COMMANDS.get(provider_id, [])
        self._capability_set = capability_set or CapabilitySet(
            tiers=["C0", "C1", "C2"],
            supports_native_async=True,
            supports_poll_endpoint=False,
            supports_resume_after_restart=False,
            supports_schema_enforcement=False,
            min_supported_version="0.1",
            tested_os=["macos", "linux"],
        )
        self._runs: Dict[str, _AcpRunHandle] = {}

    def detect(self) -> ProviderPresence:
        """Check if the agent binary exists and supports ACP."""
        binary = shutil.which(self._binary_name)
        if not binary:
            return ProviderPresence(
                provider=self.id,
                detected=False,
                binary_path=None,
                version=None,
                auth_ok=False,
                reason="binary_not_found",
            )

        # We detect the binary but can't verify ACP support without spawning.
        # Mark as detected; actual ACP handshake happens in run().
        return ProviderPresence(
            provider=self.id,
            detected=True,
            binary_path=binary,
            version=None,
            auth_ok=True,
            reason="acp_transport",
        )

    def capabilities(self) -> CapabilitySet:
        return self._capability_set

    def run(self, input_task: TaskInput) -> TaskRunRef:
        """Start an ACP session and send the prompt."""
        artifact_root = str(input_task.metadata.get("artifact_root", "/tmp/mco"))
        paths = expected_paths(artifact_root, input_task.task_id, (self.id,))
        root = paths["root"]
        paths["providers_dir"].mkdir(parents=True, exist_ok=True)
        paths["raw_dir"].mkdir(parents=True, exist_ok=True)

        stderr_path = str(paths["raw_dir"] / "{}.stderr.log".format(self.id))
        run_id = "{}-acp-{}".format(self.id, uuid.uuid4().hex[:12])

        client = AcpClient(
            command=self._acp_command,
            cwd=input_task.repo_root,
            stderr_path=stderr_path,
        )

        try:
            client.start()
            agent_info = client.initialize(timeout=30.0)
            session_id = client.new_session(
                working_directory=input_task.repo_root,
                timeout=10.0,
            )
        except (JsonRpcError, TransportClosed, TimeoutError, OSError) as exc:
            client.close()
            # Write error to stderr log
            Path(stderr_path).write_text(
                "ACP initialization failed: {}\n".format(exc),
                encoding="utf-8",
            )
            raise RuntimeError(
                "ACP initialization failed for {}: {}".format(self.id, exc),
            )

        handle = _AcpRunHandle(
            client=client,
            session_id=session_id,
            started_at=time.time(),
        )
        self._runs[run_id] = handle

        # Send prompt asynchronously — prompt() blocks until the RPC response
        # returns AND notifications are drained to idle state.
        def _run_prompt() -> None:
            try:
                client.prompt(session_id, input_task.prompt, timeout=input_task.timeout_seconds)
                handle.response_text = client.collect_text()
                handle.success = True
            except (JsonRpcError, TransportClosed, TimeoutError) as exc:
                handle.error_message = str(exc)
                handle.success = False
            finally:
                handle.completed = True

        handle.prompt_thread = threading.Thread(target=_run_prompt, daemon=True)
        handle.prompt_thread.start()

        return TaskRunRef(
            task_id=input_task.task_id,
            provider=self.id,
            run_id=run_id,
            artifact_path=str(root),
            started_at=_now_iso(),
            pid=client.pid,
            session_id=session_id,
        )

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        """Check if the ACP prompt has completed."""
        handle = self._runs.get(ref.run_id)
        if handle is None:
            return TaskStatus(
                task_id=ref.task_id,
                provider=self.id,
                run_id=ref.run_id,
                attempt_state="EXPIRED",
                completed=True,
                heartbeat_at=None,
                output_path=None,
                error_kind=ErrorKind.NON_RETRYABLE_INVALID_INPUT,
                message="run_handle_not_found",
            )

        if not handle.completed:
            return TaskStatus(
                task_id=ref.task_id,
                provider=self.id,
                run_id=ref.run_id,
                attempt_state="STARTED",
                completed=False,
                heartbeat_at=_now_iso(),
                output_path=None,
                message="running",
            )

        # Completed — write output to artifact files
        raw_dir = Path(ref.artifact_path) / "raw"
        stdout_path = raw_dir / "{}.stdout.log".format(self.id)
        provider_result_path = Path(ref.artifact_path) / "providers" / "{}.json".format(self.id)

        stdout_path.write_text(handle.response_text, encoding="utf-8")

        payload = {
            "provider": self.id,
            "task_id": ref.task_id,
            "run_id": ref.run_id,
            "pid": ref.pid,
            "transport": "acp",
            "started_at": ref.started_at,
            "completed_at": _now_iso(),
            "success": handle.success,
            "error_message": handle.error_message,
            "stdout_path": str(stdout_path),
        }
        provider_result_path.write_text(
            json.dumps(payload, ensure_ascii=True, indent=2),
            encoding="utf-8",
        )

        # Clean up
        handle.client.close()
        self._runs.pop(ref.run_id, None)

        attempt_state = "SUCCEEDED" if handle.success else "FAILED"
        error_kind = None if handle.success else ErrorKind.NON_RETRYABLE_PROCESS_FAILURE

        return TaskStatus(
            task_id=ref.task_id,
            provider=self.id,
            run_id=ref.run_id,
            attempt_state=attempt_state,
            completed=True,
            heartbeat_at=_now_iso(),
            output_path=str(provider_result_path),
            error_kind=error_kind,
            message=handle.error_message if not handle.success else "completed",
        )

    def cancel(self, ref: TaskRunRef) -> None:
        """Cancel the running ACP prompt."""
        handle = self._runs.get(ref.run_id)
        if handle is None:
            return

        # Close transport first — this immediately unblocks the prompt thread
        # (which is stuck in send_request → event.wait) via TransportClosed.
        handle.client.close()

        # Wait for prompt thread to finish before modifying handle state
        pt = handle.prompt_thread
        if pt is not None:
            pt.join(timeout=5)

        handle.completed = True
        handle.success = False
        handle.error_message = "Cancelled"
        self._runs.pop(ref.run_id, None)

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        """Normalize findings — delegates to parsing module."""
        from ..adapters.parsing import normalize_findings_from_text
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, self.id)
