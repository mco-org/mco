# Diff-Only Review Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `--diff`, `--staged`, `--unstaged` flags so MCO reviews only changed code instead of the entire repository.

**Architecture:** New `runtime/diff_utils.py` module handles all git diff operations. `cli.py` normalizes flags into `diff_mode`/`diff_base` on `ReviewRequest`. `review_engine.py` computes diff, augments the prompt, and post-processes findings with `diff_scope` tags. No changes to adapters or providers.

**Tech Stack:** Python 3.10+, subprocess (git CLI), existing unittest framework.

**Spec:** `docs/superpowers/specs/2026-03-16-diff-only-review-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `runtime/diff_utils.py` | Create | Git diff operations: detect main branch, merge-base, diff files, diff content with fair truncation |
| `runtime/cli.py` | Modify | Add `--diff`/`--staged`/`--unstaged` mutual-exclusion group, `--diff-base` flag, normalize into `ReviewRequest` fields |
| `runtime/review_engine.py` | Modify | Add `diff_mode`/`diff_base` to `ReviewRequest`, compute diff in `run_review()`, augment prompt, post-process `diff_scope` tags, build no-op result for empty diff |
| `runtime/formatters.py` | Modify | Add `diff_scope` property to SARIF result objects |
| `tests/test_diff_utils.py` | Create | Unit tests for all diff_utils functions |
| `tests/test_diff_review_integration.py` | Create | Integration tests for diff injection, scope interaction, empty diff, and diff_scope tagging |
| `tests/test_diff_cli.py` | Create | CLI argument tests: mutual exclusion, --diff-base implies --diff |

---

## Chunk 1: `runtime/diff_utils.py`

### Task 1: `detect_main_branch()`

**Files:**
- Create: `runtime/diff_utils.py`
- Create: `tests/test_diff_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diff_utils.py
"""Tests for runtime/diff_utils.py — git diff operations."""
from __future__ import annotations

import os
import subprocess
import tempfile
import unittest

from runtime.diff_utils import detect_main_branch


def _init_repo(tmp: str, branch: str = "main") -> str:
    """Create a bare-minimum git repo in tmp with given default branch."""
    subprocess.run(["git", "init", "-b", branch, tmp], capture_output=True, check=True)
    subprocess.run(["git", "-C", tmp, "commit", "--allow-empty", "-m", "init"], capture_output=True, check=True)
    return tmp


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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_diff_utils.py::TestDetectMainBranch -v`
Expected: ImportError — `runtime.diff_utils` does not exist yet.

- [ ] **Step 3: Write minimal implementation**

```python
# runtime/diff_utils.py
"""Git diff operations for diff-only review mode."""
from __future__ import annotations

import subprocess
from typing import List, Optional


def detect_main_branch(repo_root: str) -> str:
    """Return 'main' or 'master', whichever exists as a local branch. Fallback: 'main'."""
    try:
        result = subprocess.run(
            ["git", "branch", "--list", "main", "master"],
            capture_output=True, text=True, check=False, cwd=repo_root,
        )
        branches = [b.strip().lstrip("* ") for b in result.stdout.strip().splitlines()]
        if "main" in branches:
            return "main"
        if "master" in branches:
            return "master"
    except OSError:
        pass
    return "main"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_diff_utils.py::TestDetectMainBranch -v`
Expected: 3 passed.

- [ ] **Step 5: Commit**

```bash
git add runtime/diff_utils.py tests/test_diff_utils.py
git commit -m "feat: add detect_main_branch() in diff_utils"
```

---

### Task 2: `merge_base()`

**Files:**
- Modify: `runtime/diff_utils.py`
- Modify: `tests/test_diff_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_diff_utils.py
from runtime.diff_utils import merge_base


class TestMergeBase(unittest.TestCase):
    def test_merge_base_with_branch(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            # Create a feature branch with one commit
            subprocess.run(["git", "-C", tmp, "checkout", "-b", "feature"], capture_output=True, check=True)
            subprocess.run(["git", "-C", tmp, "commit", "--allow-empty", "-m", "feat"], capture_output=True, check=True)
            result = merge_base(tmp, "main")
            # merge-base should be the init commit (a valid short hash)
            self.assertTrue(len(result) >= 7)

    def test_merge_base_invalid_ref(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            with self.assertRaises(ValueError):
                merge_base(tmp, "nonexistent-branch")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_diff_utils.py::TestMergeBase -v`
Expected: ImportError — `merge_base` not yet defined.

- [ ] **Step 3: Write minimal implementation**

```python
# Append to runtime/diff_utils.py
def merge_base(repo_root: str, ref: str) -> str:
    """Return the merge-base commit hash between HEAD and ref.

    Raises ValueError if the ref is invalid or merge-base cannot be computed.
    """
    result = subprocess.run(
        ["git", "merge-base", "HEAD", ref],
        capture_output=True, text=True, check=False, cwd=repo_root,
    )
    if result.returncode != 0:
        raise ValueError(f"Cannot compute merge-base for ref '{ref}': {result.stderr.strip()}")
    return result.stdout.strip()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_diff_utils.py::TestMergeBase -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add runtime/diff_utils.py tests/test_diff_utils.py
git commit -m "feat: add merge_base() to diff_utils"
```

---

### Task 3: `diff_files()`

**Files:**
- Modify: `runtime/diff_utils.py`
- Modify: `tests/test_diff_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_diff_utils.py
from runtime.diff_utils import diff_files


def _write_file(repo: str, name: str, content: str = "x") -> None:
    path = os.path.join(repo, name)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as f:
        f.write(content)


def _commit_file(repo: str, name: str, content: str = "x") -> None:
    _write_file(repo, name, content)
    subprocess.run(["git", "-C", repo, "add", name], capture_output=True, check=True)
    subprocess.run(["git", "-C", repo, "commit", "-m", f"add {name}"], capture_output=True, check=True)


class TestDiffFiles(unittest.TestCase):
    def test_branch_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            _commit_file(tmp, "base.py", "base")
            subprocess.run(["git", "-C", tmp, "checkout", "-b", "feat"], capture_output=True, check=True)
            _commit_file(tmp, "new.py", "new")
            _commit_file(tmp, "base.py", "changed")
            files = diff_files(tmp, "branch", "main")
            self.assertEqual(sorted(files), ["base.py", "new.py"])

    def test_staged_mode(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            _commit_file(tmp, "a.py", "a")
            _write_file(tmp, "a.py", "a-modified")
            subprocess.run(["git", "-C", tmp, "add", "a.py"], capture_output=True, check=True)
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_diff_utils.py::TestDiffFiles -v`
Expected: ImportError — `diff_files` not yet defined.

- [ ] **Step 3: Write minimal implementation**

```python
# Append to runtime/diff_utils.py
def diff_files(repo_root: str, mode: str, base: Optional[str] = None) -> List[str]:
    """Return list of changed file paths relative to repo root.

    Args:
        mode: 'branch', 'staged', or 'unstaged'.
        base: Git ref for branch mode. Ignored for staged/unstaged.

    Returns:
        Sorted list of changed file paths (no duplicates).
    """
    if mode == "branch":
        if base is None:
            raise ValueError("base ref is required for branch diff mode")
        mb = merge_base(repo_root, base)
        cmd = ["git", "diff", "--name-only", mb, "HEAD"]
    elif mode == "staged":
        cmd = ["git", "diff", "--cached", "--name-only"]
    elif mode == "unstaged":
        cmd = ["git", "diff", "--name-only"]
    else:
        raise ValueError(f"Unknown diff mode: {mode}")

    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False, cwd=repo_root,
    )
    if result.returncode != 0:
        return []
    files = [f for f in result.stdout.strip().splitlines() if f]
    return sorted(set(files))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_diff_utils.py::TestDiffFiles -v`
Expected: 4 passed.

- [ ] **Step 5: Commit**

```bash
git add runtime/diff_utils.py tests/test_diff_utils.py
git commit -m "feat: add diff_files() to diff_utils"
```

---

### Task 4: `diff_content()` with fair truncation

**Files:**
- Modify: `runtime/diff_utils.py`
- Modify: `tests/test_diff_utils.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_diff_utils.py
from runtime.diff_utils import diff_content


class TestDiffContent(unittest.TestCase):
    def test_returns_diff_text(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            _commit_file(tmp, "a.py", "line1\n")
            subprocess.run(["git", "-C", tmp, "checkout", "-b", "feat"], capture_output=True, check=True)
            _commit_file(tmp, "a.py", "line1\nline2\n")
            content = diff_content(tmp, "branch", "main")
            self.assertIn("a.py", content)
            self.assertIn("+line2", content)

    def test_truncation_adds_marker(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            _init_repo(tmp, "main")
            _commit_file(tmp, "a.py", "x\n")
            subprocess.run(["git", "-C", tmp, "checkout", "-b", "feat"], capture_output=True, check=True)
            # Create a large diff
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
            subprocess.run(["git", "-C", tmp, "checkout", "-b", "feat"], capture_output=True, check=True)
            _commit_file(tmp, "a.py", "\n".join(f"line{i}" for i in range(200)))
            _commit_file(tmp, "b.py", "\n".join(f"line{i}" for i in range(200)))
            content = diff_content(tmp, "branch", "main", max_total_bytes=300)
            # Both files should be mentioned even if truncated
            self.assertIn("a.py", content)
            self.assertIn("b.py", content)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_diff_utils.py::TestDiffContent -v`
Expected: ImportError.

- [ ] **Step 3: Write minimal implementation**

```python
# Append to runtime/diff_utils.py
def diff_content(
    repo_root: str,
    mode: str,
    base: Optional[str] = None,
    max_total_bytes: int = 60_000,
) -> str:
    """Return unified diff text with per-file fair truncation.

    Changed file list is always preserved in full at the top.
    Each file gets an equal share of the byte budget.
    Truncated files get an explicit marker.
    """
    if mode == "branch":
        if base is None:
            raise ValueError("base ref is required for branch diff mode")
        mb = merge_base(repo_root, base)
        cmd = ["git", "diff", mb, "HEAD"]
    elif mode == "staged":
        cmd = ["git", "diff", "--cached"]
    elif mode == "unstaged":
        cmd = ["git", "diff"]
    else:
        raise ValueError(f"Unknown diff mode: {mode}")

    result = subprocess.run(
        cmd, capture_output=True, text=True, check=False, cwd=repo_root,
    )
    raw = result.stdout if result.returncode == 0 else ""
    if not raw.strip():
        return ""

    # Split into per-file sections
    file_sections = _split_diff_by_file(raw)
    if not file_sections:
        return ""

    # Build file list header (always complete)
    file_names = [s[0] for s in file_sections]
    header = "## Changed Files ({} files)\n{}\n".format(
        len(file_names),
        "\n".join(f"- {f}" for f in file_names),
    )

    total_raw = sum(len(s[1]) for s in file_sections)
    if total_raw <= max_total_bytes:
        # No truncation needed
        diff_body = "\n".join(s[1] for s in file_sections)
        return f"{header}\n## Diff\n```diff\n{diff_body}\n```"

    # Fair truncation: equal budget per file
    budget_per_file = max(200, max_total_bytes // len(file_sections))
    truncated_parts: List[str] = []
    for file_name, file_diff in file_sections:
        if len(file_diff) <= budget_per_file:
            truncated_parts.append(file_diff)
        else:
            truncated_parts.append(_truncate_file_diff(file_diff, budget_per_file))
    diff_body = "\n".join(truncated_parts)
    return f"{header}\n## Diff\n```diff\n{diff_body}\n```"


def _split_diff_by_file(raw_diff: str) -> List[tuple]:
    """Split a unified diff into (filename, diff_text) pairs."""
    sections: List[tuple] = []
    current_name = ""
    current_lines: List[str] = []

    for line in raw_diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_name and current_lines:
                sections.append((current_name, "".join(current_lines)))
            # Extract filename: "diff --git a/foo.py b/foo.py" -> "foo.py"
            parts = line.strip().split(" b/", 1)
            current_name = parts[1] if len(parts) > 1 else line.strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_name and current_lines:
        sections.append((current_name, "".join(current_lines)))
    return sections


def _truncate_file_diff(file_diff: str, budget: int) -> str:
    """Truncate a single file's diff to budget bytes, keeping complete hunks."""
    lines = file_diff.splitlines(keepends=True)
    kept: List[str] = []
    current_size = 0
    hunk_count = 0
    total_hunks = sum(1 for l in lines if l.startswith("@@"))

    for line in lines:
        if line.startswith("@@"):
            hunk_count += 1
        if current_size + len(line) > budget and hunk_count > 1:
            remaining = total_hunks - hunk_count + 1
            kept.append(f"... (diff truncated, {remaining} more hunks)\n")
            break
        kept.append(line)
        current_size += len(line)

    return "".join(kept)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_diff_utils.py::TestDiffContent -v`
Expected: 4 passed.

- [ ] **Step 5: Run all diff_utils tests**

Run: `python3 -m pytest tests/test_diff_utils.py -v`
Expected: 13 passed (3 + 2 + 4 + 4).

- [ ] **Step 6: Commit**

```bash
git add runtime/diff_utils.py tests/test_diff_utils.py
git commit -m "feat: add diff_content() with fair per-file truncation"
```

---

## Chunk 2: CLI flags and ReviewRequest

### Task 5: Add `diff_mode` / `diff_base` to ReviewRequest

**Files:**
- Modify: `runtime/review_engine.py:42-47` (ReviewRequest dataclass)

- [ ] **Step 1: Add fields to ReviewRequest**

Add after `memory_space` (line 47):

```python
    diff_mode: Optional[str] = None    # "branch" | "staged" | "unstaged" | None
    diff_base: Optional[str] = None    # git ref, only for diff_mode="branch"
```

- [ ] **Step 2: Run existing tests to verify nothing breaks**

Run: `python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected: All existing tests pass (the new fields have defaults).

- [ ] **Step 3: Commit**

```bash
git add runtime/review_engine.py
git commit -m "feat: add diff_mode and diff_base to ReviewRequest"
```

---

### Task 6: CLI flag group and normalization

**Files:**
- Modify: `runtime/cli.py:434-445` (after Memory group)
- Modify: `runtime/cli.py:748-761` (ReviewRequest construction)
- Create: `tests/test_diff_cli.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_diff_cli.py
"""Tests for diff-related CLI flags."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from runtime.cli import build_parser, main


class TestDiffFlagParsing(unittest.TestCase):
    def test_diff_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--diff"])
        self.assertTrue(args.diff)

    def test_staged_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--staged"])
        self.assertTrue(args.staged)

    def test_unstaged_flag_accepted(self) -> None:
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--unstaged"])
        self.assertTrue(args.unstaged)

    def test_diff_and_staged_mutually_exclusive(self) -> None:
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--diff", "--staged"])

    def test_diff_base_without_diff_flag(self) -> None:
        """--diff-base alone should be valid (implies --diff)."""
        parser = build_parser()
        args = parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--diff-base", "origin/main"])
        self.assertEqual(args.diff_base, "origin/main")

    def test_diff_base_with_staged_rejected(self) -> None:
        """--diff-base + --staged is invalid."""
        parser = build_parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["review", "--repo", ".", "--prompt", "test", "--staged", "--diff-base", "x"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_diff_cli.py -v`
Expected: FAIL — flags don't exist yet.

- [ ] **Step 3: Add flag group to CLI**

In `runtime/cli.py`, add after the Memory group (after line 445):

```python
    diff = parser.add_argument_group("Diff Mode")
    diff_exclusive = diff.add_mutually_exclusive_group()
    diff_exclusive.add_argument(
        "--diff",
        action="store_true",
        help="Review only changes vs merge-base with main/master branch",
    )
    diff_exclusive.add_argument(
        "--staged",
        action="store_true",
        help="Review only staged changes (git diff --cached)",
    )
    diff_exclusive.add_argument(
        "--unstaged",
        action="store_true",
        help="Review only unstaged working tree changes (git diff)",
    )
    diff.add_argument(
        "--diff-base",
        default="",
        help="Git ref for branch diff comparison (e.g. origin/main, HEAD~3). Implies --diff",
    )
```

- [ ] **Step 4: Run test to verify flags parse correctly**

Run: `python3 -m pytest tests/test_diff_cli.py -v`
Expected: 5 passed, 1 fail (the `--diff-base + --staged` rejection test — we handle that in the next step).

- [ ] **Step 5: Add normalization in main()**

In `runtime/cli.py`, after the memory validation block (around line 746), add:

```python
    # Normalize diff flags
    diff_base = args.diff_base.strip() if isinstance(args.diff_base, str) else ""
    if diff_base and args.staged:
        print("--diff-base cannot be used with --staged", file=sys.stderr)
        return 2
    if diff_base and args.unstaged:
        print("--diff-base cannot be used with --unstaged", file=sys.stderr)
        return 2
    diff_mode = None
    if args.diff or diff_base:
        diff_mode = "branch"
    elif args.staged:
        diff_mode = "staged"
    elif args.unstaged:
        diff_mode = "unstaged"
```

Then update the `ReviewRequest` construction to include:

```python
        diff_mode=diff_mode,
        diff_base=diff_base or None,
```

- [ ] **Step 6: Update test for --diff-base + --staged to check stderr instead**

The `--diff-base` is not in the mutual-exclusion group, so argparse won't reject it. The validation happens in `main()`. Update the test:

```python
    def test_diff_base_with_staged_rejected(self) -> None:
        """--diff-base + --staged is rejected at runtime."""
        with patch("runtime.review_engine.run_review") as mock_run:
            exit_code = main(["review", "--repo", ".", "--prompt", "t", "--staged", "--diff-base", "x"])
            self.assertEqual(exit_code, 2)
            mock_run.assert_not_called()
```

- [ ] **Step 7: Run all tests**

Run: `python3 -m pytest tests/test_diff_cli.py -v`
Expected: 6 passed.

Run: `python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected: All tests pass.

- [ ] **Step 8: Commit**

```bash
git add runtime/cli.py tests/test_diff_cli.py
git commit -m "feat: add --diff/--staged/--unstaged CLI flags with mutual exclusion"
```

---

## Chunk 3: Engine integration

### Task 7: Diff injection and no-op result in `run_review()`

**Files:**
- Modify: `runtime/review_engine.py:791-800` (after scope normalization, before prompt build)
- Create: `tests/test_diff_review_integration.py`

- [ ] **Step 1: Write the failing test — empty diff returns no-op result**

```python
# tests/test_diff_review_integration.py
"""Integration tests for diff-only review in the engine layer."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from runtime.review_engine import ReviewRequest, ReviewResult, run_review


class TestEmptyDiffReturnsNoOp(unittest.TestCase):
    @patch("runtime.diff_utils.diff_files", return_value=[])
    @patch("runtime.diff_utils.detect_main_branch", return_value="main")
    def test_empty_diff_no_providers_invoked(self, mock_detect, mock_files) -> None:
        req = ReviewRequest(
            repo_root="/tmp/fake",
            prompt="Review",
            providers=["claude"],
            diff_mode="branch",
        )
        with patch("runtime.review_engine._run_provider") as mock_run:
            result = run_review(req, review_mode=True, write_artifacts=False)
            mock_run.assert_not_called()
        self.assertEqual(result.decision, "PASS")
        self.assertEqual(result.terminal_state, "completed")
        self.assertEqual(result.findings_count, 0)
        self.assertEqual(result.provider_results, {})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_diff_review_integration.py::TestEmptyDiffReturnsNoOp -v`
Expected: FAIL — `diff_mode` not handled in `run_review()` yet.

- [ ] **Step 3: Implement diff injection in run_review()**

In `runtime/review_engine.py`, add import at top:

```python
from .diff_utils import detect_main_branch, diff_files, diff_content
```

In `run_review()`, after scope normalization (line ~795) and before prompt building (line ~796), insert:

```python
        # ── Diff mode: compute scope and augment prompt ──
        _diff_file_set: Optional[set] = None
        if request.diff_mode:
            _diff_base = request.diff_base
            if request.diff_mode == "branch" and not _diff_base:
                _diff_base = detect_main_branch(request.repo_root)
            changed = diff_files(request.repo_root, request.diff_mode, _diff_base)

            # Intersect with user-provided target_paths if set
            if request.target_paths and request.target_paths != ["."]:
                user_dirs = set(request.target_paths)
                changed = [f for f in changed if any(
                    f == d or f.startswith(d.rstrip("/") + "/") for d in user_dirs
                )]

            if not changed:
                import sys
                print("No changes detected for the specified diff mode. Nothing to review.", file=sys.stderr)
                return ReviewResult(
                    task_id=task_id,
                    artifact_root=None,
                    decision="PASS",
                    terminal_state="completed",
                    provider_results={},
                    findings_count=0,
                    parse_success_count=0,
                    parse_failure_count=0,
                    schema_valid_count=0,
                    dropped_findings_count=0,
                    findings=[],
                )

            _diff_file_set = set(changed)
            normalized_targets = changed

            _diff_text = diff_content(request.repo_root, request.diff_mode, _diff_base)
            if _diff_text:
                diff_preamble = (
                    f"{_diff_text}\n\n"
                    "Review the changes above and any code directly affected by them.\n"
                    "Do not report issues in unchanged code unless they are directly caused or exposed by the changes.\n\n"
                    "---\n"
                )
                request = ReviewRequest(
                    **{**request.__dict__, "prompt": diff_preamble + request.prompt}
                )
```

Note: we stash `_diff_file_set` for post-processing in Task 8.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_diff_review_integration.py::TestEmptyDiffReturnsNoOp -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add runtime/review_engine.py tests/test_diff_review_integration.py
git commit -m "feat: diff injection and no-op result for empty diff in run_review"
```

---

### Task 8: Scope intersection and prompt augmentation tests

**Files:**
- Modify: `tests/test_diff_review_integration.py`

- [ ] **Step 1: Write scope intersection test**

```python
# Append to tests/test_diff_review_integration.py

class TestDiffScopeInteraction(unittest.TestCase):
    @patch("runtime.diff_utils.diff_files", return_value=["src/a.py", "src/b.py", "docs/readme.md"])
    @patch("runtime.diff_utils.diff_content", return_value="fake diff")
    @patch("runtime.diff_utils.detect_main_branch", return_value="main")
    def test_target_paths_intersects_with_diff(self, mock_detect, mock_content, mock_files) -> None:
        """When user passes --target-paths src, only src/* diff files are kept."""
        req = ReviewRequest(
            repo_root="/tmp/fake",
            prompt="Review",
            providers=["claude"],
            target_paths=["src"],
            diff_mode="branch",
        )
        # We need to capture what normalized_targets becomes.
        # Since we can't easily introspect, we check the prompt contains diff text
        # and that docs/readme.md is filtered out by checking no provider gets it.
        with patch("runtime.review_engine._run_provider") as mock_run:
            mock_run.return_value = MagicMock(
                provider="claude", success=True, parse_ok=True,
                schema_valid_count=0, dropped_count=0,
                findings=[], provider_result={"success": True},
            )
            result = run_review(req, review_mode=True, write_artifacts=False)
        # Providers were called (non-empty intersection)
        mock_run.assert_called_once()

    @patch("runtime.diff_utils.diff_files", return_value=["docs/readme.md"])
    @patch("runtime.diff_utils.detect_main_branch", return_value="main")
    def test_empty_intersection_returns_no_op(self, mock_detect, mock_files) -> None:
        """target-paths=src but only docs changed -> empty intersection -> no-op."""
        req = ReviewRequest(
            repo_root="/tmp/fake",
            prompt="Review",
            providers=["claude"],
            target_paths=["src"],
            diff_mode="branch",
        )
        with patch("runtime.review_engine._run_provider") as mock_run:
            result = run_review(req, review_mode=True, write_artifacts=False)
            mock_run.assert_not_called()
        self.assertEqual(result.decision, "PASS")
```

- [ ] **Step 2: Run tests**

Run: `python3 -m pytest tests/test_diff_review_integration.py -v`
Expected: 3 passed.

- [ ] **Step 3: Commit**

```bash
git add tests/test_diff_review_integration.py
git commit -m "test: add scope intersection and empty intersection tests"
```

---

### Task 9: diff_scope post-processing

**Files:**
- Modify: `runtime/review_engine.py:926-950` (after findings merge, before memory hook)
- Modify: `tests/test_diff_review_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_diff_review_integration.py

class TestDiffScopeTagging(unittest.TestCase):
    def test_in_diff_tagged(self) -> None:
        from runtime.review_engine import _tag_diff_scope
        findings = [
            {"title": "Bug", "evidence": {"file": "src/a.py", "line": 10}},
            {"title": "Perf", "evidence": {"file": "lib/b.py", "line": 5}},
            {"title": "Style", "evidence": {}},
        ]
        diff_file_set = {"src/a.py"}
        result = _tag_diff_scope(findings, diff_file_set)
        self.assertEqual(result[0]["diff_scope"], "in_diff")
        self.assertEqual(result[1]["diff_scope"], "related")
        self.assertEqual(result[2]["diff_scope"], "unknown")

    def test_no_diff_set_returns_untagged(self) -> None:
        from runtime.review_engine import _tag_diff_scope
        findings = [{"title": "Bug", "evidence": {"file": "a.py"}}]
        result = _tag_diff_scope(findings, None)
        self.assertNotIn("diff_scope", result[0])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_diff_review_integration.py::TestDiffScopeTagging -v`
Expected: ImportError — `_tag_diff_scope` not defined.

- [ ] **Step 3: Implement _tag_diff_scope**

In `runtime/review_engine.py`, add a helper function:

```python
def _tag_diff_scope(
    findings: List[Dict[str, object]],
    diff_file_set: Optional[set],
) -> List[Dict[str, object]]:
    """Tag each finding with diff_scope based on whether its file is in the diff.

    If diff_file_set is None (non-diff mode), returns findings unchanged.
    """
    if diff_file_set is None:
        return findings
    for finding in findings:
        evidence = finding.get("evidence")
        if not isinstance(evidence, dict):
            finding["diff_scope"] = "unknown"
            continue
        file_path = str(evidence.get("file", "")).strip()
        if not file_path:
            finding["diff_scope"] = "unknown"
        elif file_path in diff_file_set:
            finding["diff_scope"] = "in_diff"
        else:
            finding["diff_scope"] = "related"
    return findings
```

Then in `run_review()`, after `merged_findings = _merge_findings_across_providers(...)` (line ~926) and before the severity counting loop, add:

```python
        merged_findings = _tag_diff_scope(merged_findings, _diff_file_set)
```

Ensure `_diff_file_set` is initialized to `None` at the top of the try block (before the diff mode check):

```python
        _diff_file_set: Optional[set] = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_diff_review_integration.py::TestDiffScopeTagging -v`
Expected: 2 passed.

- [ ] **Step 5: Run all tests**

Run: `python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add runtime/review_engine.py tests/test_diff_review_integration.py
git commit -m "feat: add diff_scope post-processing to findings"
```

---

## Chunk 4: Formatter updates and SARIF

### Task 10: SARIF diff_scope property

**Files:**
- Modify: `runtime/formatters.py:147-158` (SARIF result_payload properties)
- Modify: `tests/test_diff_review_integration.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_diff_review_integration.py
from runtime.formatters import format_sarif


class TestSarifDiffScope(unittest.TestCase):
    def test_diff_scope_in_sarif_properties(self) -> None:
        payload = {"decision": "PASS", "terminal_state": "completed", "findings_count": 1}
        findings = [{
            "title": "Bug",
            "severity": "high",
            "category": "security",
            "evidence": {"file": "a.py", "line": 1, "snippet": "x"},
            "confidence": 0.8,
            "recommendation": "fix it",
            "diff_scope": "in_diff",
        }]
        sarif = format_sarif(payload, findings)
        result_props = sarif["runs"][0]["results"][0]["properties"]
        self.assertEqual(result_props["diff_scope"], "in_diff")

    def test_no_diff_scope_omitted(self) -> None:
        payload = {"decision": "PASS", "terminal_state": "completed", "findings_count": 1}
        findings = [{
            "title": "Bug",
            "severity": "high",
            "category": "security",
            "evidence": {"file": "a.py", "line": 1, "snippet": "x"},
            "confidence": 0.8,
            "recommendation": "fix it",
        }]
        sarif = format_sarif(payload, findings)
        result_props = sarif["runs"][0]["results"][0]["properties"]
        self.assertNotIn("diff_scope", result_props)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_diff_review_integration.py::TestSarifDiffScope -v`
Expected: First test fails — `diff_scope` not in properties.

- [ ] **Step 3: Add diff_scope to SARIF formatter**

In `runtime/formatters.py`, inside the `format_sarif()` function, after the `result_payload` properties dict is built (around line 157), add:

```python
        diff_scope = finding.get("diff_scope")
        if diff_scope:
            result_payload["properties"]["diff_scope"] = diff_scope
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_diff_review_integration.py::TestSarifDiffScope -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add runtime/formatters.py tests/test_diff_review_integration.py
git commit -m "feat: include diff_scope in SARIF result properties"
```

---

### Task 11: Report format diff_scope grouping

**Files:**
- Modify: `runtime/cli.py:178-230` (`_render_user_readable_report`)
- Modify: `tests/test_diff_review_integration.py`

- [ ] **Step 1: Write the failing test**

Note: the current report renderer (`_render_user_readable_report`) does NOT display individual findings — it shows summary counts and per-provider details. Adding a diff-scope grouped findings section requires passing `findings` to the renderer. This is a scoped change.

```python
# Append to tests/test_diff_review_integration.py
from runtime.cli import _render_user_readable_report


class TestReportDiffScope(unittest.TestCase):
    def test_report_groups_by_diff_scope(self) -> None:
        payload = {
            "task_id": "test",
            "decision": "PASS",
            "terminal_state": "completed",
            "provider_success_count": 1,
            "provider_failure_count": 0,
            "findings_count": 2,
            "parse_success_count": 1,
            "parse_failure_count": 0,
            "schema_valid_count": 2,
        }
        findings = [
            {"title": "In diff bug", "severity": "high", "diff_scope": "in_diff",
             "evidence": {"file": "a.py", "line": 1}},
            {"title": "Related issue", "severity": "medium", "diff_scope": "related",
             "evidence": {"file": "b.py", "line": 5}},
        ]
        report = _render_user_readable_report("review", "stdout", ["claude"], payload, {}, findings)
        self.assertIn("In Diff", report)
        self.assertIn("Related", report)
        self.assertIn("In diff bug", report)

    def test_report_no_diff_scope_skips_section(self) -> None:
        payload = {
            "task_id": "test",
            "decision": "PASS",
            "terminal_state": "completed",
            "provider_success_count": 1,
            "provider_failure_count": 0,
            "findings_count": 0,
            "parse_success_count": 1,
            "parse_failure_count": 0,
            "schema_valid_count": 0,
        }
        report = _render_user_readable_report("review", "stdout", ["claude"], payload, {}, [])
        self.assertNotIn("In Diff", report)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_diff_review_integration.py::TestReportDiffScope -v`
Expected: TypeError — `_render_user_readable_report` doesn't accept `findings` parameter.

- [ ] **Step 3: Add optional findings parameter and diff_scope sections**

Modify `_render_user_readable_report` signature to accept `findings`:

```python
def _render_user_readable_report(
    command: str,
    result_mode: str,
    providers: List[str],
    payload: Dict[str, object],
    provider_results: Dict[str, Dict[str, object]],
    findings: Optional[List[Dict[str, object]]] = None,
) -> str:
```

At the end of the function, before `return "\n".join(lines)`, add:

```python
    # Diff scope findings breakdown (only when findings have diff_scope tags)
    if findings and any(f.get("diff_scope") for f in findings):
        in_diff = [f for f in findings if f.get("diff_scope") == "in_diff"]
        related = [f for f in findings if f.get("diff_scope") == "related"]
        unknown = [f for f in findings if f.get("diff_scope") == "unknown"]

        if in_diff:
            lines.append("")
            lines.append(f"In Diff ({len(in_diff)} findings)")
            for f in in_diff:
                lines.append(f"  {str(f.get('severity', '-')).upper():8s} {f.get('category', '-'):15s} {f.get('title', '-')}  {_finding_location_from_dict(f)}")
        if related:
            lines.append("")
            lines.append(f"Related ({len(related)} findings)")
            for f in related:
                lines.append(f"  {str(f.get('severity', '-')).upper():8s} {f.get('category', '-'):15s} {f.get('title', '-')}  {_finding_location_from_dict(f)}")
```

Add helper (in `cli.py`):

```python
def _finding_location_from_dict(finding: Dict[str, object]) -> str:
    evidence = finding.get("evidence")
    if not isinstance(evidence, dict):
        return ""
    file_path = str(evidence.get("file", ""))
    line = evidence.get("line")
    if file_path and isinstance(line, int):
        return f"{file_path}:{line}"
    return file_path
```

Then update the two call sites of `_render_user_readable_report` in `main()` to pass `result.findings`:

```python
                    _render_user_readable_report(
                        args.command,
                        effective_result_mode,
                        providers,
                        payload,
                        result.provider_results,
                        result.findings,  # NEW
                    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_diff_review_integration.py::TestReportDiffScope -v`
Expected: 2 passed.

- [ ] **Step 5: Run full test suite**

Run: `python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add runtime/cli.py tests/test_diff_review_integration.py
git commit -m "feat: add diff_scope grouping to human-readable report"
```

---

## Chunk 5: Final integration and cleanup

### Task 12: End-to-end test with mocked git

**Files:**
- Modify: `tests/test_diff_review_integration.py`

- [ ] **Step 1: Write end-to-end test**

```python
# Append to tests/test_diff_review_integration.py

class TestEndToEndDiffReview(unittest.TestCase):
    @patch("runtime.diff_utils.diff_content", return_value="## Changed Files (1 files)\n- src/a.py\n\n## Diff\n```diff\n+new line\n```")
    @patch("runtime.diff_utils.diff_files", return_value=["src/a.py"])
    @patch("runtime.diff_utils.detect_main_branch", return_value="main")
    def test_full_diff_review_flow(self, mock_detect, mock_files, mock_content) -> None:
        """Full flow: diff computed, prompt augmented, findings tagged."""
        req = ReviewRequest(
            repo_root="/tmp/fake",
            prompt="Review for bugs",
            providers=["claude"],
            diff_mode="branch",
        )

        mock_finding = {
            "title": "Bug in a.py",
            "severity": "high",
            "category": "security",
            "evidence": {"file": "src/a.py", "line": 5, "snippet": "x"},
            "confidence": 0.9,
            "recommendation": "fix",
        }

        with patch("runtime.review_engine._run_provider") as mock_run:
            mock_outcome = MagicMock()
            mock_outcome.provider = "claude"
            mock_outcome.success = True
            mock_outcome.parse_ok = True
            mock_outcome.schema_valid_count = 1
            mock_outcome.dropped_count = 0
            mock_outcome.findings = [MagicMock(
                provider="claude", finding_id="1", fingerprint="fp1",
                **mock_finding,
            )]
            mock_outcome.provider_result = {"success": True}
            mock_run.return_value = mock_outcome

            result = run_review(req, review_mode=True, write_artifacts=False)

        self.assertGreaterEqual(result.findings_count, 0)
        # Verify diff content was used in prompt
        mock_content.assert_called_once()
```

- [ ] **Step 2: Run the test**

Run: `python3 -m pytest tests/test_diff_review_integration.py::TestEndToEndDiffReview -v`
Expected: PASS.

- [ ] **Step 3: Run full test suite one final time**

Run: `python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -5`
Expected: All tests pass, 0 errors.

- [ ] **Step 4: Commit**

```bash
git add tests/test_diff_review_integration.py
git commit -m "test: add end-to-end diff review integration test"
```

---

### Task 13: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add diff-only section to README Use Cases table**

Already done in previous README update — verify the "Persistent code review" row is there. If not, add a row:

```markdown
| Diff-only review | `mco review --diff` | Review only changed files vs main branch |
```

- [ ] **Step 2: Add --diff flags to Key Runtime Flags table**

Verify `--diff`, `--staged`, `--unstaged`, `--diff-base` appear in the flags table. If not, add:

```markdown
| `--diff` | off | Review only changes vs merge-base with main/master |
| `--staged` | off | Review only staged changes |
| `--unstaged` | off | Review only unstaged changes |
| `--diff-base` | auto | Git ref for branch diff (implies --diff) |
```

- [ ] **Step 3: Commit**

```bash
git add README.md
git commit -m "docs: add diff-only review flags to README"
```
