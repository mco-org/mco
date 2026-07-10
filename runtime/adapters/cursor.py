from __future__ import annotations

from typing import Any, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, TaskInput
from .parsing import normalize_findings_from_text
from .shim import ShimAdapterBase


class CursorAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="cursor",
            binary_name="agent",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=False,
                min_supported_version="unknown",
                tested_os=["macos", "linux", "windows"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "status"]

    def supported_permission_keys(self) -> List[str]:
        return ["mode", "force", "sandbox"]

    def supported_model_keys(self) -> List[str]:
        return ["model"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        command = ["agent", "-p", input_task.prompt, "--output-format", "text"]
        permissions = input_task.metadata.get("provider_permissions", {})
        mode = permissions.get("mode") if isinstance(permissions, dict) else None
        resolved_mode = str(mode).strip() if isinstance(mode, str) and mode.strip() else "ask"
        if resolved_mode not in ("agent", "ask", "plan"):
            raise ValueError("unsupported Cursor mode: {}".format(resolved_mode))
        if resolved_mode != "agent":
            command.extend(["--mode", resolved_mode])
        force = permissions.get("force") if isinstance(permissions, dict) else None
        if force not in (None, "", "false", "true"):
            raise ValueError("unsupported Cursor force value: {}".format(force))
        if force == "true":
            command.append("--force")
        sandbox = permissions.get("sandbox") if isinstance(permissions, dict) else None
        if sandbox not in (None, "", "enabled", "disabled"):
            raise ValueError("unsupported Cursor sandbox value: {}".format(sandbox))
        if isinstance(sandbox, str) and sandbox:
            command.extend(["--sandbox", sandbox])
        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            command.extend(["--model", model.strip()])
        return command

    def _build_command_for_record(self) -> List[str]:
        return ["agent", "-p", "<prompt>", "--output-format", "text", "--mode", "ask"]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        return return_code == 0 and bool(stdout_text.strip())

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, "cursor")
