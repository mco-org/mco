from __future__ import annotations

from typing import List

from ..contracts import CapabilitySet, TaskInput
from .shim import ShimAdapterBase


class AgyAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="agy",
            binary_name="agy",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=True,
                min_supported_version="1.2.3",
                tested_os=["macos"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "models"]

    def supported_permission_keys(self) -> List[str]:
        return ["mode", "sandbox", "dangerously_skip_permissions"]

    def supported_model_keys(self) -> List[str]:
        return ["model"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        permissions = input_task.metadata.get("provider_permissions", {})
        mode = permissions.get("mode", "plan") if isinstance(permissions, dict) else "plan"
        if mode not in ("plan", "accept-edits"):
            raise ValueError("unsupported agy mode: {}".format(mode))

        command = ["agy", "--mode", str(mode), "--output-format", "text"]
        bypass_value = permissions.get("dangerously_skip_permissions", "false")
        if bypass_value not in ("true", "false"):
            raise ValueError("unsupported agy permission bypass value: {}".format(bypass_value))
        bypass = bypass_value == "true"
        sandbox = permissions.get("sandbox", "false" if bypass else "true")
        if sandbox not in ("true", "false"):
            raise ValueError("unsupported agy sandbox value: {}".format(sandbox))
        if sandbox == "true":
            command.append("--sandbox")
        if bypass:
            command.append("--dangerously-skip-permissions")
        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            command.extend(["--model", model.strip()])
        command.extend(["--print", input_task.prompt])
        return command

    def _build_command_for_record(self) -> List[str]:
        return ["agy", "--mode", "plan", "--output-format", "text", "--sandbox", "--print", "<prompt>"]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        return return_code == 0 and bool(stdout_text.strip())
