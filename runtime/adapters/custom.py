from __future__ import annotations

import shlex
from typing import Any, List

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, ProviderPresence, TaskInput
from .parsing import normalize_findings_from_text
from .shim import ShimAdapterBase


class CommandShimAdapter(ShimAdapterBase):
    def __init__(
        self,
        provider_id: str,
        command: List[str],
        permission_keys: List[str] | None = None,
    ) -> None:
        binary_name = command[0] if command else provider_id
        super().__init__(
            provider_id=provider_id,  # type: ignore[arg-type]
            binary_name=binary_name,
            capability_set=CapabilitySet(
                tiers=["C0", "C1", "C2"],
                supports_native_async=False,
                supports_poll_endpoint=False,
                supports_resume_after_restart=False,
                supports_schema_enforcement=False,
                min_supported_version="0.1",
                tested_os=["macos", "linux"],
            ),
        )
        self._command = list(command)
        self._permission_keys = list(permission_keys or [])

    @classmethod
    def from_command_text(
        cls,
        provider_id: str,
        command_text: str,
        permission_keys: List[str] | None = None,
    ) -> "CommandShimAdapter":
        return cls(provider_id=provider_id, command=shlex.split(command_text), permission_keys=permission_keys)

    def detect(self) -> ProviderPresence:
        binary = self._resolve_binary()
        if not binary:
            return ProviderPresence(
                provider=self.id,
                detected=False,
                binary_path=None,
                version=None,
                auth_ok=False,
                reason="binary_not_found",
            )
        return ProviderPresence(
            provider=self.id,
            detected=True,
            binary_path=binary,
            version=self._probe_version(binary),
            auth_ok=True,
            reason="ok",
        )

    def supported_permission_keys(self) -> List[str]:
        return list(self._permission_keys)

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "--version"]

    def _build_command(self, input_task: TaskInput) -> List[str]:
        return [*self._command, input_task.prompt]

    def _build_command_for_record(self) -> List[str]:
        return [*self._command, "<prompt>"]

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, self.id)  # type: ignore[arg-type]

