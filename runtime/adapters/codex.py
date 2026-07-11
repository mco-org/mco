from __future__ import annotations

from typing import Any, List

from ..answer_transport import AnswerTransport, decode_codex_events
from ..contracts import CapabilitySet, TaskInput
from .shim import ShimAdapterBase


class CodexAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="codex",
            binary_name="codex",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3", "C4", "C5"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=True,
                supports_schema_enforcement=True,
                min_supported_version="0.46.0",
                tested_os=["macos"],
            ),
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "login", "status"]

    def supported_permission_keys(self) -> List[str]:
        return ["sandbox", "approval_policy", "bypass"]

    def supported_model_keys(self) -> List[str]:
        return ["model"]

    def supported_context_keys(self) -> List[str]:
        return ["context_files"]

    def decode_transport(self, raw: str) -> AnswerTransport:
        return decode_codex_events(raw)

    def _build_command(self, input_task: TaskInput) -> List[str]:
        sandbox = "workspace-write"
        raw_permissions = input_task.metadata.get("provider_permissions")
        if isinstance(raw_permissions, dict):
            value = raw_permissions.get("sandbox")
            if isinstance(value, str) and value.strip():
                sandbox = value.strip()
        approval_policy = raw_permissions.get("approval_policy") if isinstance(raw_permissions, dict) else None
        bypass = raw_permissions.get("bypass") if isinstance(raw_permissions, dict) else None
        context_read_only_paths = input_task.metadata.get("context_read_only_paths", [])
        has_context_read_only_paths = (
            isinstance(context_read_only_paths, list)
            and any(isinstance(path, str) and path for path in context_read_only_paths)
        )
        if has_context_read_only_paths:
            # Codex --add-dir would make the context writable. A file-backed
            # stage therefore uses the built-in read-only sandbox instead.
            sandbox = "read-only"
            bypass = None
        cmd = [
            "codex",
        ]
        if bypass == "true":
            cmd.append("--dangerously-bypass-approvals-and-sandbox")
        else:
            if isinstance(approval_policy, str) and approval_policy.strip():
                cmd.extend(["--ask-for-approval", approval_policy.strip()])
        cmd.extend(["exec", "--skip-git-repo-check", "-C", input_task.repo_root])
        if bypass != "true":
            cmd.extend(["--sandbox", sandbox])
        cmd.append("--json")
        # Context policy is opt-in: only apply when provider_context key is present.
        if "provider_context" in input_task.metadata:
            ctx = input_task.metadata.get("provider_context", {})
            if not isinstance(ctx, dict):
                ctx = {}
            if ctx.get("context_files") is not True:
                cmd.extend(["--ignore-user-config", "--ignore-rules"])
        output_schema_path = input_task.metadata.get("output_schema_path")
        if isinstance(output_schema_path, str) and output_schema_path.strip():
            cmd.extend(["--output-schema", output_schema_path.strip()])
        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            cmd.extend(["--model", model.strip()])
        cmd.append(input_task.prompt)
        return cmd

    def _build_command_for_record(self) -> List[str]:
        return [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "-C",
            "<repo_root>",
            "--sandbox",
            "workspace-write",
            "--json",
            "--output-schema",
            "<schema-path>",
            "<prompt>",
        ]

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        if return_code == 0:
            return True
        # Codex may emit MCP startup errors and still return useful JSON events.
        if stdout_text.strip() and "\"type\":\"turn.completed\"" in stdout_text:
            return True
        if stdout_text.strip() and "\"ok\":true" in stdout_text:
            return True
        if "mcp client" in stderr_text.lower() and stdout_text.strip():
            return True
        return False
