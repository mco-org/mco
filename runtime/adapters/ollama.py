from __future__ import annotations

import subprocess
from typing import Any, List, Optional

from ..contracts import CapabilitySet, NormalizeContext, NormalizedFinding, ProviderPresence, TaskInput
from .parsing import normalize_findings_from_text
from .shim import ShimAdapterBase, _sanitize_env


class OllamaAdapter(ShimAdapterBase):
    def __init__(self, provider_id: str = "ollama", model: str = "codellama") -> None:
        super().__init__(
            provider_id=provider_id,  # type: ignore[arg-type]
            binary_name="ollama",
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
        self.model = model

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
        version = self._probe_version(binary)
        if not self._model_available(binary):
            return ProviderPresence(
                provider=self.id,
                detected=True,
                binary_path=binary,
                version=version,
                auth_ok=False,
                reason="model_not_found",
            )
        return ProviderPresence(
            provider=self.id,
            detected=True,
            binary_path=binary,
            version=version,
            auth_ok=True,
            reason="ok",
        )

    def _auth_check_command(self, binary: str) -> List[str]:
        return [binary, "list"]

    def _probe_version(self, binary: str) -> Optional[str]:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            env=_sanitize_env(),
        )
        output = (result.stdout or result.stderr).strip()
        return output.splitlines()[-1].strip() if output else None

    def _model_available(self, binary: str) -> bool:
        result = subprocess.run(
            [binary, "list"],
            capture_output=True,
            text=True,
            check=False,
            env=_sanitize_env(),
        )
        if result.returncode != 0:
            return False
        output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        return self.model.lower() in output

    def _build_command(self, input_task: TaskInput) -> List[str]:
        return ["ollama", "run", self.model, input_task.prompt]

    def _build_command_for_record(self) -> List[str]:
        return ["ollama", "run", self.model, "<prompt>"]

    def normalize(self, raw: Any, ctx: NormalizeContext) -> List[NormalizedFinding]:
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, self.id)  # type: ignore[arg-type]

