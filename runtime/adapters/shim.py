from __future__ import annotations

import json
import os
import shutil
import signal
import subprocess
import time
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List, Optional, TextIO

from ..artifacts import expected_paths
from ..contracts import (
    CapabilitySet,
    NormalizeContext,
    NormalizedFinding,
    ProviderId,
    ProviderPresence,
    TaskInput,
    TaskRunRef,
    TaskStatus,
)
from ..errors import classify_error, detect_warnings
from ..types import ErrorKind


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ShimRunHandle:
    process: subprocess.Popen[str]
    stdout_path: Path
    stderr_path: Path
    provider_result_path: Path
    stdout_file: TextIO
    stderr_file: TextIO


_ENV_VARS_TO_STRIP = (
    "CLAUDECODE",
)


def _sanitize_env() -> Dict[str, str]:
    """Return a copy of os.environ with known conflicting variables removed."""
    env = os.environ.copy()
    for key in _ENV_VARS_TO_STRIP:
        env.pop(key, None)
    return env


class ShimAdapterBase:
    id: ProviderId

    def __init__(self, provider_id: ProviderId, binary_name: str, capability_set: CapabilitySet) -> None:
        self.id = provider_id
        self.binary_name = binary_name
        self._capability_set = capability_set
        self._runs: Dict[str, ShimRunHandle] = {}

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
        auth_ok, reason = self._probe_auth(binary)
        return ProviderPresence(
            provider=self.id,
            detected=True,
            binary_path=binary,
            version=version,
            auth_ok=auth_ok,
            reason=reason,
        )

    def capabilities(self) -> CapabilitySet:
        return self._capability_set

    def supported_permission_keys(self) -> List[str]:
        return []

    def run(self, input_task: TaskInput) -> TaskRunRef:
        command_override = input_task.metadata.get("command_override")
        cmd = command_override if isinstance(command_override, list) else self._build_command(input_task)
        if not isinstance(cmd, list) or not cmd:
            raise ValueError("adapter run command is empty")

        artifact_root = str(input_task.metadata.get("artifact_root", "/tmp/mco"))
        paths = expected_paths(artifact_root, input_task.task_id, (self.id,))
        root = paths["root"]
        paths["providers_dir"].mkdir(parents=True, exist_ok=True)
        paths["raw_dir"].mkdir(parents=True, exist_ok=True)

        stdout_path = paths[f"raw/{self.id}.stdout.log"]
        stderr_path = paths[f"raw/{self.id}.stderr.log"]
        provider_result_path = paths[f"providers/{self.id}.json"]
        run_id = f"{self.id}-{uuid.uuid4().hex[:12]}"

        stdout_file = stdout_path.open("w", encoding="utf-8")
        stderr_file = stderr_path.open("w", encoding="utf-8")
        process = subprocess.Popen(
            cmd,
            cwd=input_task.repo_root,
            stdout=stdout_file,
            stderr=stderr_file,
            text=True,
            start_new_session=True,
            env=_sanitize_env(),
        )
        self._runs[run_id] = ShimRunHandle(
            process=process,
            stdout_path=stdout_path,
            stderr_path=stderr_path,
            provider_result_path=provider_result_path,
            stdout_file=stdout_file,
            stderr_file=stderr_file,
        )
        return TaskRunRef(
            task_id=input_task.task_id,
            provider=self.id,
            run_id=run_id,
            artifact_path=str(root),
            started_at=now_iso(),
            pid=process.pid,
            session_id=None,
        )

    @staticmethod
    def _close_io(handle: ShimRunHandle) -> None:
        try:
            handle.stdout_file.close()
        except Exception:
            pass
        try:
            handle.stderr_file.close()
        except Exception:
            pass

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        handle = self._runs.get(ref.run_id)
        if handle is None:
            return TaskStatus(
                task_id=ref.task_id,
                provider=self.id,
                run_id=ref.run_id,
                attempt_state="EXPIRED",
                completed=True,
                heartbeat_at=None,
                output_path=None,
                error_kind=ErrorKind.NON_RETRYABLE_INVALID_INPUT,
                exit_code=None,
                message="run_handle_not_found",
            )

        return_code = handle.process.poll()
        if return_code is None:
            return TaskStatus(
                task_id=ref.task_id,
                provider=self.id,
                run_id=ref.run_id,
                attempt_state="STARTED",
                completed=False,
                heartbeat_at=now_iso(),
                output_path=str(handle.provider_result_path),
                error_kind=None,
                exit_code=None,
                message="running",
            )

        self._close_io(handle)

        stdout_text = handle.stdout_path.read_text(encoding="utf-8") if handle.stdout_path.exists() else ""
        stderr_text = handle.stderr_path.read_text(encoding="utf-8") if handle.stderr_path.exists() else ""
        success = self._is_success(return_code, stdout_text, stderr_text)
        error_kind = None if success else classify_error(return_code, stderr_text)
        warnings = [warning.value for warning in detect_warnings(stderr_text)]

        payload = {
            "provider": self.id,
            "task_id": ref.task_id,
            "run_id": ref.run_id,
            "pid": ref.pid,
            "command": self._build_command_for_record(),
            "started_at": ref.started_at,
            "completed_at": now_iso(),
            "exit_code": return_code,
            "success": success,
            "error_kind": error_kind.value if error_kind else None,
            "warnings": warnings,
            "stdout_path": str(handle.stdout_path),
            "stderr_path": str(handle.stderr_path),
        }
        handle.provider_result_path.write_text(json.dumps(payload, ensure_ascii=True, indent=2), encoding="utf-8")
        self._runs.pop(ref.run_id, None)

        return TaskStatus(
            task_id=ref.task_id,
            provider=self.id,
            run_id=ref.run_id,
            attempt_state="SUCCEEDED" if success else "FAILED",
            completed=True,
            heartbeat_at=now_iso(),
            output_path=str(handle.provider_result_path),
            error_kind=error_kind,
            exit_code=return_code,
            message="completed",
        )

    def cancel(self, ref: TaskRunRef) -> None:
        handle = self._runs.get(ref.run_id)
        if handle is None:
            return
        if handle.process.poll() is not None:
            self._close_io(handle)
            self._runs.pop(ref.run_id, None)
            return
        try:
            os.killpg(os.getpgid(handle.process.pid), signal.SIGTERM)
        except ProcessLookupError:
            self._close_io(handle)
            self._runs.pop(ref.run_id, None)
            return
        time.sleep(0.2)
        if handle.process.poll() is None:
            try:
                os.killpg(os.getpgid(handle.process.pid), signal.SIGKILL)
            except ProcessLookupError:
                self._close_io(handle)
                self._runs.pop(ref.run_id, None)
                return
            time.sleep(0.1)
        if handle.process.poll() is not None:
            self._close_io(handle)
            self._runs.pop(ref.run_id, None)

    def normalize(self, raw: object, ctx: NormalizeContext) -> List[NormalizedFinding]:
        raise NotImplementedError

    def _resolve_binary(self) -> Optional[str]:
        env = _sanitize_env()
        return shutil.which(self.binary_name, path=env.get("PATH"))

    def _probe_version(self, binary: str) -> Optional[str]:
        result = subprocess.run(
            [binary, "--version"],
            capture_output=True,
            text=True,
            check=False,
            env=_sanitize_env(),
        )
        lines = (result.stdout or result.stderr).splitlines()
        return lines[-1].strip() if lines else None

    def _probe_auth(self, binary: str) -> tuple[bool, str]:
        cmd = self._auth_check_command(binary)
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            check=False,
            env=_sanitize_env(),
        )
        if result.returncode == 0:
            return True, "ok"

        output = f"{result.stdout or ''}\n{result.stderr or ''}".lower()
        config_markers = ("configuration", "config", "unknown key", "invalid", "toml", "yaml")
        if any(marker in output for marker in config_markers):
            return False, "probe_config_error"
        auth_markers = ("not logged", "auth", "unauthorized", "token", "api key", "login")
        if any(marker in output for marker in auth_markers):
            return False, "auth_check_failed"
        return False, "probe_unknown_error"

    def _auth_check_command(self, binary: str) -> List[str]:
        raise NotImplementedError

    def _build_command(self, input_task: TaskInput) -> List[str]:
        raise NotImplementedError

    def _build_command_for_record(self) -> List[str]:
        return []

    def _is_success(self, return_code: int, stdout_text: str, stderr_text: str) -> bool:
        _ = stdout_text
        _ = stderr_text
        return return_code == 0
