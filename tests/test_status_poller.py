from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from runtime.bridge.status_poller import poll_until_searchable


class TestStatusPoller(unittest.TestCase):
    """Tests for poll_until_searchable write-confirmation polling."""

    def test_all_searchable_immediately(self):
        """All request_ids return 'searchable' on first poll -> empty pending set."""
        client = MagicMock()
        client.request_status.side_effect = lambda rid: {"lifecycle": "searchable"}

        result = poll_until_searchable(
            client,
            request_ids=["r1", "r2", "r3"],
            timeout_s=0.05,
            interval_s=0.01,
        )
        self.assertEqual(result, set())
        self.assertTrue(client.request_status.called)

    def test_timeout_returns_pending(self):
        """Always 'queued' with short timeout -> returns full pending set."""
        client = MagicMock()
        client.request_status.return_value = {"lifecycle": "queued"}

        result = poll_until_searchable(
            client,
            request_ids=["r1", "r2"],
            timeout_s=0.05,
            interval_s=0.01,
        )
        self.assertEqual(result, {"r1", "r2"})

    def test_provisional_counts_as_done(self):
        """'provisional' lifecycle is treated as searchable."""
        client = MagicMock()
        client.request_status.return_value = {"lifecycle": "provisional"}

        result = poll_until_searchable(
            client,
            request_ids=["r1"],
            timeout_s=0.05,
            interval_s=0.01,
        )
        self.assertEqual(result, set())

    def test_empty_request_ids_is_noop(self):
        """Empty request_ids list -> no calls made, empty result."""
        client = MagicMock()

        result = poll_until_searchable(
            client,
            request_ids=[],
            timeout_s=0.05,
            interval_s=0.01,
        )
        self.assertEqual(result, set())
        client.request_status.assert_not_called()

    def test_exception_retried_next_iteration(self):
        """Exceptions from request_status are caught; polling retries on next iteration."""
        call_count = 0

        def side_effect(rid):
            nonlocal call_count
            call_count += 1
            if call_count <= 1:
                raise ConnectionError("transient failure")
            return {"lifecycle": "searchable"}

        client = MagicMock()
        client.request_status.side_effect = side_effect

        result = poll_until_searchable(
            client,
            request_ids=["r1"],
            timeout_s=0.5,
            interval_s=0.01,
        )
        self.assertEqual(result, set())
        self.assertGreaterEqual(client.request_status.call_count, 2)


if __name__ == "__main__":
    unittest.main()
