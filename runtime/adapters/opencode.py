from __future__ import annotations

from typing import Any, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, TaskInput
from .parsing import normalize_findings_from_text
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
        return ["plugins"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        cmd = ["opencode", "run"]
        # Context policy is opt-in: only apply when provider_context key is present.
        if "provider_context" in input_task.metadata:
            ctx = input_task.metadata.get("provider_context", {})
            if not isinstance(ctx, dict):
                ctx = {}
            if "plugins" in ctx and ctx.get("plugins") is not True:
                cmd.append("--pure")
        cmd.extend([input_task.prompt, "--format", "json", "--dir", input_task.repo_root])
        return cmd

    def _build_command_for_record(self) -> List[str]:
        return ["opencode", "run", "<prompt>", "--format", "json", "--dir", "<repo_root>"]

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, "opencode")
