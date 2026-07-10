from __future__ import annotations

from typing import Any, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, TaskInput
from .parsing import normalize_findings_from_text
from .shim import ShimAdapterBase


class GrokAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="grok",
            binary_name="grok",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=False,
                min_supported_version="unknown",
                tested_os=["macos", "linux"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "models"]

    def supported_permission_keys(self) -> List[str]:
        return ["permission_mode", "approval_mode"]

    def supported_model_keys(self) -> List[str]:
        return ["model"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        command = [
            "grok",
            "--no-auto-update",
            "-p",
            input_task.prompt,
            "--output-format",
            "plain",
        ]
        permissions = input_task.metadata.get("provider_permissions", {})
        permission_mode = permissions.get("permission_mode") if isinstance(permissions, dict) else None
        approval_mode = permissions.get("approval_mode") if isinstance(permissions, dict) else None
        if permission_mode not in (None, "", "plan", "acceptEdits", "bypassPermissions"):
            raise ValueError("unsupported Grok permission_mode: {}".format(permission_mode))
        if approval_mode not in (None, "", "ask", "always-approve"):
            raise ValueError("unsupported Grok approval_mode: {}".format(approval_mode))
        if isinstance(permission_mode, str) and permission_mode:
            command.extend(["--permission-mode", permission_mode])
        if approval_mode == "always-approve":
            command.append("--always-approve")
        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            command.extend(["--model", model.strip()])
        return command

    def _build_command_for_record(self) -> List[str]:
        return ["grok", "--no-auto-update", "-p", "<prompt>", "--output-format", "plain"]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        return return_code == 0 and bool(stdout_text.strip())

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, "grok")
