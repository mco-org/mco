"""Git diff operations for diff-only review mode."""
from __future__ import annotations

import subprocess
from typing import List, Optional, Tuple


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

    file_sections = _split_diff_by_file(raw)
    if not file_sections:
        return ""

    # File list header (always complete)
    file_names = [s[0] for s in file_sections]
    header = "## Changed Files ({} files)\n{}".format(
        len(file_names),
        "\n".join(f"- {f}" for f in file_names),
    )

    total_raw = sum(len(s[1]) for s in file_sections)
    if total_raw <= max_total_bytes:
        diff_body = "\n".join(s[1] for s in file_sections)
        return f"{header}\n\n## Diff\n```diff\n{diff_body}\n```"

    # Fair truncation: equal budget per file
    budget_per_file = max(200, max_total_bytes // len(file_sections))
    truncated_parts: List[str] = []
    for _file_name, file_diff in file_sections:
        if len(file_diff) <= budget_per_file:
            truncated_parts.append(file_diff)
        else:
            truncated_parts.append(_truncate_file_diff(file_diff, budget_per_file))
    diff_body = "\n".join(truncated_parts)
    return f"{header}\n\n## Diff\n```diff\n{diff_body}\n```"


def _split_diff_by_file(raw_diff: str) -> List[Tuple[str, str]]:
    """Split a unified diff into (filename, diff_text) pairs."""
    sections: List[Tuple[str, str]] = []
    current_name = ""
    current_lines: List[str] = []

    for line in raw_diff.splitlines(keepends=True):
        if line.startswith("diff --git "):
            if current_name and current_lines:
                sections.append((current_name, "".join(current_lines)))
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
    total_hunks = sum(1 for l in lines if l.startswith("@@"))
    hunks_kept = 0

    in_header = True
    for line in lines:
        is_hunk_start = line.startswith("@@")
        if is_hunk_start:
            in_header = False

        if current_size + len(line) > budget and not in_header:
            remaining = total_hunks - hunks_kept
            if remaining > 0:
                kept.append(f"... (diff truncated, {remaining} more hunks)\n")
            else:
                kept.append("... (diff truncated)\n")
            break

        if is_hunk_start:
            hunks_kept += 1
        kept.append(line)
        current_size += len(line)

    return "".join(kept)
