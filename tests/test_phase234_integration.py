"""Integration tests for Phase 2-4: confidence, classification, stack detection,
agent scoring, status polling, and cold-start weights wired into bridge hooks.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from typing import Any, Dict, List
from unittest.mock import MagicMock, patch

from runtime.bridge.evermemos_client import EverMemosClient


class TestPreRunLoadsAgentWeights(unittest.TestCase):
    """pre_run detects stack and loads agent weights from evermemos."""

    def test_pre_run_populates_stack_and_weights(self):
        """pre_run detects tech stack and computes agent weights from score spaces."""

        # Build serialized agent scores for the repo-level --agents space
        repo_score = EverMemosClient.serialize_agent_score({
            "agent": "claude",
            "repo": "test-org--test-repo",
            "task_category": "security",
            "cross_validated_rate": 0.8,
            "finding_eval_count": 10,
        })
        stack_score = EverMemosClient.serialize_agent_score({
            "agent": "gemini",
            "repo": "test-org--test-repo",
            "task_category": "security",
            "cross_validated_rate": 0.6,
            "finding_eval_count": 5,
        })

        open_finding = EverMemosClient.serialize_finding({
            "finding_hash": "sha256:aaa",
            "title": "SQL injection",
            "file": "api.py",
            "status": "open",
            "occurrence_count": 2,
            "detected_by": ["claude"],
        })

        def fake_call_tool_sync(name, arguments):
            space = arguments.get("space_id", "")
            if name == "list_spaces":
                return [
                    "coding:test-org--test-repo--findings",
                    "coding:test-org--test-repo--context",
                ]
            if name == "briefing":
                return "Python FastAPI project"
            if name == "fetch_history":
                if space == "coding:test-org--test-repo--findings":
                    return [{"content": open_finding}]
                if space == "coding:test-org--test-repo--agents":
                    return [{"content": repo_score}]
                if space.startswith("coding:stacks--"):
                    return [{"content": stack_score}]
                if space == "coding:global--agents":
                    return []
                return []
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create pyproject.toml so stack detector returns "python"
            with open(os.path.join(tmpdir, "pyproject.toml"), "w") as f:
                f.write("[project]\nname = 'test'\n")

            # Create fake git config
            git_dir = os.path.join(tmpdir, ".git")
            os.makedirs(git_dir)
            with open(os.path.join(git_dir, "config"), "w") as f:
                f.write('[remote "origin"]\n  url = https://github.com/test-org/test-repo.git\n')

            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                from runtime.bridge import register_hooks
                from runtime.bridge.core import BridgeContext, make_pre_run
                from runtime.hooks import RunHooks
                from runtime.config import ReviewPolicy
                from runtime.review_engine import ReviewRequest

                hooks = RunHooks()
                req = ReviewRequest(
                    repo_root=tmpdir,
                    prompt="review for security vulnerabilities",
                    providers=["claude", "gemini"],
                    artifact_base=tmpdir,
                    policy=ReviewPolicy(),
                    memory_enabled=True,
                )
                register_hooks(hooks, req)

                # Access the BridgeContext through the closure
                # We need to call pre_run to trigger the population
                result = hooks.invoke_pre_run(
                    prompt="review for security vulnerabilities",
                    repo_root=tmpdir,
                    providers=["claude", "gemini"],
                )

            # Verify prompt was augmented
            self.assertIn("SQL injection", result)
            self.assertIn("review for security vulnerabilities", result)
            # Verify confidence grade appears in injected prompt
            self.assertIn("[", result)  # e.g., [HIGH], [MEDIUM], or [LOW]

    def test_pre_run_cold_start_with_no_history(self):
        """pre_run handles cold start gracefully when no spaces exist."""

        def fake_call_tool_sync(name, arguments):
            if name == "list_spaces":
                return []  # No spaces exist yet
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            git_dir = os.path.join(tmpdir, ".git")
            os.makedirs(git_dir)
            with open(os.path.join(git_dir, "config"), "w") as f:
                f.write('[remote "origin"]\n  url = https://github.com/test-org/test-repo.git\n')

            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                from runtime.bridge import register_hooks
                from runtime.hooks import RunHooks
                from runtime.config import ReviewPolicy
                from runtime.review_engine import ReviewRequest

                hooks = RunHooks()
                req = ReviewRequest(
                    repo_root=tmpdir,
                    prompt="review code",
                    providers=["claude"],
                    artifact_base=tmpdir,
                    policy=ReviewPolicy(),
                    memory_enabled=True,
                )
                register_hooks(hooks, req)

                result = hooks.invoke_pre_run(
                    prompt="review code",
                    repo_root=tmpdir,
                    providers=["claude"],
                )

            # With no history, original prompt is returned unchanged
            self.assertEqual(result, "review code")


class TestPostRunWritesConfidenceAndScores(unittest.TestCase):
    """post_run computes confidence, classifies task, and writes agent scores."""

    def test_post_run_findings_have_computed_confidence(self):
        """Findings written via remember() have computed confidence values."""
        from runtime.bridge.finding_hash import compute_finding_hash

        real_hash = compute_finding_hash(
            repo="myrepo", file_path="main.py", category="security", title="SQL injection",
        )

        remembered_contents: List[str] = []

        def fake_call_tool_sync(name, arguments):
            if name == "list_spaces":
                return ["coding:myrepo--findings"]
            if name == "fetch_history":
                return []  # No existing findings
            if name == "remember":
                remembered_contents.append(arguments.get("content", ""))
                return {"request_id": "req-1"}
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch("runtime.bridge.core._current_commit", return_value="abc123"), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                from runtime.bridge import register_hooks
                from runtime.bridge.core import BridgeContext
                from runtime.hooks import RunHooks
                from runtime.config import ReviewPolicy
                from runtime.review_engine import ReviewRequest

                hooks = RunHooks()
                req = ReviewRequest(
                    repo_root=tmpdir,
                    prompt="check for SQL injection vulnerabilities",
                    providers=["claude", "gemini"],
                    artifact_base=tmpdir,
                    policy=ReviewPolicy(),
                    memory_enabled=True,
                    memory_space="myrepo",
                )
                register_hooks(hooks, req)

                hooks.invoke_post_run(
                    findings=[{
                        "title": "SQL injection",
                        "category": "security",
                        "severity": "critical",
                        "evidence": {"file": "main.py", "line": 42, "snippet": "query", "symbol": None},
                        "recommendation": "Use parameterized queries",
                        "confidence": 0.5,
                        "fingerprint": "fp1",
                        "detected_by": ["claude", "gemini"],
                    }],
                    provider_results={"claude": {"success": True}, "gemini": {"success": True}},
                    repo_root=tmpdir,
                    prompt="check for SQL injection vulnerabilities",
                    providers=["claude", "gemini"],
                )

            # Separate findings from agent scores
            finding_contents = [c for c in remembered_contents if EverMemosClient.is_finding_entry(c)]
            score_contents = [c for c in remembered_contents if EverMemosClient.is_agent_score_entry(c)]

            # Verify finding has computed confidence
            self.assertEqual(len(finding_contents), 1)
            persisted = EverMemosClient.deserialize_finding(finding_contents[0])
            self.assertIn("confidence", persisted)
            self.assertIsInstance(persisted["confidence"], float)
            # With 2 agents both detecting, consensus = 1.0, so confidence should be meaningful
            self.assertGreater(persisted["confidence"], 0.0)

            # Verify agent scores were written
            self.assertGreater(len(score_contents), 0)
            for sc in score_contents:
                score = EverMemosClient.deserialize_agent_score(sc)
                self.assertIn("agent", score)
                self.assertIn("cross_validated_rate", score)

    def test_post_run_classifies_task_for_scoring(self):
        """Agent scores are categorized by task classification."""
        remembered_contents: List[str] = []

        def fake_call_tool_sync(name, arguments):
            if name == "list_spaces":
                return ["coding:myrepo--findings"]
            if name == "fetch_history":
                return []
            if name == "remember":
                remembered_contents.append(arguments.get("content", ""))
                return {"request_id": None}
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch("runtime.bridge.core._current_commit", return_value="abc123"), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                from runtime.bridge import register_hooks
                from runtime.hooks import RunHooks
                from runtime.config import ReviewPolicy
                from runtime.review_engine import ReviewRequest

                hooks = RunHooks()
                req = ReviewRequest(
                    repo_root=tmpdir,
                    prompt="review for performance bottlenecks",
                    providers=["claude"],
                    artifact_base=tmpdir,
                    policy=ReviewPolicy(),
                    memory_enabled=True,
                    memory_space="myrepo",
                )
                register_hooks(hooks, req)

                hooks.invoke_post_run(
                    findings=[{
                        "title": "N+1 query in loop",
                        "category": "performance",
                        "severity": "medium",
                        "evidence": {"file": "views.py", "line": 10},
                        "recommendation": "Use prefetch_related",
                        "confidence": 0.7,
                        "fingerprint": "fp2",
                        "detected_by": ["claude"],
                    }],
                    provider_results={"claude": {"success": True}},
                    repo_root=tmpdir,
                    prompt="review for performance bottlenecks",
                    providers=["claude"],
                )

            # Verify agent score was written with the correct task_category
            score_contents = [c for c in remembered_contents if EverMemosClient.is_agent_score_entry(c)]
            self.assertGreater(len(score_contents), 0)
            score = EverMemosClient.deserialize_agent_score(score_contents[0])
            # The classifier should pick "performance" given the prompt and findings
            self.assertEqual(score["task_category"], "performance")

    def test_post_run_polls_critical_findings(self):
        """Status polling is triggered for critical/high severity findings."""
        remembered_contents: List[str] = []
        polled_ids: List[str] = []

        def fake_call_tool_sync(name, arguments):
            if name == "list_spaces":
                return ["coding:myrepo--findings"]
            if name == "fetch_history":
                return []
            if name == "remember":
                remembered_contents.append(arguments.get("content", ""))
                return {"request_id": "req-critical-1"}
            if name == "request_status":
                polled_ids.append(arguments.get("request_id", ""))
                return {"lifecycle": "searchable"}
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch("runtime.bridge.core._current_commit", return_value="abc123"), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                from runtime.bridge import register_hooks
                from runtime.hooks import RunHooks
                from runtime.config import ReviewPolicy
                from runtime.review_engine import ReviewRequest

                hooks = RunHooks()
                req = ReviewRequest(
                    repo_root=tmpdir,
                    prompt="security review",
                    providers=["claude"],
                    artifact_base=tmpdir,
                    policy=ReviewPolicy(),
                    memory_enabled=True,
                    memory_space="myrepo",
                )
                register_hooks(hooks, req)

                hooks.invoke_post_run(
                    findings=[{
                        "title": "Remote code execution",
                        "category": "security",
                        "severity": "critical",
                        "evidence": {"file": "app.py", "line": 5},
                        "recommendation": "Sanitize input",
                        "confidence": 0.9,
                        "fingerprint": "fp3",
                        "detected_by": ["claude"],
                    }],
                    provider_results={"claude": {"success": True}},
                    repo_root=tmpdir,
                    prompt="security review",
                    providers=["claude"],
                )

            # Verify status polling was triggered for the critical finding
            # The finding remember returns "req-critical-1", which is critical severity
            # The first remember() call is for the finding; agent score remember() also
            # returns "req-critical-1" but only finding severity triggers polling
            self.assertGreater(len(polled_ids), 0)


class TestPromptShowsConfidenceGrades(unittest.TestCase):
    """Injected prompt includes [HIGH]/[MEDIUM]/[LOW] grades."""

    def test_high_confidence_grade_in_prompt(self):
        from runtime.bridge.prompt_builder import build_injected_prompt

        findings = [{
            "title": "SQL injection",
            "file": "api.py",
            "confidence": 0.85,
            "detected_by": ["claude", "gemini"],
            "occurrence_count": 3,
        }]
        result = build_injected_prompt(
            original="review",
            context=None,
            known_open=findings,
            accepted_risks=[],
            agent_weights={"claude": 0.8, "gemini": 0.7},
            total_agents=2,
        )
        self.assertIn("[HIGH]", result)
        self.assertIn("SQL injection", result)

    def test_medium_confidence_grade_in_prompt(self):
        from runtime.bridge.prompt_builder import build_injected_prompt

        findings = [{
            "title": "Possible XSS",
            "file": "template.html",
            "confidence": 0.55,
            "detected_by": ["claude"],
            "occurrence_count": 1,
        }]
        result = build_injected_prompt(
            original="review",
            context=None,
            known_open=findings,
            accepted_risks=[],
            agent_weights={"claude": 0.5},
            total_agents=3,
        )
        self.assertIn("[MEDIUM]", result)
        self.assertIn("Possible XSS", result)

    def test_low_confidence_grade_in_prompt(self):
        from runtime.bridge.prompt_builder import build_injected_prompt

        findings = [{
            "title": "Minor style issue",
            "file": "utils.py",
            "confidence": 0.2,
            "detected_by": ["linter"],
            "occurrence_count": 1,
        }]
        result = build_injected_prompt(
            original="review",
            context=None,
            known_open=findings,
            accepted_risks=[],
            agent_weights={"linter": 0.3},
            total_agents=5,
        )
        self.assertIn("[LOW]", result)
        self.assertIn("Minor style issue", result)

    def test_no_grades_without_agent_weights(self):
        """When agent_weights is not provided, no grade labels appear."""
        from runtime.bridge.prompt_builder import build_injected_prompt

        findings = [{
            "title": "SQL injection",
            "file": "api.py",
            "confidence": 0.85,
        }]
        result = build_injected_prompt(
            original="review",
            context=None,
            known_open=findings,
            accepted_risks=[],
        )
        self.assertNotIn("[HIGH]", result)
        self.assertNotIn("[MEDIUM]", result)
        self.assertNotIn("[LOW]", result)
        self.assertIn("SQL injection", result)

    def test_grade_computed_from_weights_when_no_confidence_field(self):
        """When finding has no pre-computed confidence, grade is computed on the fly."""
        from runtime.bridge.prompt_builder import build_injected_prompt

        findings = [{
            "title": "Buffer overflow",
            "file": "parser.c",
            "detected_by": ["claude", "gemini"],
            "occurrence_count": 5,
            # No "confidence" key
        }]
        result = build_injected_prompt(
            original="review",
            context=None,
            known_open=findings,
            accepted_risks=[],
            agent_weights={"claude": 0.9, "gemini": 0.85},
            total_agents=2,
        )
        # With 2/2 agents detecting, high weights, and high occurrence,
        # confidence should be HIGH
        self.assertIn("[HIGH]", result)
        self.assertIn("Buffer overflow", result)


class TestLoadAgentRates(unittest.TestCase):
    """Unit test for the _load_agent_rates helper."""

    def test_loads_rates_from_agent_score_entries(self):
        from runtime.bridge.core import _load_agent_rates

        score1 = EverMemosClient.serialize_agent_score({
            "agent": "claude", "cross_validated_rate": 0.75,
            "repo": "test", "task_category": "security",
        })
        score2 = EverMemosClient.serialize_agent_score({
            "agent": "gemini", "cross_validated_rate": 0.6,
            "repo": "test", "task_category": "security",
        })

        client = MagicMock(spec=EverMemosClient)
        client.fetch_history.return_value = [
            {"content": score1},
            {"content": "some plain text"},
            {"content": score2},
        ]

        rates = _load_agent_rates(client, "coding:test--agents")
        self.assertEqual(rates, {"claude": 0.75, "gemini": 0.6})

    def test_returns_empty_on_error(self):
        from runtime.bridge.core import _load_agent_rates

        client = MagicMock(spec=EverMemosClient)
        client.fetch_history.side_effect = RuntimeError("connection failed")

        rates = _load_agent_rates(client, "coding:test--agents")
        self.assertEqual(rates, {})


class TestBridgeContextExpanded(unittest.TestCase):
    """Verify BridgeContext has the new Phase 2-4 fields."""

    def test_default_values(self):
        from runtime.bridge.core import BridgeContext
        ctx = BridgeContext()
        self.assertEqual(ctx.stack, "unknown")
        self.assertEqual(ctx.run_count, 0)
        self.assertEqual(ctx.agent_weights, {})
        self.assertEqual(ctx.total_agents, 0)

    def test_fields_are_mutable(self):
        from runtime.bridge.core import BridgeContext
        ctx = BridgeContext()
        ctx.stack = "python"
        ctx.run_count = 5
        ctx.agent_weights = {"claude": 0.8}
        ctx.total_agents = 3
        self.assertEqual(ctx.stack, "python")
        self.assertEqual(ctx.run_count, 5)
        self.assertEqual(ctx.agent_weights, {"claude": 0.8})
        self.assertEqual(ctx.total_agents, 3)


if __name__ == "__main__":
    unittest.main()
