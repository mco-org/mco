from __future__ import annotations

import json
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from runtime.bridge.space import infer_space_slug
from runtime.bridge.prompt_builder import build_injected_prompt


class TestInferSpaceSlug(unittest.TestCase):
    def test_from_git_remote_https(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = os.path.join(tmpdir, ".git")
            os.makedirs(git_dir)
            with open(os.path.join(git_dir, "config"), "w") as f:
                f.write('[remote "origin"]\n  url = https://github.com/mco-org/mco.git\n')
            slug = infer_space_slug(tmpdir)
            self.assertEqual(slug, "mco-org--mco")

    def test_from_git_remote_ssh(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = os.path.join(tmpdir, ".git")
            os.makedirs(git_dir)
            with open(os.path.join(git_dir, "config"), "w") as f:
                f.write('[remote "origin"]\n  url = git@github.com:mco-org/mco.git\n')
            slug = infer_space_slug(tmpdir)
            self.assertEqual(slug, "mco-org--mco")

    def test_fallback_to_dirname(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            slug = infer_space_slug(tmpdir)
            self.assertEqual(slug, os.path.basename(tmpdir))

    def test_explicit_override(self):
        slug = infer_space_slug("/tmp", explicit="my-project")
        self.assertEqual(slug, "my-project")


class TestBuildInjectedPrompt(unittest.TestCase):
    def test_no_history_returns_original(self):
        result = build_injected_prompt(
            original="review for bugs",
            context=None,
            known_open=[],
            accepted_risks=[],
        )
        self.assertEqual(result, "review for bugs")

    def test_injects_context(self):
        result = build_injected_prompt(
            original="review",
            context="This project uses FastAPI with SQLAlchemy.",
            known_open=[],
            accepted_risks=[],
        )
        self.assertIn("FastAPI", result)
        self.assertIn("review", result)

    def test_injects_accepted_risks(self):
        result = build_injected_prompt(
            original="review",
            context=None,
            known_open=[],
            accepted_risks=[{"title": "Known XSS in admin panel", "finding_hash": "sha256:abc"}],
        )
        self.assertIn("Known XSS in admin panel", result)
        self.assertIn("accepted risk", result.lower())

    def test_injects_open_findings(self):
        result = build_injected_prompt(
            original="review",
            context=None,
            known_open=[{"title": "SQL injection", "file": "user.py", "finding_hash": "sha256:xyz"}],
            accepted_risks=[],
        )
        self.assertIn("SQL injection", result)

    def test_max_injected_findings_caps_output(self):
        findings = [{"title": f"Finding {i}", "file": "f.py", "finding_hash": f"h{i}"} for i in range(30)]
        result = build_injected_prompt(
            original="review",
            context=None,
            known_open=findings,
            accepted_risks=[],
            max_injected_findings=5,
        )
        count = sum(1 for i in range(30) if f"Finding {i}" in result)
        self.assertLessEqual(count, 5)

    def test_original_prompt_always_first(self):
        result = build_injected_prompt(
            original="review for bugs",
            context="some context",
            known_open=[{"title": "t", "file": "f", "finding_hash": "h"}],
            accepted_risks=[],
        )
        self.assertTrue(result.startswith("review for bugs"))


class TestBridgePostRunPersistence(unittest.TestCase):
    """Verify post_run produces correct serialized content for evermemos."""

    def test_post_run_serializes_with_hash_and_occurrence(self):
        """New findings get occurrence_count=1, first_seen==last_seen."""
        from runtime.bridge.finding_hash import compute_finding_hash
        from runtime.bridge.evermemos_client import EverMemosClient

        finding = {
            "finding_hash": compute_finding_hash("repo", "f.py", "bug", "null deref"),
            "category": "bug",
            "severity": "medium",
            "title": "null deref",
            "file": "f.py",
            "occurrence_count": 1,
            "first_seen": "2026-03-11T00:00:00Z",
            "last_seen": "2026-03-11T00:00:00Z",
            "status": "open",
        }
        serialized = EverMemosClient.serialize_finding(finding)
        roundtrip = EverMemosClient.deserialize_finding(serialized)
        self.assertEqual(roundtrip["occurrence_count"], 1)
        self.assertEqual(roundtrip["status"], "open")
        self.assertTrue(roundtrip["finding_hash"].startswith("sha256:"))

    def test_existing_finding_increments_occurrence(self):
        """When a finding already exists in history, occurrence_count bumps."""
        from runtime.bridge.core import _merge_finding_with_existing

        existing = {
            "finding_hash": "sha256:abc",
            "occurrence_count": 2,
            "first_seen": "2026-03-01T00:00:00Z",
            "last_seen": "2026-03-05T00:00:00Z",
            "detected_by": ["claude"],
            "severity": "medium",
            "status": "open",
        }
        new_raw = {
            "severity": "high",
            "detected_by": ["gemini"],
        }
        merged = _merge_finding_with_existing(existing, new_raw, commit="abc123")
        self.assertEqual(merged["occurrence_count"], 3)
        self.assertIn("claude", merged["detected_by"])
        self.assertIn("gemini", merged["detected_by"])
        self.assertEqual(merged["last_seen_commit"], "abc123")
        # first_seen unchanged
        self.assertEqual(merged["first_seen"], "2026-03-01T00:00:00Z")


if __name__ == "__main__":
    unittest.main()
