from __future__ import annotations

import unittest
from unittest.mock import MagicMock, call

from runtime.bridge.forget_cleaner import clean_rejected_findings


class TestCleanRejectedFindings(unittest.TestCase):

    def test_rejected_findings_are_forgotten(self):
        """2 rejected + 1 open -> 2 forget calls."""
        client = MagicMock()
        findings = [
            {"status": "rejected", "memory_id": "mem-1"},
            {"status": "open", "memory_id": "mem-2"},
            {"status": "rejected", "memory_id": "mem-3"},
        ]

        result = clean_rejected_findings(client, findings, space="coding:test--findings")

        self.assertEqual(result["forgotten_count"], 2)
        self.assertEqual(result["skipped_no_id"], 0)
        client.forget.assert_has_calls(
            [
                call(memory_ids=["mem-1"], space="coding:test--findings"),
                call(memory_ids=["mem-3"], space="coding:test--findings"),
            ],
            any_order=False,
        )
        self.assertEqual(client.forget.call_count, 2)

    def test_no_rejected_is_noop(self):
        """No rejected findings -> no forget calls."""
        client = MagicMock()
        findings = [
            {"status": "open", "memory_id": "mem-1"},
            {"status": "accepted", "memory_id": "mem-2"},
            {"status": "wontfix", "memory_id": "mem-3"},
        ]

        result = clean_rejected_findings(client, findings, space="coding:test--findings")

        self.assertEqual(result["forgotten_count"], 0)
        self.assertEqual(result["skipped_no_id"], 0)
        client.forget.assert_not_called()

    def test_findings_without_memory_id_skipped(self):
        """Rejected without memory_id counted as skipped."""
        client = MagicMock()
        findings = [
            {"status": "rejected", "memory_id": "mem-1"},
            {"status": "rejected"},  # no memory_id
            {"status": "rejected", "memory_id": None},  # explicit None
        ]

        result = clean_rejected_findings(client, findings, space="coding:test--findings")

        self.assertEqual(result["forgotten_count"], 1)
        self.assertEqual(result["skipped_no_id"], 2)
        client.forget.assert_called_once_with(memory_ids=["mem-1"], space="coding:test--findings")

    def test_wontfix_not_forgotten(self):
        """wontfix findings are preserved (accepted risks, not forgotten)."""
        client = MagicMock()
        findings = [
            {"status": "wontfix", "memory_id": "mem-1"},
            {"status": "wontfix", "memory_id": "mem-2"},
        ]

        result = clean_rejected_findings(client, findings, space="coding:test--findings")

        self.assertEqual(result["forgotten_count"], 0)
        self.assertEqual(result["skipped_no_id"], 0)
        client.forget.assert_not_called()

    def test_forget_exception_is_caught_and_counted(self):
        """If forget() raises, the error is caught, logged, and we continue."""
        client = MagicMock()
        client.forget.side_effect = [RuntimeError("network error"), None]
        findings = [
            {"status": "rejected", "memory_id": "mem-1"},
            {"status": "rejected", "memory_id": "mem-2"},
        ]

        result = clean_rejected_findings(client, findings, space="coding:test--findings")

        # First call failed, second succeeded
        self.assertEqual(result["forgotten_count"], 1)
        self.assertEqual(client.forget.call_count, 2)


if __name__ == "__main__":
    unittest.main()
