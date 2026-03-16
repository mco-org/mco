"""Tests for runtime/diff_utils.py — git diff operations."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest


def _init_repo(tmp: str, branch: str = "main") -> str:
    """Create a bare-minimum git repo in tmp with given default branch."""
    subprocess.run(["git", "init", "-b", branch, tmp], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", tmp, "config", "user.email", "test@test.com"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", tmp, "config", "user.name", "Test"],
        capture_output=True, check=True,
    )
    subprocess.run(
        ["git", "-C", tmp, "commit", "--allow-empty", "-m", "init"],
        capture_output=True, check=True,
    )
    return tmp


def _write_file(repo: str, name: str, content: str = "x") -> None:
    path = os.path.join(repo, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _commit_file(repo: str, name: str, content: str = "x") -> None:
    _write_file(repo, name, content)
    subprocess.run(["git", "-C", repo, "add", name], capture_output=True, check=True)
    subprocess.run(
        ["git", "-C", repo, "commit", "-m", f"add {name}"],
        capture_output=True, check=True,
    )


# ── detect_main_branch ──

from runtime.diff_utils import detect_main_branch


class TestDetectMainBranch(unittest.TestCase):
    def test_detects_main(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            self.assertEqual(detect_main_branch(tmp), "main")

    def test_detects_master(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "master")
            self.assertEqual(detect_main_branch(tmp), "master")

    def test_fallback_when_neither(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "develop")
            self.assertEqual(detect_main_branch(tmp), "main")


# ── merge_base ──

from runtime.diff_utils import merge_base


class TestMergeBase(unittest.TestCase):
    def test_merge_base_with_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            subprocess.run(
                ["git", "-C", tmp, "checkout", "-b", "feature"],
                capture_output=True, check=True,
            )
            subprocess.run(
                ["git", "-C", tmp, "commit", "--allow-empty", "-m", "feat"],
                capture_output=True, check=True,
            )
            result = merge_base(tmp, "main")
            self.assertTrue(len(result) >= 7)

    def test_merge_base_invalid_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            with self.assertRaises(ValueError):
                merge_base(tmp, "nonexistent-branch")


# ── diff_files ──

from runtime.diff_utils import diff_files


class TestDiffFiles(unittest.TestCase):
    def test_branch_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            _commit_file(tmp, "base.py", "base")
            subprocess.run(
                ["git", "-C", tmp, "checkout", "-b", "feat"],
                capture_output=True, check=True,
            )
            _commit_file(tmp, "new.py", "new")
            _commit_file(tmp, "base.py", "changed")
            files = diff_files(tmp, "branch", "main")
            self.assertEqual(sorted(files), ["base.py", "new.py"])

    def test_staged_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            _commit_file(tmp, "a.py", "a")
            _write_file(tmp, "a.py", "a-modified")
            subprocess.run(
                ["git", "-C", tmp, "add", "a.py"],
                capture_output=True, check=True,
            )
            files = diff_files(tmp, "staged")
            self.assertEqual(files, ["a.py"])

    def test_unstaged_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            _commit_file(tmp, "b.py", "b")
            _write_file(tmp, "b.py", "b-modified")
            files = diff_files(tmp, "unstaged")
            self.assertEqual(files, ["b.py"])

    def test_empty_diff(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            files = diff_files(tmp, "unstaged")
            self.assertEqual(files, [])


# ── diff_content ──

from runtime.diff_utils import diff_content


class TestDiffContent(unittest.TestCase):
    def test_returns_diff_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            _commit_file(tmp, "a.py", "line1\n")
            subprocess.run(
                ["git", "-C", tmp, "checkout", "-b", "feat"],
                capture_output=True, check=True,
            )
            _commit_file(tmp, "a.py", "line1\nline2\n")
            content = diff_content(tmp, "branch", "main")
            self.assertIn("a.py", content)
            self.assertIn("+line2", content)

    def test_truncation_adds_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            _commit_file(tmp, "a.py", "x\n")
            subprocess.run(
                ["git", "-C", tmp, "checkout", "-b", "feat"],
                capture_output=True, check=True,
            )
            _commit_file(tmp, "a.py", "\n".join(f"line{i}" for i in range(200)))
            content = diff_content(tmp, "branch", "main", max_total_bytes=200)
            self.assertIn("diff truncated", content)

    def test_empty_diff_returns_empty(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            content = diff_content(tmp, "unstaged")
            self.assertEqual(content, "")

    def test_file_list_always_present(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            _commit_file(tmp, "a.py", "x\n")
            _commit_file(tmp, "b.py", "y\n")
            subprocess.run(
                ["git", "-C", tmp, "checkout", "-b", "feat"],
                capture_output=True, check=True,
            )
            _commit_file(tmp, "a.py", "\n".join(f"line{i}" for i in range(200)))
            _commit_file(tmp, "b.py", "\n".join(f"line{i}" for i in range(200)))
            content = diff_content(tmp, "branch", "main", max_total_bytes=300)
            self.assertIn("a.py", content)
            self.assertIn("b.py", content)
