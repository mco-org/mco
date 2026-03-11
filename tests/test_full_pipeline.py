"""End-to-end integration test for the full Phase 1-4 memory bridge pipeline.

Validates the complete chain: register_hooks -> pre_run -> post_run across
multiple consecutive MCO runs using a stateful mock at the EverMemosClient
._call_tool_sync level. This ensures all components (space inference,
serialization, finding merge, confidence, scoring, stack aggregation,
passive confirmation, forget cleanup, status polling, cold-start priors)
work together correctly.
"""
from __future__ import annotations

import json
import os
import tempfile
import unittest
from typing import Any, Dict, List, Optional
from unittest.mock import patch

from runtime.bridge.evermemos_client import EverMemosClient
from runtime.bridge.finding_hash import compute_finding_hash
from runtime.config import ReviewPolicy
from runtime.hooks import RunHooks
from runtime.review_engine import ReviewRequest


class StatefulMockClient:
    """Tracks remembered content across calls to simulate evermemos state.

    Each call to ``remember()`` appends to a per-space list so that
    ``fetch_history()`` on a subsequent run returns everything written
    by prior runs.  ``forget()`` records which memory_ids were deleted.
    ``request_status()`` tracks how many polls occurred.
    """

    def __init__(self) -> None:
        self.remembered: Dict[str, List[str]] = {}  # space -> list of contents
        self.forgotten: List[str] = []  # memory_ids
        self.status_polls: int = 0
        self._remember_counter: int = 0

    def fake_call_tool_sync(self, name: str, arguments: Dict[str, Any]) -> Any:
        if name == "list_spaces":
            return list(self.remembered.keys())
        if name == "fetch_history":
            space = arguments.get("space_id", "")
            items = self.remembered.get(space, [])
            return [{"content": c} for c in items]
        if name == "remember":
            space = arguments.get("space_id", "")
            content = arguments.get("content", "")
            if space not in self.remembered:
                self.remembered[space] = []
            self.remembered[space].append(content)
            self._remember_counter += 1
            return {"request_id": f"req-{self._remember_counter}"}
        if name == "briefing":
            return "Test project context"
        if name == "request_status":
            self.status_polls += 1
            return {"lifecycle": "searchable"}
        if name == "forget":
            self.forgotten.extend(arguments.get("memory_ids", []))
            return None
        return None


def _setup_repo(tmpdir: str, *, with_pyproject: bool = True) -> None:
    """Create a fake git repo structure for space inference and stack detection."""
    git_dir = os.path.join(tmpdir, ".git")
    os.makedirs(git_dir, exist_ok=True)
    with open(os.path.join(git_dir, "config"), "w") as f:
        f.write('[remote "origin"]\n  url = https://github.com/test-org/test-repo.git\n')
    if with_pyproject:
        with open(os.path.join(tmpdir, "pyproject.toml"), "w") as f:
            f.write("[project]\nname = 'test'\n")


def _make_hooks_and_req(
    tmpdir: str,
    providers: List[str],
    prompt: str = "review for security issues",
    memory_space: Optional[str] = None,
) -> tuple:
    """Create RunHooks + ReviewRequest, call register_hooks, return (hooks, req)."""
    from runtime.bridge import register_hooks

    hooks = RunHooks()
    req = ReviewRequest(
        repo_root=tmpdir,
        prompt=prompt,
        providers=providers,
        artifact_base=tmpdir,
        policy=ReviewPolicy(),
        memory_enabled=True,
        memory_space=memory_space,
    )
    register_hooks(hooks, req)
    return hooks, req


class TestTwoCycleFullPipeline(unittest.TestCase):
    """Simulate two consecutive MCO runs and verify the full Phase 1-4 flow."""

    def test_two_cycle_full_pipeline(self):
        mock = StatefulMockClient()
        providers = ["claude", "gemini"]
        slug = "test-org--test-repo"
        findings_space = f"coding:{slug}--findings"
        agents_space = f"coding:{slug}--agents"
        stack_space = "coding:stacks--python"

        # Compute real hashes so merge logic matches
        critical_hash = compute_finding_hash(
            repo=slug, file_path="auth.py", category="security", title="SQL injection in login",
        )
        medium_hash = compute_finding_hash(
            repo=slug, file_path="utils.py", category="bug", title="Off-by-one in parser",
        )
        low_hash = compute_finding_hash(
            repo=slug, file_path="config.py", category="style", title="Unused import os",
        )

        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(tmpdir)

            # ── Run 1: Cold start ──────────────────────────────────
            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=mock.fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch("runtime.bridge.core._current_commit", return_value="aaa111"), \
                 patch("runtime.bridge.core._changed_files_since", return_value=set()), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                hooks1, _ = _make_hooks_and_req(tmpdir, providers)

                # Pre-run: cold start, no history
                prompt1 = hooks1.invoke_pre_run(
                    prompt="review for security issues",
                    repo_root=tmpdir,
                    providers=providers,
                )
                # With no findings space in mock yet, original prompt returned unchanged
                self.assertEqual(prompt1, "review for security issues")

                # Post-run: two findings — critical security + medium bug
                hooks1.invoke_post_run(
                    findings=[
                        {
                            "title": "SQL injection in login",
                            "category": "security",
                            "severity": "critical",
                            "evidence": {"file": "auth.py", "line": 42, "snippet": "query(user_input)"},
                            "recommendation": "Use parameterized queries",
                            "confidence": 0.5,
                            "fingerprint": "fp1",
                            "detected_by": ["claude", "gemini"],
                        },
                        {
                            "title": "Off-by-one in parser",
                            "category": "bug",
                            "severity": "medium",
                            "evidence": {"file": "utils.py", "line": 10, "snippet": "for i in range(n)"},
                            "recommendation": "Use range(n+1)",
                            "confidence": 0.5,
                            "fingerprint": "fp2",
                            "detected_by": ["claude"],
                        },
                    ],
                    provider_results={"claude": {"success": True}, "gemini": {"success": True}},
                    repo_root=tmpdir,
                    prompt="review for security issues",
                    providers=providers,
                )

            # ── Verify Run 1 outputs ──────────────────────────────

            # Findings written
            finding_contents_1 = [
                c for c in mock.remembered.get(findings_space, [])
                if EverMemosClient.is_finding_entry(c)
            ]
            self.assertEqual(len(finding_contents_1), 2, "Run 1 should write 2 findings")

            # Check the critical finding has confidence computed
            critical_finding = None
            medium_finding = None
            for c in finding_contents_1:
                f = EverMemosClient.deserialize_finding(c)
                if f.get("finding_hash") == critical_hash:
                    critical_finding = f
                elif f.get("finding_hash") == medium_hash:
                    medium_finding = f

            self.assertIsNotNone(critical_finding, "Critical finding should be persisted")
            self.assertIsNotNone(medium_finding, "Medium finding should be persisted")
            self.assertEqual(critical_finding["occurrence_count"], 1)
            self.assertIsInstance(critical_finding["confidence"], float)
            self.assertGreater(critical_finding["confidence"], 0.0)
            self.assertEqual(critical_finding["last_seen_commit"], "aaa111")

            # Agent scores written
            agent_scores_1 = [
                c for c in mock.remembered.get(agents_space, [])
                if EverMemosClient.is_agent_score_entry(c)
            ]
            self.assertGreater(len(agent_scores_1), 0, "Agent scores should be written in Run 1")

            # Stack aggregate written
            stack_scores_1 = [
                c for c in mock.remembered.get(stack_space, [])
                if EverMemosClient.is_agent_score_entry(c)
            ]
            self.assertGreater(len(stack_scores_1), 0, "Stack aggregate should be written in Run 1")

            # Status polling triggered for critical finding
            self.assertGreater(mock.status_polls, 0, "request_status should be polled for critical finding")

            # ── Run 2: Warm start ──────────────────────────────────
            # Reset polls counter for Run 2
            run1_polls = mock.status_polls
            mock.status_polls = 0

            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=mock.fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch("runtime.bridge.core._current_commit", return_value="bbb222"), \
                 patch("runtime.bridge.core._changed_files_since", return_value={"utils.py"}), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                hooks2, _ = _make_hooks_and_req(tmpdir, providers)

                # Pre-run: history from Run 1 now available
                prompt2 = hooks2.invoke_pre_run(
                    prompt="review for security issues",
                    repo_root=tmpdir,
                    providers=providers,
                )

                # Verify injected prompt contains Run 1 findings with confidence grades
                self.assertIn("SQL injection in login", prompt2)
                self.assertIn("Off-by-one in parser", prompt2)
                self.assertIn("review for security issues", prompt2)
                # Confidence grades should appear (agent_weights populated from Run 1 scores)
                self.assertTrue(
                    "[HIGH]" in prompt2 or "[MEDIUM]" in prompt2 or "[LOW]" in prompt2,
                    "Confidence grades should appear in injected prompt",
                )

                # Post-run Run 2:
                # - Same critical issue (should merge: occurrence_count++)
                # - Medium bug NOT found (passive confirm candidate since utils.py changed)
                # - New low issue
                hooks2.invoke_post_run(
                    findings=[
                        {
                            "title": "SQL injection in login",
                            "category": "security",
                            "severity": "critical",
                            "evidence": {"file": "auth.py", "line": 42, "snippet": "query(user_input)"},
                            "recommendation": "Use parameterized queries",
                            "confidence": 0.5,
                            "fingerprint": "fp1",
                            "detected_by": ["claude"],
                        },
                        {
                            "title": "Unused import os",
                            "category": "style",
                            "severity": "low",
                            "evidence": {"file": "config.py", "line": 1, "snippet": "import os"},
                            "recommendation": "Remove unused import",
                            "confidence": 0.5,
                            "fingerprint": "fp3",
                            "detected_by": ["gemini"],
                        },
                    ],
                    provider_results={"claude": {"success": True}, "gemini": {"success": True}},
                    repo_root=tmpdir,
                    prompt="review for security issues",
                    providers=providers,
                )

            # ── Verify Run 2 outputs ──────────────────────────────

            # Collect all findings written in Run 2 (after Run 1's findings)
            all_findings_content = [
                c for c in mock.remembered.get(findings_space, [])
                if EverMemosClient.is_finding_entry(c)
            ]
            # Run 1 wrote 2, Run 2 should write at least 2 (merged critical + new low)
            # plus passive confirm update for medium bug
            self.assertGreater(len(all_findings_content), 2, "Run 2 should write additional findings")

            # Find the merged critical finding from Run 2
            # It will be the latest one with the critical hash
            merged_critical = None
            for c in reversed(all_findings_content):
                f = EverMemosClient.deserialize_finding(c)
                if f.get("finding_hash") == critical_hash:
                    merged_critical = f
                    break

            self.assertIsNotNone(merged_critical, "Merged critical finding should exist")
            self.assertEqual(merged_critical["occurrence_count"], 2, "Merged finding should have occurrence_count=2")
            self.assertIn("claude", merged_critical["detected_by"])
            self.assertIn("gemini", merged_critical["detected_by"])
            self.assertEqual(merged_critical["last_seen_commit"], "bbb222")

            # Find passive confirm candidate for medium bug
            passive_updates = []
            for c in all_findings_content:
                f = EverMemosClient.deserialize_finding(c)
                if f.get("finding_hash") == medium_hash and f.get("passive_fix_candidate") is True:
                    passive_updates.append(f)

            self.assertGreater(
                len(passive_updates), 0,
                "Medium bug should be marked passive_fix_candidate=True "
                "(absent from Run 2, utils.py changed)",
            )

            # Verify new low issue was written
            low_findings = [
                EverMemosClient.deserialize_finding(c)
                for c in all_findings_content
                if EverMemosClient.deserialize_finding(c).get("finding_hash") == low_hash
            ]
            self.assertGreater(len(low_findings), 0, "New low issue should be written in Run 2")
            self.assertEqual(low_findings[-1]["occurrence_count"], 1)

            # Verify agent scores accumulated (not reset) — more entries in Run 2
            all_agent_scores = [
                c for c in mock.remembered.get(agents_space, [])
                if EverMemosClient.is_agent_score_entry(c)
            ]
            self.assertGreater(
                len(all_agent_scores), len(agent_scores_1),
                "Agent scores should accumulate across runs (Run 2 adds more)",
            )


class TestRejectedFindingForgotten(unittest.TestCase):
    """Verify that rejected findings with memory_id are cleaned up via forget()."""

    def test_rejected_finding_forgotten(self):
        mock = StatefulMockClient()
        slug = "test-org--test-repo"
        findings_space = f"coding:{slug}--findings"

        rejected_hash = compute_finding_hash(
            repo=slug, file_path="old.py", category="bug", title="False positive null check",
        )

        # Pre-populate the mock with a rejected finding that has a memory_id
        rejected_finding = EverMemosClient.serialize_finding({
            "finding_hash": rejected_hash,
            "title": "False positive null check",
            "category": "bug",
            "severity": "medium",
            "file": "old.py",
            "status": "rejected",
            "memory_id": "mem-rejected-001",
            "occurrence_count": 1,
            "first_seen": "2026-03-01T00:00:00Z",
            "last_seen": "2026-03-01T00:00:00Z",
            "last_seen_commit": "old_commit",
            "detected_by": ["claude"],
        })
        mock.remembered[findings_space] = [rejected_finding]

        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(tmpdir)

            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=mock.fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch("runtime.bridge.core._current_commit", return_value="ccc333"), \
                 patch("runtime.bridge.core._changed_files_since", return_value=set()), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                hooks, _ = _make_hooks_and_req(tmpdir, ["claude"])

                # Post-run with empty findings: the rejected finding should be forgotten
                hooks.invoke_post_run(
                    findings=[],
                    provider_results={"claude": {"success": True}},
                    repo_root=tmpdir,
                    prompt="review code",
                    providers=["claude"],
                )

            # Verify forget() was called with the rejected finding's memory_id
            self.assertIn(
                "mem-rejected-001",
                mock.forgotten,
                "Rejected finding with memory_id should be forgotten",
            )


class TestColdStartWeightsFromStackPriors(unittest.TestCase):
    """Verify that cold-start repos pick up agent weights from stack-level priors."""

    def test_cold_start_weights_from_stack_priors(self):
        mock = StatefulMockClient()
        slug = "test-org--test-repo"

        # Pre-populate stack-level agent scores (simulating another repo
        # having previously written scores to the python stack space)
        from runtime.bridge.scoring import AgentScore

        claude_stack_score = AgentScore(
            agent="claude",
            repo="other-repo",
            task_category="security",
            cross_validated_count=8,
            cross_validated_rate=0.8,
            finding_eval_count=10,
            last_updated="2026-03-01T00:00:00Z",
        )
        gemini_stack_score = AgentScore(
            agent="gemini",
            repo="other-repo",
            task_category="security",
            cross_validated_count=3,
            cross_validated_rate=0.3,
            finding_eval_count=10,
            last_updated="2026-03-01T00:00:00Z",
        )

        stack_space = "coding:stacks--python"
        mock.remembered[stack_space] = [
            EverMemosClient.serialize_agent_score(claude_stack_score.to_dict()),
            EverMemosClient.serialize_agent_score(gemini_stack_score.to_dict()),
        ]

        # NO repo-level scores and NO findings space — true cold start
        # But the findings space must not exist so pre_run skips briefing/history

        with tempfile.TemporaryDirectory() as tmpdir:
            _setup_repo(tmpdir, with_pyproject=True)

            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=mock.fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                from runtime.bridge import register_hooks
                from runtime.bridge.core import BridgeContext, make_pre_run

                hooks = RunHooks()
                req = ReviewRequest(
                    repo_root=tmpdir,
                    prompt="security review",
                    providers=["claude", "gemini"],
                    artifact_base=tmpdir,
                    policy=ReviewPolicy(),
                    memory_enabled=True,
                )
                register_hooks(hooks, req)

                prompt = hooks.invoke_pre_run(
                    prompt="security review",
                    repo_root=tmpdir,
                    providers=["claude", "gemini"],
                )

            # Access the BridgeContext through the hooks closure to verify weights.
            # The closure is hooks._pre_run.__closure__; ctx is the first cell.
            # We'll verify indirectly: with stack priors but no repo scores,
            # agent_weights should be populated with unequal values reflecting
            # the different stack-level rates.

            # Since we can't easily access the closure, we test via the prompt:
            # with no findings, prompt is unchanged, but the weights were computed
            # internally. Let's verify by running a second pass where we observe
            # the weights via confidence in findings.

            # Alternative: run post_run with findings and check that confidence
            # reflects non-default weights.
            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=mock.fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch("runtime.bridge.core._current_commit", return_value="ddd444"), \
                 patch("runtime.bridge.core._changed_files_since", return_value=set()), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                # Re-register hooks (fresh context) to pick up the now-populated stack priors
                hooks2 = RunHooks()
                req2 = ReviewRequest(
                    repo_root=tmpdir,
                    prompt="security review",
                    providers=["claude", "gemini"],
                    artifact_base=tmpdir,
                    policy=ReviewPolicy(),
                    memory_enabled=True,
                )
                register_hooks(hooks2, req2)

                # Pre-run to load weights from stack priors
                hooks2.invoke_pre_run(
                    prompt="security review",
                    repo_root=tmpdir,
                    providers=["claude", "gemini"],
                )

                # Now post_run with a finding detected by only claude
                hooks2.invoke_post_run(
                    findings=[{
                        "title": "Hardcoded secret",
                        "category": "security",
                        "severity": "high",
                        "evidence": {"file": "settings.py", "line": 5, "snippet": "SECRET='abc'"},
                        "recommendation": "Use env var",
                        "confidence": 0.5,
                        "fingerprint": "fp-cold",
                        "detected_by": ["claude"],
                    }],
                    provider_results={"claude": {"success": True}, "gemini": {"success": True}},
                    repo_root=tmpdir,
                    prompt="security review",
                    providers=["claude", "gemini"],
                )

            # Extract the finding that was written
            findings_space = f"coding:{slug}--findings"
            finding_contents = [
                c for c in mock.remembered.get(findings_space, [])
                if EverMemosClient.is_finding_entry(c)
            ]
            self.assertGreater(len(finding_contents), 0, "Finding should be written")

            persisted = EverMemosClient.deserialize_finding(finding_contents[-1])
            confidence = persisted["confidence"]

            # With stack priors giving claude=0.8 and gemini=0.3, and cold start
            # (run_count=0 so alpha=0), the blended weight for claude should be
            # 0.7*0.8 + 0.3*0 = 0.56 (from prior only).
            # Default weight would be 0.5. With stack priors, claude's weight
            # should be ~0.56, yielding a different confidence than default.
            # Specifically: consensus = 1/2 = 0.5, reliability = 0.56,
            # recurrence = 1/3 = 0.333, confidence = 0.4*0.5 + 0.4*0.56 + 0.2*0.333 = 0.49
            # With default weight (0.5): 0.4*0.5 + 0.4*0.5 + 0.2*0.333 = 0.467
            # So confidence with priors should be > 0.467
            self.assertIsInstance(confidence, float)
            self.assertGreater(confidence, 0.0)

            # More specifically, verify that confidence is NOT the pure-default value
            # Default: 0.4*(1/2) + 0.4*0.5 + 0.2*(1/3) ~= 0.467
            default_confidence = 0.4 * 0.5 + 0.4 * 0.5 + 0.2 * (1.0 / 3.0)
            self.assertNotAlmostEqual(
                confidence, default_confidence, places=3,
                msg="Confidence should differ from pure default, proving stack priors were applied",
            )


if __name__ == "__main__":
    unittest.main()
