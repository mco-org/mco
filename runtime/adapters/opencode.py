from __future__ import annotations

from typing import Any, List

from ..answer_transport import AnswerTransport, decode_json_text_events
from ..contracts import CapabilitySet, TaskInput
from .shim import ShimAdapterBase


class OpenCodeAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="opencode",
            binary_name="opencode",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3", "C4"],
                supports_native_async=True,
                supports_poll_endpoint=True,
                supports_resume_after_restart=True,
                supports_schema_enforcement=False,
                min_supported_version="1.2.11",
                tested_os=["macos"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "auth", "list"]

    def supported_context_keys(self) -> List[str]:
        # OpenCode 2 removed --pure; no per-run plugin isolation is verified.
        return []

    def supports_context_files(self) -> bool:
        return True

    def supported_model_keys(self) -> List[str]:
        return ["model"]

    def decode_transport(self, raw: str) -> AnswerTransport:
        return decode_json_text_events(raw)

    def supported_permission_keys(self) -> List[str]:
        return ["agent_mode", "auto"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        cmd = ["opencode", "run"]
        permissions = input_task.metadata.get("provider_permissions", {})
        agent_mode = permissions.get("agent_mode", "plan") if isinstance(permissions, dict) else "plan"
        auto = permissions.get("auto", "false") if isinstance(permissions, dict) else "false"
        if agent_mode not in ("plan", "build"):
            raise ValueError("unsupported OpenCode agent_mode: {}".format(agent_mode))
        if auto not in ("false", "true"):
            raise ValueError("unsupported OpenCode auto value: {}".format(auto))
        cmd.extend(["--agent", str(agent_mode)])
        if auto == "true":
            cmd.append("--auto")
        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            cmd.extend(["--model", model.strip()])
        # ShimAdapterBase starts the process in repo_root; OpenCode 2 removed --dir.
        cmd.extend([input_task.prompt, "--format", "json"])
        return cmd

    def _build_command_for_record(self) -> List[str]:
        return [
            "opencode", "run", "--agent", "plan", "<prompt>",
            "--format", "json",
        ]
