"""Integration test: --memory flag end-to-end with mocked bridge."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from runtime.config import ReviewPolicy
from runtime.contracts import (
    CapabilitySet,
    NormalizeContext,
    ProviderPresence,
    TaskInput,
    TaskRunRef,
    TaskStatus,
)
from runtime.review_engine import ReviewRequest, run_review
from runtime.adapters.parsing import normalize_findings_from_text


class FakeMemoryAdapter:
    """Minimal fake adapter that returns one finding."""

    def __init__(self, provider: str):
        self.id = provider

    def detect(self):
        return ProviderPresence(provider=self.id, detected=True, binary_path="/bin/fake", version="1.0", auth_ok=True)

    def capabilities(self):
        return CapabilitySet(
            tiers=["C0", "C1"], supports_native_async=False,
            supports_poll_endpoint=False, supports_resume_after_restart=False,
            supports_schema_enforcement=False, min_supported_version="1.0", tested_os=["macos"],
        )

    def run(self, input_task: TaskInput) -> TaskRunRef:
        artifact_root = Path(input_task.metadata["artifact_root"]) / input_task.task_id
        (artifact_root / "raw").mkdir(parents=True, exist_ok=True)
        (artifact_root / "providers").mkdir(parents=True, exist_ok=True)

        finding_json = json.dumps({"findings": [{
            "finding_id": "f1", "severity": "medium", "category": "bug",
            "title": "Null pointer dereference",
            "evidence": {"file": "main.py", "line": 10, "snippet": "x.foo()", "symbol": None},
            "recommendation": "Add null check", "confidence": 0.8, "fingerprint": "fp1",
        }]})
        (artifact_root / "raw" / f"{self.id}.stdout.log").write_text(finding_json, encoding="utf-8")
        (artifact_root / "raw" / f"{self.id}.stderr.log").write_text("", encoding="utf-8")
        (artifact_root / "providers" / f"{self.id}.json").write_text(
            json.dumps({"provider": self.id, "ok": True}), encoding="utf-8"
        )
        return TaskRunRef(
            task_id=input_task.task_id, provider=self.id,
            run_id=f"{self.id}-run-1", artifact_path=str(artifact_root),
            started_at="2026-03-11T00:00:00Z", pid=1234,
        )

    def poll(self, ref: TaskRunRef) -> TaskStatus:
        return TaskStatus(
            task_id=ref.task_id, provider=ref.provider, run_id=ref.run_id,
            attempt_state="SUCCEEDED", completed=True,
            heartbeat_at="2026-03-11T00:00:01Z",
            output_path=f"{ref.artifact_path}/providers/{self.id}.json",
            error_kind=None, exit_code=0, message="completed",
        )

    def cancel(self, ref):
        pass

    def normalize(self, raw, ctx):
        text = raw if isinstance(raw, str) else ""
        return normalize_findings_from_text(text, ctx, self.id)


class TestMemoryHookWiring(unittest.TestCase):
    def test_memory_enabled_triggers_hooks(self):
        """When memory_enabled=True, pre_run and post_run hooks fire."""
        hook_calls = {"pre_run": 0, "post_run": 0, "post_run_findings": None}

        def mock_pre_run(prompt, repo_root, providers):
            hook_calls["pre_run"] += 1
            return prompt + "\n[memory injected]"

        def mock_post_run(findings, provider_results, repo_root, prompt, providers):
            hook_calls["post_run"] += 1
            hook_calls["post_run_findings"] = findings

        from runtime.hooks import RunHooks
        mock_hooks = RunHooks()
        mock_hooks.set_pre_run(mock_pre_run)
        mock_hooks.set_post_run(mock_post_run)

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review for bugs",
                providers=["fake"],
                artifact_base=tmpdir,
                policy=ReviewPolicy(stall_timeout_seconds=10, review_hard_timeout_seconds=30),
                memory_enabled=True,
            )
            adapter = FakeMemoryAdapter("fake")

            with patch("runtime.review_engine._load_memory_hooks", return_value=mock_hooks):
                result = run_review(req, adapters={"fake": adapter})

            self.assertEqual(hook_calls["pre_run"], 1)
            self.assertEqual(hook_calls["post_run"], 1)
            # post_run receives the merged findings list
            self.assertIsInstance(hook_calls["post_run_findings"], list)

    def test_memory_disabled_skips_hooks(self):
        """When memory_enabled=False, _load_memory_hooks is never called."""
        with tempfile.TemporaryDirectory() as tmpdir:
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review for bugs",
                providers=["fake"],
                artifact_base=tmpdir,
                policy=ReviewPolicy(stall_timeout_seconds=10, review_hard_timeout_seconds=30),
                memory_enabled=False,
            )
            adapter = FakeMemoryAdapter("fake")

            with patch("runtime.review_engine._load_memory_hooks") as mock_load:
                result = run_review(req, adapters={"fake": adapter})
                mock_load.assert_not_called()

    def test_hook_failure_does_not_break_review(self):
        """A broken hook should log but not crash the review."""
        def exploding_pre_run(prompt, repo_root, providers):
            raise RuntimeError("bridge exploded")

        from runtime.hooks import RunHooks
        mock_hooks = RunHooks()
        mock_hooks.set_pre_run(exploding_pre_run)

        with tempfile.TemporaryDirectory() as tmpdir:
            req = ReviewRequest(
                repo_root=tmpdir,
                prompt="review for bugs",
                providers=["fake"],
                artifact_base=tmpdir,
                policy=ReviewPolicy(stall_timeout_seconds=10, review_hard_timeout_seconds=30),
                memory_enabled=True,
            )
            adapter = FakeMemoryAdapter("fake")

            with patch("runtime.review_engine._load_memory_hooks", return_value=mock_hooks):
                # Should complete without raising
                result = run_review(req, adapters={"fake": adapter})
                self.assertIn(result.decision, ("PASS", "ESCALATE", "PARTIAL", "FAIL", "INCONCLUSIVE"))


class TestRealBridgePath(unittest.TestCase):
    """Test the real path: register_hooks -> bridge_pre_run/post_run -> client.

    Mocks at the EverMemosClient._call_tool_sync level, NOT at the hook level.
    This validates that register_hooks, BridgeContext, space inference,
    serialization, and prompt building all work together.
    """

    def test_pre_run_injects_history_from_client(self):
        """register_hooks -> bridge_pre_run -> EverMemosClient -> injected prompt."""
        from runtime.bridge.evermemos_client import EverMemosClient

        # Simulate evermemos returning one open finding and one accepted risk
        open_finding = EverMemosClient.serialize_finding({
            "finding_hash": "sha256:aaa", "title": "SQL injection",
            "file": "api.py", "status": "open", "occurrence_count": 2,
        })
        accepted_risk = EverMemosClient.serialize_finding({
            "finding_hash": "sha256:bbb", "title": "Known XSS",
            "file": "admin.py", "status": "accepted", "occurrence_count": 1,
        })

        call_log = []

        def fake_call_tool_sync(name, arguments):
            call_log.append(name)
            if name == "list_spaces":
                return ["coding:test-org--test-repo--findings", "coding:test-org--test-repo--context"]
            if name == "briefing":
                return "FastAPI project with PostgreSQL"
            if name == "fetch_history":
                return [
                    {"content": open_finding},
                    {"content": accepted_risk},
                    {"content": "some non-finding text"},  # should be skipped
                ]
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create fake git config for space inference
            import os
            git_dir = os.path.join(tmpdir, ".git")
            os.makedirs(git_dir)
            with open(os.path.join(git_dir, "config"), "w") as f:
                f.write('[remote "origin"]\n  url = https://github.com/test-org/test-repo.git\n')

            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                from runtime.bridge import register_hooks
                from runtime.hooks import RunHooks

                hooks = RunHooks()
                req = ReviewRequest(
                    repo_root=tmpdir, prompt="review for bugs", providers=["claude"],
                    artifact_base=tmpdir, policy=ReviewPolicy(), memory_enabled=True,
                )
                register_hooks(hooks, req)

                result = hooks.invoke_pre_run(
                    prompt="review for bugs", repo_root=tmpdir, providers=["claude"],
                )

            # Verify the full chain executed
            self.assertIn("list_spaces", call_log)
            self.assertIn("briefing", call_log)
            self.assertIn("fetch_history", call_log)
            # Verify prompt was augmented
            self.assertIn("SQL injection", result)
            self.assertIn("Known XSS", result)
            self.assertIn("FastAPI", result)
            self.assertIn("review for bugs", result)

    def test_post_run_writes_findings_with_merge(self):
        """register_hooks -> bridge_post_run -> remember with merge."""
        from runtime.bridge.evermemos_client import EverMemosClient

        from runtime.bridge.finding_hash import compute_finding_hash

        # Use the real hash so merge logic can match
        real_hash = compute_finding_hash(
            repo="myrepo", file_path="main.py", category="bug", title="null deref",
        )

        # Simulate existing finding in history
        existing = EverMemosClient.serialize_finding({
            "finding_hash": real_hash, "title": "null deref",
            "category": "bug", "file": "main.py",
            "status": "open", "occurrence_count": 1,
            "first_seen": "2026-03-01T00:00:00Z",
            "last_seen": "2026-03-01T00:00:00Z",
            "detected_by": ["claude"],
        })

        remembered_contents = []

        def fake_call_tool_sync(name, arguments):
            if name == "list_spaces":
                return ["coding:myrepo--findings"]
            if name == "fetch_history":
                return [{"content": existing}]
            if name == "remember":
                remembered_contents.append(arguments.get("content", ""))
                return {"request_id": "req-1"}
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch("runtime.bridge.core._current_commit", return_value="abc123"), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                from runtime.bridge import register_hooks
                from runtime.bridge.core import BridgeContext
                from runtime.bridge.finding_hash import compute_finding_hash
                from runtime.hooks import RunHooks

                hooks = RunHooks()
                req = ReviewRequest(
                    repo_root=tmpdir, prompt="test", providers=["claude", "gemini"],
                    artifact_base=tmpdir, policy=ReviewPolicy(),
                    memory_enabled=True, memory_space="myrepo",
                )
                register_hooks(hooks, req)

                # Finding that matches existing (same title + file + category)
                hooks.invoke_post_run(
                    findings=[{
                        "title": "null deref", "category": "bug", "severity": "high",
                        "evidence": {"file": "main.py", "line": 10, "snippet": "x", "symbol": None},
                        "recommendation": "check null", "confidence": 0.9, "fingerprint": "fp",
                        "detected_by": ["gemini"],
                    }],
                    provider_results={"claude": {"success": True}, "gemini": {"success": True}},
                    repo_root=tmpdir, prompt="test", providers=["claude", "gemini"],
                )

            # Verify remember was called (finding + agent scores)
            finding_contents = [c for c in remembered_contents if EverMemosClient.is_finding_entry(c)]
            self.assertEqual(len(finding_contents), 1)
            # Deserialize and check merge happened
            persisted = EverMemosClient.deserialize_finding(finding_contents[0])
            self.assertEqual(persisted["occurrence_count"], 2)  # merged, not appended
            self.assertIn("claude", persisted["detected_by"])
            self.assertIn("gemini", persisted["detected_by"])
            self.assertEqual(persisted["last_seen_commit"], "abc123")
            self.assertEqual(persisted["first_seen"], "2026-03-01T00:00:00Z")  # preserved
            # Verify confidence was computed (not just the raw value)
            self.assertIn("confidence", persisted)
            self.assertIsInstance(persisted["confidence"], float)
            # Verify agent scores were written
            score_contents = [c for c in remembered_contents if EverMemosClient.is_agent_score_entry(c)]
            self.assertGreater(len(score_contents), 0)


class TestPassiveConfirmTriggeredInPostRun(unittest.TestCase):
    """Post-run triggers passive confirmation for missing open findings."""

    def test_passive_confirm_triggered_in_post_run(self):
        """Post-run with no findings but file change triggers passive fix candidate."""
        from runtime.bridge.evermemos_client import EverMemosClient
        from runtime.bridge.finding_hash import compute_finding_hash

        real_hash = compute_finding_hash(
            repo="myrepo", file_path="main.py", category="bug", title="null deref",
        )

        # Simulate an existing open finding in history
        existing = EverMemosClient.serialize_finding({
            "finding_hash": real_hash, "title": "null deref",
            "category": "bug", "file": "main.py",
            "status": "open", "occurrence_count": 1,
            "first_seen": "2026-03-01T00:00:00Z",
            "last_seen": "2026-03-01T00:00:00Z",
            "last_seen_commit": "old_commit",
            "detected_by": ["claude"],
            "passive_fix_candidate": False,
        })

        remembered_contents = []

        def fake_call_tool_sync(name, arguments):
            if name == "list_spaces":
                return ["coding:myrepo--findings"]
            if name == "fetch_history":
                return [{"content": existing}]
            if name == "remember":
                remembered_contents.append(arguments.get("content", ""))
                return {"request_id": "req-1"}
            return None

        with tempfile.TemporaryDirectory() as tmpdir:
            import os
            with patch.object(EverMemosClient, "_call_tool_sync", side_effect=fake_call_tool_sync), \
                 patch.object(EverMemosClient, "_ensure_mcp_sdk"), \
                 patch("runtime.bridge.core._current_commit", return_value="new_commit"), \
                 patch("runtime.bridge.core._changed_files_since", return_value={"main.py"}), \
                 patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):

                from runtime.bridge import register_hooks
                from runtime.hooks import RunHooks

                hooks = RunHooks()
                req = ReviewRequest(
                    repo_root=tmpdir, prompt="test", providers=["claude"],
                    artifact_base=tmpdir, policy=ReviewPolicy(),
                    memory_enabled=True, memory_space="myrepo",
                )
                register_hooks(hooks, req)

                # Run post_run with NO findings but with a file change
                hooks.invoke_post_run(
                    findings=[],
                    provider_results={"claude": {"success": True}},
                    repo_root=tmpdir, prompt="test", providers=["claude"],
                )

            # Verify remember was called — filter for finding entries only
            # (run markers and other entries are also written)
            finding_contents = [c for c in remembered_contents if EverMemosClient.is_finding_entry(c)]
            self.assertEqual(len(finding_contents), 1)
            persisted = EverMemosClient.deserialize_finding(finding_contents[0])
            self.assertTrue(persisted["passive_fix_candidate"])
            self.assertEqual(persisted["status"], "open")
            self.assertEqual(persisted["finding_hash"], real_hash)


if __name__ == "__main__":
    unittest.main()
