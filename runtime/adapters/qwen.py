from __future__ import annotations

from typing import Any, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, TaskInput
from .parsing import normalize_findings_from_text
from .shim import ShimAdapterBase


class QwenAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="qwen",
            binary_name="qwen",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=False,
                min_supported_version="0.10.6",
                tested_os=["macos"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "Reply with exactly OK", "--output-format", "text", "--auth-type", "qwen-oauth"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        return ["qwen", input_task.prompt, "--output-format", "json", "--auth-type", "qwen-oauth", "-y"]

    def _build_command_for_record(self) -> List[str]:
        return ["qwen", "<prompt>", "--output-format", "json", "--auth-type", "qwen-oauth", "-y"]

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, "qwen")

