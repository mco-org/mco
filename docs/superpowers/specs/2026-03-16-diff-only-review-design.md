# Diff-Only Review — Design Spec

## Overview

Add `--diff`, `--staged`, `--unstaged` flags to `mco review` / `mco run` so that agents only review changed code instead of the entire repository.

## CLI Flags

### Mutual exclusion

`--diff`, `--staged`, `--unstaged` form a mutually exclusive group.

| Flag | Meaning |
|------|---------|
| `--diff` | Review changes on current branch vs merge-base with main/master |
| `--staged` | Review `git diff --cached` only |
| `--unstaged` | Review `git diff` (working tree) only |

### `--diff-base <ref>`

Modifier for branch diff mode. Passing `--diff-base` implicitly enables `--diff`.

```bash
mco review --diff                    # auto-detect merge-base with main/master
mco review --diff-base origin/main   # explicit base ref
mco review --diff-base HEAD~3        # last 3 commits
mco review --diff-base abc1234       # specific commit
```

If `--diff-base` is passed without `--diff`, `--diff` is inferred.

## Diff Computation — `runtime/diff_utils.py`

New module with the following functions:

```python
def detect_main_branch(repo_root: str) -> str:
    """Return 'main' or 'master', whichever exists. Fallback: 'main'."""

def merge_base(repo_root: str, ref: str) -> str:
    """Return `git merge-base HEAD <ref>`."""

def diff_files(repo_root: str, mode: str, base: Optional[str] = None) -> List[str]:
    """Return list of changed file paths (relative to repo root).

    mode: 'branch' | 'staged' | 'unstaged'
    base: required for 'branch' mode; ignored for staged/unstaged.
    """

def diff_content(repo_root: str, mode: str, base: Optional[str] = None,
                 max_total_bytes: int = 60_000) -> str:
    """Return unified diff text with per-file fair truncation.

    Truncation strategy:
    1. Compute full diff.
    2. If total bytes <= max_total_bytes, return as-is.
    3. Otherwise, allocate budget = max_total_bytes / num_files per file.
    4. For each file, keep the file header + as many complete hunks as fit
       within the per-file budget.
    5. If a file is truncated, append '... (diff truncated, N more hunks)'.
    6. Changed file list is ALWAYS included in full at the top,
       regardless of truncation.

    Returns:
        Formatted string with file list header + truncated unified diff.
    """
```

### Truncation strategy (detail)

The goal is **fair representation across all changed files**, not just the first N bytes.

1. Full changed file list is always preserved at the top.
2. Per-file budget = `max_total_bytes / len(files)`.
3. Within each file, keep complete hunks until budget exhausted.
4. Truncated files get an explicit `... (diff truncated, N more hunks)` marker.
5. Default `max_total_bytes = 60_000` (~15k tokens). Configurable but not exposed as CLI flag in v1.

## Scope Interaction with `--target-paths`

Priority rules:

| `--target-paths` | diff mode | Effective file scope |
|-------------------|-----------|---------------------|
| not set | on | diff files |
| set | on | intersection of target-paths and diff files |
| set | off | target-paths (existing behavior) |
| not set | off | "." (existing behavior) |

Implementation: after computing diff files, if user also passed `--target-paths`, filter diff files to only those under the target paths. If the intersection is empty, exit with a message: `"No changed files found within the specified target paths."` (exit code 0, not an error).

## Empty Diff Behavior

If diff computation returns zero changed files:

- Print to stderr: `"No changes detected for the specified diff mode. Nothing to review."`
- Exit with code 0 (success, not error).
- Do NOT invoke any providers.

## Prompt Augmentation

When diff mode is active, the prompt is augmented BEFORE the existing scope annotation:

```
## Changed Files ({N} files)
- path/to/file1.py
- path/to/file2.ts
- ...

## Diff
```diff
<unified diff content, possibly truncated>
```

Review the changes above and any code directly affected by them.
Do not report issues in unchanged code unless they are directly caused or exposed by the changes.

---
{original_user_prompt}

Scope: {effective_target_paths}
```

The original prompt and scope annotation remain intact below the diff section.

## IN_DIFF / RELATED Classification

**Not done by the model. Done as local post-processing.**

After provider results are collected and findings are parsed:

1. Build `diff_file_set: Set[str]` from the diff files list.
2. For each finding with `evidence.file_path`:
   - If `file_path` is in `diff_file_set` → tag `"diff_scope": "in_diff"`
   - Otherwise → tag `"diff_scope": "related"`
3. Findings without `file_path` in evidence → tag `"diff_scope": "unknown"`

This tag is added to the finding dict at the top level, NOT inside the title or description. It does not affect deduplication or memory hashing.

### v1 scope: file-level only

Line-level hunk matching (is the finding's line number within a changed hunk?) is deferred to v2. File-level is a sufficient and reliable approximation for v1.

## ReviewRequest Changes

```python
@dataclass
class ReviewRequest:
    # ... existing fields ...
    diff_mode: Optional[str] = None    # "branch" | "staged" | "unstaged" | None
    diff_base: Optional[str] = None    # git ref, only used when diff_mode="branch"
```

## Integration Point in `run_review()`

```
existing: normalize scopes (line ~791)
     ↓
NEW: if diff_mode is set:
       1. compute diff_files and diff_content
       2. intersect with target_paths if user provided them
       3. if empty → print message, return early
       4. override normalized_targets with diff file list
       5. prepend diff section to full_prompt
     ↓
existing: build prompt (line ~796)
     ↓
existing: memory pre_run hook (line ~804)
     ↓
existing: provider dispatch
     ↓
existing: merge findings
     ↓
NEW: post-process findings with diff_scope tags
     ↓
existing: memory post_run hook
```

## Output Changes

### JSON output

Findings gain a new optional field:

```json
{
  "title": "SQL injection in query builder",
  "severity": "high",
  "diff_scope": "in_diff",
  ...
}
```

### Report format

When `--format report` (default), findings are grouped:

```
## In Diff (3 findings)
...

## Related (1 finding)
...
```

### SARIF / markdown-pr

`diff_scope` is included as a property but does not change the output structure.

## What Is NOT in Scope (v1)

- Memory layer filtering (pre_run only injecting diff-related findings) → v2
- Line-level IN_DIFF classification → v2
- `--diff-base` auto-detection from PR context (e.g., GitHub PR base branch) → v2
- New CLI flag for diff truncation budget → not planned

## Files to Create/Modify

| File | Action |
|------|--------|
| `runtime/diff_utils.py` | Create — diff computation and truncation |
| `runtime/cli.py` | Modify — add mutual-exclusion flag group |
| `runtime/review_engine.py` | Modify — diff injection + post-processing |
| `tests/test_diff_utils.py` | Create — unit tests for diff module |
| `tests/test_diff_review_integration.py` | Create — integration tests |
