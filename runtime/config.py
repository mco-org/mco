from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List

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
    providers: List[str] = field(default_factory=lambda: ["claude", "codex"])
    artifact_base: str = "reports/review"
    policy: ReviewPolicy = field(default_factory=ReviewPolicy)
