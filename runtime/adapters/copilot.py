from __future__ import annotations

from typing import Any, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, TaskInput
from .parsing import normalize_findings_from_text
from .shim import ShimAdapterBase


class CopilotAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="copilot",
            binary_name="copilot",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=False,
                min_supported_version="1.0.65",
                tested_os=["macos"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "-p", "Reply with exactly OK", "-s", "--allow-all-tools", "--no-ask-user"]

    def supported_model_keys(self) -> List[str]:
        return ["model"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        # One-shot, non-interactive run:
        #   -p              run a single prompt and exit
        #   -s              print only the agent's final response (clean stdout)
        #   --allow-all-tools / --no-ask-user  never block on a permission or ask_user prompt
        cmd = [
            "copilot",
            "-p",
            input_task.prompt,
            "-s",
            "--allow-all-tools",
            "--no-ask-user",
        ]
        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            cmd.extend(["--model", model.strip()])
        return cmd

    def _build_command_for_record(self) -> List[str]:
        return ["copilot", "-p", "<prompt>", "-s", "--allow-all-tools", "--no-ask-user"]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        if return_code != 0:
            return False
        return len(stdout_text.strip()) > 0

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, "copilot")
