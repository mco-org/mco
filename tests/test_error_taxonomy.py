from __future__ import annotations

import unittest

from runtime.errors import classify_error, detect_warnings
from runtime.types import ErrorKind, WarningKind


class ErrorTaxonomyTests(unittest.TestCase):
    def test_retryable_timeout(self) -> None:
        self.assertEqual(classify_error(124, "timed out"), ErrorKind.RETRYABLE_TIMEOUT)

    def test_retryable_rate_limit(self) -> None:
        self.assertEqual(classify_error(1, "Rate limit exceeded (429)"), ErrorKind.RETRYABLE_RATE_LIMIT)

    def test_retryable_transient_network(self) -> None:
        self.assertEqual(classify_error(1, "connection reset by peer"), ErrorKind.RETRYABLE_TRANSIENT_NETWORK)

    def test_non_retryable_auth(self) -> None:
        self.assertEqual(classify_error(1, "invalid api key 401"), ErrorKind.NON_RETRYABLE_AUTH)

    def test_non_retryable_invalid_input(self) -> None:
        self.assertEqual(classify_error(1, "schema validation failed"), ErrorKind.NON_RETRYABLE_INVALID_INPUT)

    def test_non_retryable_unsupported_capability(self) -> None:
        self.assertEqual(classify_error(1, "unknown arguments: --output-format"), ErrorKind.NON_RETRYABLE_UNSUPPORTED_CAPABILITY)

    def test_normalization_error_fallback(self) -> None:
        self.assertEqual(classify_error(1, "unexpected malformed output"), ErrorKind.PROVIDER_FAILURE)

    def test_mcp_warning_detection(self) -> None:
        warnings = detect_warnings("MCP client failed to start: Auth required")
        self.assertIn(WarningKind.PROVIDER_WARNING_MCP_STARTUP, warnings)


if __name__ == "__main__":
    unittest.main()
