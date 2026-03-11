"""Tests for the 5 correctness fixes to the memory bridge state model.

Fix 1: Canonical latest view (deduplicate findings/scores by key)
Fix 2: run_count from run markers (not entry count)
Fix 3: Category-aware _load_agent_rates
Fix 4: memory_id injection from fetch_history outer item
Fix 5: Per-finding changed_files (not union across all commits)
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from runtime.bridge.evermemos_client import EverMemosClient
from runtime.bridge.core import (
    _dedupe_findings_latest,
    _dedupe_scores_latest,
    _parse_history_findings,
    _count_run_markers,
    _load_agent_rates,
    MCO_RUN_MARKER_PREFIX,
)
from runtime.bridge.passive_confirm import check_passive_fixes


class TestDedupeFindings(unittest.TestCase):
    """Fix 1: Only the latest version of each finding_hash is kept."""

    def test_keeps_latest_by_hash(self):
        findings = [
            {"finding_hash": "sha256:aaa", "status": "open", "occurrence_count": 1},
            {"finding_hash": "sha256:bbb", "status": "open", "occurrence_count": 1},
            {"finding_hash": "sha256:aaa", "status": "open", "occurrence_count": 2},
        ]
        result = _dedupe_findings_latest(findings)
        self.assertEqual(len(result), 2)
        by_hash = {f["finding_hash"]: f for f in result}
        self.assertEqual(by_hash["sha256:aaa"]["occurrence_count"], 2)

    def test_latest_status_wins(self):
        """If same hash appears with open then fixed, fixed wins."""
        findings = [
            {"finding_hash": "sha256:aaa", "status": "open"},
            {"finding_hash": "sha256:aaa", "status": "fixed"},
        ]
        result = _dedupe_findings_latest(findings)
        self.assertEqual(len(result), 1)
        self.assertEqual(result[0]["status"], "fixed")

    def test_empty_list(self):
        self.assertEqual(_dedupe_findings_latest([]), [])


class TestDedupeScores(unittest.TestCase):
    """Fix 1: Only the latest version of each (agent, task_category) score is kept."""

    def test_keeps_latest_per_agent_category(self):
        scores = [
            {"agent": "claude", "task_category": "security", "cross_validated_rate": 0.5},
            {"agent": "claude", "task_category": "security", "cross_validated_rate": 0.8},
            {"agent": "gemini", "task_category": "security", "cross_validated_rate": 0.6},
        ]
        result = _dedupe_scores_latest(scores)
        self.assertEqual(len(result), 2)
        by_agent = {s["agent"]: s for s in result}
        self.assertAlmostEqual(by_agent["claude"]["cross_validated_rate"], 0.8)


class TestRunCountMarkers(unittest.TestCase):
    """Fix 2: run_count counts [MCO-RUN-MARKER] entries, not finding entries."""

    def test_counts_markers_only(self):
        history = [
            {"content": f'{MCO_RUN_MARKER_PREFIX}{{"run": 1}}'},
            {"content": "some other text"},
            {"content": f'{MCO_RUN_MARKER_PREFIX}{{"run": 2}}'},
            {"content": EverMemosClient.serialize_finding({"finding_hash": "sha256:aaa"})},
        ]
        self.assertEqual(_count_run_markers(history), 2)

    def test_empty_history(self):
        self.assertEqual(_count_run_markers([]), 0)

    def test_no_markers(self):
        history = [
            {"content": "random text"},
            {"content": EverMemosClient.serialize_finding({"finding_hash": "sha256:aaa"})},
        ]
        self.assertEqual(_count_run_markers(history), 0)


class TestCategoryAwareAgentRates(unittest.TestCase):
    """Fix 3: _load_agent_rates can filter by task_category or average."""

    def _make_client(self, scores):
        client = MagicMock()
        history = []
        for s in scores:
            history.append({"content": EverMemosClient.serialize_agent_score(s)})
        client.fetch_history.return_value = history
        return client

    def test_filter_by_category(self):
        client = self._make_client([
            {"agent": "claude", "task_category": "security", "cross_validated_rate": 0.9},
            {"agent": "claude", "task_category": "style", "cross_validated_rate": 0.3},
            {"agent": "gemini", "task_category": "security", "cross_validated_rate": 0.7},
        ])
        rates = _load_agent_rates(client, "coding:test--agents", category="security")
        self.assertAlmostEqual(rates["claude"], 0.9)
        self.assertAlmostEqual(rates["gemini"], 0.7)
        self.assertNotIn("style", str(rates))

    def test_average_without_category(self):
        client = self._make_client([
            {"agent": "claude", "task_category": "security", "cross_validated_rate": 0.9},
            {"agent": "claude", "task_category": "style", "cross_validated_rate": 0.3},
        ])
        rates = _load_agent_rates(client, "coding:test--agents", category=None)
        # Average of 0.9 and 0.3 = 0.6
        self.assertAlmostEqual(rates["claude"], 0.6)

    def test_category_not_found_returns_empty(self):
        client = self._make_client([
            {"agent": "claude", "task_category": "security", "cross_validated_rate": 0.9},
        ])
        rates = _load_agent_rates(client, "coding:test--agents", category="performance")
        self.assertEqual(rates, {})


class TestMemoryIdInjection(unittest.TestCase):
    """Fix 4: memory_id is extracted from fetch_history outer item."""

    def test_id_from_outer_item(self):
        content = EverMemosClient.serialize_finding({
            "finding_hash": "sha256:aaa", "status": "open", "title": "Bug",
        })
        items = [{"id": "mem-123", "content": content}]
        findings = _parse_history_findings(items)
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["memory_id"], "mem-123")

    def test_memory_id_from_outer_item(self):
        content = EverMemosClient.serialize_finding({
            "finding_hash": "sha256:aaa", "status": "open", "title": "Bug",
        })
        items = [{"memory_id": "mem-456", "content": content}]
        findings = _parse_history_findings(items)
        self.assertEqual(findings[0]["memory_id"], "mem-456")

    def test_no_id_preserves_content_memory_id(self):
        """If outer item has no id, keep memory_id from content if present."""
        content = EverMemosClient.serialize_finding({
            "finding_hash": "sha256:aaa", "status": "rejected",
            "title": "Bug", "memory_id": "mem-from-content",
        })
        items = [{"content": content}]
        findings = _parse_history_findings(items)
        self.assertEqual(findings[0]["memory_id"], "mem-from-content")

    def test_outer_id_overrides_content_memory_id(self):
        """Outer item id takes precedence over content memory_id."""
        content = EverMemosClient.serialize_finding({
            "finding_hash": "sha256:aaa", "status": "open",
            "title": "Bug", "memory_id": "old-id",
        })
        items = [{"id": "real-id", "content": content}]
        findings = _parse_history_findings(items)
        self.assertEqual(findings[0]["memory_id"], "real-id")


class TestPerFindingChangedFiles(unittest.TestCase):
    """Fix 5: Each finding checks changed_files only for its own last_seen_commit."""

    def test_per_commit_isolation(self):
        """Finding A (commit X) shouldn't see changes from commit Y."""
        findings = [
            {"finding_hash": "sha256:aaa", "status": "open", "file": "a.py",
             "last_seen_commit": "commit_X", "passive_fix_candidate": False},
            {"finding_hash": "sha256:bbb", "status": "open", "file": "b.py",
             "last_seen_commit": "commit_Y", "passive_fix_candidate": False},
        ]
        # a.py changed since commit_X, but NOT since commit_Y
        changed_files_by_commit = {
            "commit_X": {"a.py"},
            "commit_Y": {"c.py"},  # b.py NOT changed
        }
        updates = check_passive_fixes(
            existing_findings=findings,
            current_hashes=set(),
            current_commit="commit_Z",
            changed_files_by_commit=changed_files_by_commit,
        )
        # Only finding A should be updated (file changed since its commit)
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["finding_hash"], "sha256:aaa")
        self.assertTrue(updates[0]["passive_fix_candidate"])

    def test_legacy_flat_set_still_works(self):
        """Passing changed_files as flat set still works (backward compat)."""
        findings = [
            {"finding_hash": "sha256:aaa", "status": "open", "file": "a.py",
             "last_seen_commit": "old", "passive_fix_candidate": False},
        ]
        updates = check_passive_fixes(
            existing_findings=findings,
            current_hashes=set(),
            current_commit="new",
            changed_files={"a.py"},
        )
        self.assertEqual(len(updates), 1)
        self.assertTrue(updates[0]["passive_fix_candidate"])


class TestRunMarkerWrittenInPostRun(unittest.TestCase):
    """Verify that post_run writes a run marker to the context space."""

    def test_run_marker_written(self):
        from runtime.bridge.finding_hash import compute_finding_hash
        from runtime.config import ReviewPolicy
        from runtime.review_engine import ReviewRequest
        from runtime.hooks import RunHooks

        remembered = {}

        def fake_call_tool_sync(name, arguments):
            if name == "list_spaces":
                return []
            if name == "fetch_history":
                return []
            if name == "remember":
                space = arguments.get("space_id", "")
                content = arguments.get("content", "")
                if space not in remembered:
                    remembered[space] = []
                remembered[space].append(content)
                return {"request_id": "req-1"}
            if name == "request_status":
                return {"lifecycle": "searchable"}
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch("runtime.bridge.core._current_commit", return_value="abc"), \
                 patch("runtime.bridge.core._changed_files_since", return_value=set()), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                from runtime.bridge import register_hooks
                hooks = RunHooks()
                req = ReviewRequest(
                    repo_root=tmpdir, prompt="test", providers=["claude"],
                    artifact_base=tmpdir, policy=ReviewPolicy(),
                    memory_enabled=True, memory_space="myrepo",
                )
                register_hooks(hooks, req)

                hooks.invoke_post_run(
                    findings=[{
                        "title": "Bug", "category": "logic", "severity": "low",
                        "evidence": {"file": "a.py", "line": 1, "snippet": "x"},
                        "recommendation": "fix", "confidence": 0.5, "fingerprint": "fp",
                    }],
                    provider_results={"claude": {"success": True}},
                    repo_root=tmpdir, prompt="test", providers=["claude"],
                )

            # Verify run marker in context space
            context_contents = remembered.get("coding:myrepo--context", [])
            markers = [c for c in context_contents if c.startswith(MCO_RUN_MARKER_PREFIX)]
            self.assertEqual(len(markers), 1)
            marker_data = json.loads(markers[0][len(MCO_RUN_MARKER_PREFIX):])
            self.assertIn("timestamp", marker_data)
            self.assertEqual(marker_data["providers"], ["claude"])


if __name__ == "__main__":
    unittest.main()
