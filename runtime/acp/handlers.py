"""ACP fs/terminal request handlers.

These handle agent-initiated requests when the agent needs to read/write
files or run terminal commands through MCO.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import threading
from pathlib import Path
from typing import Any, Dict, List


def _check_path_allowed(path: str, cwd: str, allow_paths: List[str]) -> str:
    """Resolve path and check it falls within allowed directories. Returns resolved path."""
    resolved = Path(path)
    if not resolved.is_absolute():
        resolved = Path(cwd) / resolved
    resolved = resolved.resolve()
    cwd_resolved = Path(cwd).resolve()

    for allowed in allow_paths:
        allowed_resolved = (cwd_resolved / allowed).resolve()
        try:
            resolved.relative_to(allowed_resolved)
            return str(resolved)
        except ValueError:
            continue

    raise PermissionError("Path '{}' is outside allowed paths: {}".format(path, allow_paths))


def handle_fs_read(
    params: Dict[str, Any],
    cwd: str,
    allow_paths: List[str],
) -> Dict[str, Any]:
    """Handle fs/read_text_file request."""
    path = params.get("path", "")
    if not path:
        raise ValueError("Missing 'path' parameter")

    resolved = _check_path_allowed(path, cwd, allow_paths)
    if not os.path.isfile(resolved):
        raise FileNotFoundError("File not found: {}".format(resolved))

    content = Path(resolved).read_text(encoding="utf-8")
    return {"content": content}


def handle_fs_write(
    params: Dict[str, Any],
    cwd: str,
    allow_paths: List[str],
) -> Dict[str, Any]:
    """Handle fs/write_text_file request."""
    path = params.get("path", "")
    content = params.get("content", "")
    if not path:
        raise ValueError("Missing 'path' parameter")

    resolved = _check_path_allowed(path, cwd, allow_paths)
    Path(resolved).parent.mkdir(parents=True, exist_ok=True)
    Path(resolved).write_text(content, encoding="utf-8")
    return {}


class TerminalManager:
    """Manages terminal subprocess lifecycle for ACP terminal/* methods."""

    def __init__(self, cwd: str) -> None:
        self._cwd = cwd
        self._terminals: Dict[str, subprocess.Popen] = {}
        self._output_buffers: Dict[str, List[str]] = {}
        self._next_id = 1
        self._lock = threading.Lock()

    def create(self, command: str) -> str:
        """Create a terminal subprocess. Returns terminal_id."""
        with self._lock:
            tid = "term-{}".format(self._next_id)
            self._next_id += 1

        cmd = shlex.split(command)
        if not cmd:
            raise ValueError("Empty terminal command")

        proc = subprocess.Popen(
            cmd,
            cwd=self._cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
        )
        with self._lock:
            self._terminals[tid] = proc
            self._output_buffers[tid] = []

        # Background reader
        def _reader():
            for line in proc.stdout:
                with self._lock:
                    buf = self._output_buffers.get(tid)
                    if buf is not None:
                        buf.append(line)
        threading.Thread(target=_reader, daemon=True).start()

        return tid

    def output(self, terminal_id: str) -> str:
        """Return buffered output and clear buffer."""
        with self._lock:
            buf = self._output_buffers.get(terminal_id, [])
            text = "".join(buf)
            buf.clear()
        return text

    def wait_for_exit(self, terminal_id: str, timeout: float = 60.0) -> int:
        """Wait for terminal to exit. Returns exit code."""
        proc = self._terminals.get(terminal_id)
        if proc is None:
            raise ValueError("Unknown terminal: {}".format(terminal_id))
        try:
            return proc.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            proc.kill()
            return -1

    def kill(self, terminal_id: str) -> None:
        """Kill a terminal process."""
        proc = self._terminals.get(terminal_id)
        if proc and proc.poll() is None:
            proc.kill()

    def release(self, terminal_id: str) -> None:
        """Release a terminal and clean up resources."""
        self.kill(terminal_id)
        self._terminals.pop(terminal_id, None)
        self._output_buffers.pop(terminal_id, None)

    def close_all(self) -> None:
        """Release all terminals."""
        for tid in list(self._terminals):
            self.release(tid)
