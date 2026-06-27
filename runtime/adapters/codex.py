from __future__ import annotations

from typing import Any, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, TaskInput
from .parsing import normalize_findings_from_text
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
        return ["sandbox"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        sandbox = "workspace-write"
        raw_permissions = input_task.metadata.get("provider_permissions")
        if isinstance(raw_permissions, dict):
            value = raw_permissions.get("sandbox")
            if isinstance(value, str) and value.strip():
                sandbox = value.strip()
        cmd = [
            "codex",
            "exec",
            "--skip-git-repo-check",
            "-C",
            input_task.repo_root,
            "--sandbox",
            sandbox,
            "--json",
        ]
        output_schema_path = input_task.metadata.get("output_schema_path")
        if isinstance(output_schema_path, str) and output_schema_path.strip():
            cmd.extend(["--output-schema", output_schema_path.strip()])
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

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, "codex")
