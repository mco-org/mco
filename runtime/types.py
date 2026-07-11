from __future__ import annotations

from enum import Enum


class ErrorKind(str, Enum):
    RETRYABLE_TIMEOUT = "retryable_timeout"
    RETRYABLE_RATE_LIMIT = "retryable_rate_limit"
    RETRYABLE_TRANSIENT_NETWORK = "retryable_transient_network"
    NON_RETRYABLE_AUTH = "non_retryable_auth"
    NON_RETRYABLE_INVALID_INPUT = "non_retryable_invalid_input"
    NON_RETRYABLE_UNSUPPORTED_CAPABILITY = "non_retryable_unsupported_capability"
    PROVIDER_FAILURE = "provider_failure"


class WarningKind(str, Enum):
    PROVIDER_WARNING_MCP_STARTUP = "provider_warning_mcp_startup"
