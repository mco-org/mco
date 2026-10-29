from __future__ import annotations

import io
import shutil
import subprocess
import tarfile
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ShellLineEndingTests(unittest.TestCase):
    def test_windows_autocrlf_keeps_shell_scripts_executable_in_checkouts_and_archives(self) -> None:
        script = b"#!/usr/bin/env bash\nset -eu\nprintf 'OK\\n'\n"
        with tempfile.TemporaryDirectory() as tmp:
            repo = Path(tmp)

            def git(*args: str) -> bytes:
                return subprocess.run(
                    ["git", "-C", str(repo), *args], check=True,
                    capture_output=True, timeout=20,
                ).stdout

            git("init")
            git("config", "user.name", "Shell test")
            git("config", "user.email", "shell@example.invalid")
            git("config", "commit.gpgsign", "false")
            git("config", "core.autocrlf", "true")
            attributes = ROOT / ".gitattributes"
            if attributes.exists():
                shutil.copyfile(attributes, repo / ".gitattributes")
            for name in ("probe.sh", "probe.bash"):
                (repo / name).write_bytes(script)
            git("add", ".")
            git("commit", "-m", "shell fixture")
            for name in ("probe.sh", "probe.bash"):
                (repo / name).unlink()
            git("checkout", "--", "probe.sh", "probe.bash")
            archive = git("archive", "--format=tar", "HEAD")
            with tarfile.open(fileobj=io.BytesIO(archive)) as tar:
                for name in ("probe.sh", "probe.bash"):
                    with self.subTest(name=name, output="checkout"):
                        self.assertEqual((repo / name).read_bytes(), script)
                    with self.subTest(name=name, output="archive"):
                        self.assertEqual(tar.extractfile(name).read(), script)
