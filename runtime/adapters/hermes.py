from __future__ import annotations

from typing import Any, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, TaskInput
from .parsing import normalize_findings_from_text
from .shim import ShimAdapterBase


class HermesAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="hermes",
            binary_name="hermes",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=False,
                min_supported_version="0.17.0",
                tested_os=["macos"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "status"]

    def supported_model_keys(self) -> List[str]:
        return ["model", "provider"]

    def supported_context_keys(self) -> List[str]:
        return ["skills", "context_files"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        # Hermes oneshot mode auto-bypasses approval prompts by design.
        cmd = ["hermes"]
        if input_task.metadata.get("yolo") is True:
            cmd.append("--yolo")
        if input_task.metadata.get("accept_hooks") is True:
            cmd.append("--accept-hooks")
        if input_task.metadata.get("ignore_rules") is True:
            cmd.append("--ignore-rules")
        # Context policy is opt-in: only apply when provider_context key is present.
        if "provider_context" in input_task.metadata:
            ctx = input_task.metadata.get("provider_context", {})
            if not isinstance(ctx, dict):
                ctx = {}
            # Only add --safe-mode when context_files is explicitly False.
            # When absent, Hermes uses its default ambient context behavior.
            if ctx.get("context_files") is False:
                cmd.append("--safe-mode")
            skills = ctx.get("skills")
            if isinstance(skills, list) and skills:
                for skill_name in skills:
                    cmd.extend(["--skills", str(skill_name)])
        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            cmd.extend(["--model", model.strip()])
        provider = input_task.metadata.get("provider")
        if isinstance(provider, str) and provider.strip():
            cmd.extend(["--provider", provider.strip()])
        cmd.extend(["-z", input_task.prompt])
        return cmd

    def _build_command_for_record(self) -> List[str]:
        return ["hermes", "-z", "<prompt>"]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        if return_code != 0:
            return False
        return len(stdout_text.strip()) > 0

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, "hermes")
