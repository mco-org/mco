from __future__ import annotations

import re
import subprocess
from dataclasses import replace
from pathlib import Path
from typing import List

from ..answer_transport import AnswerTransport, decode_kimi_events
from ..contracts import CapabilitySet, ProviderPresence, TaskInput
from .shim import ShimAdapterBase, _sanitize_env


class KimiAdapter(ShimAdapterBase):
    def __init__(self) -> None:
        super().__init__(
            provider_id="kimi",
            binary_name="kimi",
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2", "C3"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=False,
                supports_schema_enforcement=False,
                min_supported_version="2.5.2",
                tested_os=[],
            ),
        )

    def detect(self) -> ProviderPresence:
        presence = super().detect()
        if not presence.detected:
            return presence
        version = presence.version or ""
        if not re.fullmatch(r"\d+\.\d+\.\d+", version):
            return replace(presence, auth_ok=False, reason="version_not_verified")
        if tuple(int(part) for part in version.split(".")) < (2, 5, 2):
            return replace(presence, auth_ok=False, reason="unsupported_version")
        return presence

    def _probe_version(self, binary: str) -> str | None:
        result = subprocess.run(
            [binary, "--version"], capture_output=True, text=True,
            check=False, env=_sanitize_env(),
        )
        if result.returncode != 0:
            return None
        # Legacy 1.x prints a migration notice after its version line.
        for line in (result.stdout or result.stderr).splitlines():
            match = re.fullmatch(r"(?:kimi, version )?(\d+\.\d+\.\d+)", line.strip())
            if match:
                return match.group(1)
        return None

    def _probe_auth(self, binary: str) -> tuple[bool, str]:
        # Kimi Code has no non-interactive auth-status command. `doctor`
        # validates TOML only (and succeeds even with no config files).
        # Defer credential validation to the requested run, without inference
        # or reading credentials during discovery, as the ACP adapter does.
        return True, "auth_deferred_to_run"

    def supported_permission_keys(self) -> List[str]:
        return ["access"]

    def supports_context_files(self) -> bool:
        return True

    def supported_model_keys(self) -> List[str]:
        return ["model"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        command = ["kimi", "-p", input_task.prompt, "--output-format", "stream-json"]
        permissions = input_task.metadata.get("provider_permissions", {})
        access = permissions.get("access", "read_only") if isinstance(permissions, dict) else "read_only"
        if access not in ("read_only", "write", "yolo"):
            raise ValueError("unsupported Kimi access: {}".format(access))
        if access != "yolo":
            profile_name = "kimi-read-only.md" if access == "read_only" else "kimi-write.md"
            profile = Path(__file__).resolve().parent.parent / "data" / profile_name
            if not profile.is_file():
                raise ValueError("Kimi tool profile is missing: {}".format(profile))
            command.extend(["--agent-file", str(profile)])
        # Print mode is already `auto`; --auto, --yolo and --plan conflict
        # with -p. Agent-file tool allowlists are enforced before execution,
        # independently of approval mode. They are not an OS path sandbox.
        model = input_task.metadata.get("model")
        if isinstance(model, str) and model.strip():
            command.extend(["--model", model.strip()])
        return command

    def _build_command_for_record(self) -> List[str]:
        return ["kimi", "-p", "<prompt>", "--output-format", "stream-json"]

    def decode_transport(self, raw: str) -> AnswerTransport:
        return decode_kimi_events(raw)

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        return return_code == 0 and self.decode_transport(stdout_text).status == "succeeded"
