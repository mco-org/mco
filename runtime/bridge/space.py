"""Space slug inference from git remote or directory name."""
from __future__ import annotations

import re
from pathlib import Path
from typing import Optional


def infer_space_slug(repo_root: str, explicit: Optional[str] = None) -> str:
    """Infer evermemos space slug from repo.

    Priority: explicit override > git remote > directory basename.
    Returns a slug safe for evermemos space_id (no colons, no spaces).
    """
    if explicit:
        return explicit

    git_config = Path(repo_root) / ".git" / "config"
    if git_config.exists():
        try:
            text = git_config.read_text(encoding="utf-8")
            match = re.search(r'url\s*=\s*.*[:/]([^/]+)/([^/\s]+?)(?:\.git)?\s*$', text, re.MULTILINE)
            if match:
                org, repo = match.group(1), match.group(2)
                return f"{org}--{repo}"
        except OSError:
            pass

    return Path(repo_root).resolve().name
