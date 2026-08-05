"""Cross-platform process helpers for the runtime.

These shim Unix-only stdlib behavior so the runtime works on Windows:
- os.getuid() does not exist on win32; fall back to the username.
- subprocess cannot spawn ".cmd" shims from a bare name on Windows.
- os.killpg/os.getpgid are Unix-only; fall back to terminate/kill.
"""

from __future__ import annotations

import os
import shutil
import signal
from typing import List


def user_suffix() -> str:
    """Return a stable per-user identifier for temp/artifact paths.

    os.getuid() is Unix-only; fall back to the Windows username on win32.
    """
    if hasattr(os, "getuid"):
        return str(os.getuid())
    return os.environ.get("USERNAME") or os.environ.get("USER") or "user"


def resolve_spawn_arg(cmd: List[str]) -> List[str]:
    """Resolve a bare command name to a spawnable executable.

    subprocess on Windows appends only ".exe" to bare names, so npm-style
    ".cmd" shims (opencode, copilot, ...) fail with FileNotFoundError.
    Resolving via shutil.which fixes this without requiring a shell.
    """
    if not cmd:
        return cmd
    resolved = shutil.which(cmd[0])
    if resolved:
        return [resolved, *cmd[1:]]
    return cmd


def terminate_process(process) -> None:
    """Terminate a subprocess, handling Unix-only process groups."""
    if hasattr(os, "killpg"):
        os.killpg(os.getpgid(process.pid), signal.SIGTERM)
    else:
        process.terminate()


def kill_process(process) -> None:
    """Force-kill a subprocess, handling Unix-only process groups."""
    if hasattr(os, "killpg"):
        os.killpg(os.getpgid(process.pid), signal.SIGKILL)
    else:
        process.kill()
