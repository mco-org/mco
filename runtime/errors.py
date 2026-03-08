from __future__ import annotations

import re
from typing import List

from .types import ErrorKind, WarningKind


def detect_warnings(stderr: str) -> List[WarningKind]:
    text = stderr.lower()
    warnings: List[WarningKind] = []
    if "mcp" in text and ("failed to start" in text or "auth required" in text):
        warnings.append(WarningKind.PROVIDER_WARNING_MCP_STARTUP)
    return warnings


def classify_error(exit_code: int, stderr: str) -> ErrorKind:
    text = stderr.lower()

    # Timeout: specific exit codes or explicit timeout phrases
    if exit_code in (124, 142) or re.search(r"\btimed?\s*out\b", text):
        return ErrorKind.RETRYABLE_TIMEOUT

    # Rate limiting: HTTP 429 as word boundary or explicit phrase
    if "rate limit" in text or re.search(r"\b429\b", text):
        return ErrorKind.RETRYABLE_RATE_LIMIT

    if any(token in text for token in ("connection reset", "temporary failure", "econnreset", "ehostunreach")):
        return ErrorKind.RETRYABLE_TRANSIENT_NETWORK
    # "network" alone is too broad; require "network error" or "network failure"
    if re.search(r"\bnetwork\s+(error|failure|unreachable)\b", text):
        return ErrorKind.RETRYABLE_TRANSIENT_NETWORK

    # Auth: HTTP 401 as word boundary, explicit auth phrases
    if re.search(r"\b401\b", text) or any(
        token in text for token in ("invalid api key", "unauthorized", "not logged in", "auth failed", "oauth")
    ):
        return ErrorKind.NON_RETRYABLE_AUTH

    if any(token in text for token in ("unsupported capability", "not supported", "unknown arguments")):
        return ErrorKind.NON_RETRYABLE_UNSUPPORTED_CAPABILITY

    if any(token in text for token in ("invalid input", "missing required", "validation failed", "invalid type")):
        return ErrorKind.NON_RETRYABLE_INVALID_INPUT

    # A parsing failure after command success is also represented as normalization error.
    if re.search(r"(parse|deserialize|json).*fail", text) or "normalization" in text:
        return ErrorKind.NORMALIZATION_ERROR

    return ErrorKind.NORMALIZATION_ERROR

