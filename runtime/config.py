from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

DEFAULT_PROVIDER_TIMEOUTS: Dict[str, int] = {
}


@dataclass(frozen=True)
class ReviewPolicy:
    timeout_seconds: int = 180
    stall_timeout_seconds: int = 900
    poll_interval_seconds: float = 1.0
    review_hard_timeout_seconds: int = 1800
    enforce_findings_contract: bool = False
    max_retries: int = 1
    high_escalation_threshold: int = 1
    require_non_empty_findings: bool = True
    max_provider_parallelism: int = 0
    provider_timeouts: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_PROVIDER_TIMEOUTS))
    allow_paths: List[str] = field(default_factory=lambda: ["."])
    provider_permissions: Dict[str, Dict[str, str]] = field(default_factory=dict)
    enforcement_mode: str = "strict"


@dataclass(frozen=True)
class ReviewConfig:
    providers: List[str] = field(default_factory=lambda: ["claude", "codex", "gemini", "opencode", "qwen"])
    artifact_base: str = "reports/review"
    policy: ReviewPolicy = field(default_factory=ReviewPolicy)


_DEFAULT_GLOBAL_CONFIG_DIR = os.path.join(os.path.expanduser("~"), ".mco")


def load_config_files(
    repo_root: str,
    global_config_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Load and merge config from global (~/.mco/config.json) and project (.mcorc.json).

    Merge order: global < project. Returns empty dict if no config files found.
    """
    global_dir = global_config_dir or _DEFAULT_GLOBAL_CONFIG_DIR
    merged: Dict[str, Any] = {}

    # Global config
    global_path = os.path.join(global_dir, "config.json")
    if os.path.isfile(global_path):
        try:
            with open(global_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                merged.update(data)
        except (json.JSONDecodeError, OSError):
            pass

    # Project config
    project_path = os.path.join(repo_root, ".mcorc.json")
    if os.path.isfile(project_path):
        try:
            with open(project_path, encoding="utf-8") as f:
                data = json.load(f)
            if isinstance(data, dict):
                merged.update(data)
        except (json.JSONDecodeError, OSError):
            pass

    return merged
