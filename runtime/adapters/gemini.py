from __future__ import annotations

from typing import Any, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, TaskInput
from .parsing import normalize_findings_from_text
from .shim import ShimAdapterBase


class GeminiAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="gemini",
            binary_name="gemini",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=False,
                supports_schema_enforcement=False,
                min_supported_version="0.1.7",
                tested_os=["macos"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "-p", "Reply with exactly OK"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        return ["gemini", "-p", input_task.prompt, "-y"]

    def _build_command_for_record(self) -> List[str]:
        return ["gemini", "-p", "<prompt>", "-y"]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        if return_code != 0:
            return False
        text = f"{stdout_text}\n{stderr_text}".lower()
        if "unknown arguments" in text:
            return False
        if "api error" in text:
            return False
        return True

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, "gemini")

