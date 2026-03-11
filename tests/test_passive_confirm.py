from __future__ import annotations

import unittest

from runtime.bridge.passive_confirm import check_passive_fixes


class TestPassiveConfirm(unittest.TestCase):
    """Tests for passive fix confirmation (two-strike rule)."""

    def _make_finding(
        self,
        finding_hash: str = "sha256:aaa",
        status: str = "open",
        file: str = "src/app.py",
        last_seen_commit: str = "abc1234",
        passive_fix_candidate: bool = False,
    ) -> dict:
        return {
            "finding_hash": finding_hash,
            "status": status,
            "file": file,
            "last_seen_commit": last_seen_commit,
            "passive_fix_candidate": passive_fix_candidate,
            "category": "bug",
            "severity": "medium",
            "title": "Some bug",
            "occurrence_count": 1,
        }

    def test_open_finding_missing_and_file_changed_becomes_candidate(self):
        """First absence + file changed -> passive_fix_candidate=True, status still open."""
        finding = self._make_finding(
            finding_hash="sha256:aaa",
            status="open",
            file="src/app.py",
            last_seen_commit="old_commit",
            passive_fix_candidate=False,
        )
        # Finding hash NOT in current_hashes (absent), file IS in changed_files
        updates = check_passive_fixes(
            existing_findings=[finding],
            current_hashes=set(),
            current_commit="new_commit",
            changed_files={"src/app.py"},
        )
        self.assertEqual(len(updates), 1)
        self.assertTrue(updates[0]["passive_fix_candidate"])
        self.assertEqual(updates[0]["status"], "open")
        # Must not mutate original
        self.assertFalse(finding["passive_fix_candidate"])

    def test_candidate_missing_again_becomes_fixed(self):
        """Second consecutive absence -> status=fixed."""
        finding = self._make_finding(
            finding_hash="sha256:bbb",
            status="open",
            file="src/model.py",
            last_seen_commit="commit_1",
            passive_fix_candidate=True,
        )
        updates = check_passive_fixes(
            existing_findings=[finding],
            current_hashes=set(),
            current_commit="commit_2",
            changed_files={"src/model.py"},
        )
        self.assertEqual(len(updates), 1)
        self.assertEqual(updates[0]["status"], "fixed")
        # Original unchanged
        self.assertEqual(finding["status"], "open")

    def test_finding_reappears_clears_candidate_flag(self):
        """If a candidate reappears in current run, clear the flag."""
        finding = self._make_finding(
            finding_hash="sha256:ccc",
            status="open",
            file="src/util.py",
            last_seen_commit="commit_old",
            passive_fix_candidate=True,
        )
        # Finding hash IS in current_hashes (reappeared)
        updates = check_passive_fixes(
            existing_findings=[finding],
            current_hashes={"sha256:ccc"},
            current_commit="commit_new",
            changed_files={"src/util.py"},
        )
        self.assertEqual(len(updates), 1)
        self.assertFalse(updates[0]["passive_fix_candidate"])
        self.assertEqual(updates[0]["status"], "open")

    def test_file_not_changed_no_update(self):
        """Same commit / file not changed -> no inference, no update."""
        finding = self._make_finding(
            finding_hash="sha256:ddd",
            status="open",
            file="src/stable.py",
            last_seen_commit="old_commit",
            passive_fix_candidate=False,
        )
        # Finding absent, but file NOT in changed_files
        updates = check_passive_fixes(
            existing_findings=[finding],
            current_hashes=set(),
            current_commit="new_commit",
            changed_files=set(),
        )
        self.assertEqual(len(updates), 0)

    def test_non_open_findings_skipped(self):
        """Only open findings are considered for passive confirmation."""
        findings = [
            self._make_finding(finding_hash="sha256:e1", status="accepted", file="a.py"),
            self._make_finding(finding_hash="sha256:e2", status="wontfix", file="b.py"),
            self._make_finding(finding_hash="sha256:e3", status="fixed", file="c.py"),
            self._make_finding(finding_hash="sha256:e4", status="rejected", file="d.py"),
        ]
        updates = check_passive_fixes(
            existing_findings=findings,
            current_hashes=set(),
            current_commit="new_commit",
            changed_files={"a.py", "b.py", "c.py", "d.py"},
        )
        self.assertEqual(len(updates), 0)

    def test_multiple_findings_mixed(self):
        """Multiple findings: only the ones that need updates are returned."""
        f1 = self._make_finding(
            finding_hash="sha256:m1", status="open", file="x.py",
            last_seen_commit="c1", passive_fix_candidate=False,
        )
        f2 = self._make_finding(
            finding_hash="sha256:m2", status="open", file="y.py",
            last_seen_commit="c1", passive_fix_candidate=True,
        )
        f3 = self._make_finding(
            finding_hash="sha256:m3", status="accepted", file="z.py",
            last_seen_commit="c1",
        )
        updates = check_passive_fixes(
            existing_findings=[f1, f2, f3],
            current_hashes=set(),
            current_commit="c2",
            changed_files={"x.py", "y.py", "z.py"},
        )
        by_hash = {u["finding_hash"]: u for u in updates}
        # f1: first absence -> candidate
        self.assertIn("sha256:m1", by_hash)
        self.assertTrue(by_hash["sha256:m1"]["passive_fix_candidate"])
        self.assertEqual(by_hash["sha256:m1"]["status"], "open")
        # f2: second absence -> fixed
        self.assertIn("sha256:m2", by_hash)
        self.assertEqual(by_hash["sha256:m2"]["status"], "fixed")
        # f3: non-open, skipped
        self.assertNotIn("sha256:m3", by_hash)

    def test_returns_copies_not_originals(self):
        """Returned dicts must be copies; originals must not be mutated."""
        finding = self._make_finding(
            finding_hash="sha256:copy",
            status="open",
            file="f.py",
            last_seen_commit="c_old",
            passive_fix_candidate=False,
        )
        updates = check_passive_fixes(
            existing_findings=[finding],
            current_hashes=set(),
            current_commit="c_new",
            changed_files={"f.py"},
        )
        self.assertEqual(len(updates), 1)
        # Verify it's a different dict object
        self.assertIsNot(updates[0], finding)
        # Verify original not mutated
        self.assertFalse(finding["passive_fix_candidate"])
        self.assertEqual(finding["status"], "open")


if __name__ == "__main__":
    unittest.main()
