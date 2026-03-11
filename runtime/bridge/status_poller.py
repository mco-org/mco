"""Poll evermemos request_status() until writes become searchable.

After writing critical/high severity findings, the bridge calls this to
confirm that the memos are indexed and will be visible to the next run's
search queries.  Lifecycle states considered "done": searchable, provisional.
"""
from __future__ import annotations

import sys
import time
from typing import Any, List, Set

_DONE_STATES = frozenset({"searchable", "provisional"})


def poll_until_searchable(
    client: Any,
    request_ids: List[str],
    timeout_s: float = 30,
    interval_s: float = 3,
) -> Set[str]:
    """Poll request_status() for each id until all are searchable or timeout.

    Args:
        client: Object exposing ``request_status(request_id) -> dict``.
        request_ids: Identifiers returned by a prior write/upsert call.
        timeout_s: Maximum wall-clock seconds to spend polling.
        interval_s: Seconds to sleep between polling iterations.

    Returns:
        Set of request_ids that were still pending when the deadline expired.
        An empty set means every write has been confirmed searchable.
    """
    if not request_ids:
        return set()

    pending: Set[str] = set(request_ids)
    deadline = time.monotonic() + timeout_s

    while pending and time.monotonic() < deadline:
        for rid in list(pending):
            try:
                result = client.request_status(rid)
            except Exception:
                # Transient failure — retry on the next iteration.
                continue

            lifecycle = result.get("lifecycle", "")
            if lifecycle in _DONE_STATES:
                pending.discard(rid)

        if pending:
            time.sleep(interval_s)

    if pending:
        print(
            f"[mco-bridge] warning: {len(pending)} write(s) still not searchable "
            f"after {timeout_s}s: {sorted(pending)}",
            file=sys.stderr,
        )

    return pending
