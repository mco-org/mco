from __future__ import annotations

from typing import Any, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, TaskInput
from .parsing import normalize_findings_from_text
from .shim import ShimAdapterBase


class ClaudeAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="claude",
            binary_name="claude",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3", "C4", "C5", "C6"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=True,
                min_supported_version="2.1.59",
                tested_os=["macos"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "auth", "status"]

    def supported_permission_keys(self) -> List[str]:
        return ["permission_mode"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        permission_mode = "plan"
        raw_permissions = input_task.metadata.get("provider_permissions")
        if isinstance(raw_permissions, dict):
            value = raw_permissions.get("permission_mode")
            if isinstance(value, str) and value.strip():
                permission_mode = value.strip()
        return [
            "claude",
            "-p",
            "--permission-mode",
            permission_mode,
            "--output-format",
            "text",
            input_task.prompt,
        ]

    def _build_command_for_record(self) -> List[str]:
        return ["claude", "-p", "--permission-mode", "plan", "--output-format", "text", "<prompt>"]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        if return_code != 0:
            return False
        text = f"{stdout_text}\n{stderr_text}".lower()
        return "api error" not in text

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, "claude")
