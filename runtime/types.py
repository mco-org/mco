from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ErrorKind(str, Enum):
    RETRYABLE_TIMEOUT = "retryable_timeout"
    RETRYABLE_RATE_LIMIT = "retryable_rate_limit"
    RETRYABLE_TRANSIENT_NETWORK = "retryable_transient_network"
    NON_RETRYABLE_AUTH = "non_retryable_auth"
    NON_RETRYABLE_INVALID_INPUT = "non_retryable_invalid_input"
    NON_RETRYABLE_UNSUPPORTED_CAPABILITY = "non_retryable_unsupported_capability"
    NORMALIZATION_ERROR = "normalization_error"


class WarningKind(str, Enum):
    PROVIDER_WARNING_MCP_STARTUP = "provider_warning_mcp_startup"


RUN_RESULT_SCHEMA_VERSION = "stage-a-v2"
RUN_RESULT_FIELDS = (
    "task_id",
    "provider",
    "success",
    "attempts",
    "delays_seconds",
    "output",
    "final_error",
    "warnings",
)


class TaskState(str, Enum):
    DRAFT = "DRAFT"
    QUEUED = "QUEUED"
    DISPATCHED = "DISPATCHED"
    RUNNING = "RUNNING"
    RETRYING = "RETRYING"
    AGGREGATING = "AGGREGATING"
    COMPLETED = "COMPLETED"
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    EXPIRED = "EXPIRED"


@dataclass
class AttemptResult:
    success: bool
    output: Optional[Dict[str, Any]] = None
    error_kind: Optional[ErrorKind] = None
    stderr: str = ""
    warnings: List[WarningKind] = field(default_factory=list)


@dataclass
class RunResult:
    task_id: str
    provider: str
    success: bool
    attempts: int
    delays_seconds: List[float]
    output: Optional[Dict[str, Any]]
    final_error: Optional[ErrorKind]
    warnings: List[WarningKind]
