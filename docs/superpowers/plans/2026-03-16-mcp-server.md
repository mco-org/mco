# MCP Server Mode Implementation Plan

> **For agentic workers:** REQUIRED: Use superpowers:subagent-driven-development (if subagents available) or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `mco serve` subcommand that starts a stdio MCP server exposing 5 tools (review, run, doctor, findings_list, memory_status).

**Architecture:** `runtime/mcp_server.py` defines tools with `@server.tool()` decorators. All sync MCO functions are called via `asyncio.to_thread()`. `cli.py` adds a thin `serve` subcommand. Data layer functions are extracted from `memory_cli.py` and `findings_cli.py` for structured (non-rendered) output. All tool responses use `{"ok": true/false, ...}` envelope.

**Tech Stack:** Python 3.10+, mcp>=1.0 (optional dependency), asyncio, existing unittest framework.

**Spec:** `docs/superpowers/specs/2026-03-16-mcp-server-design.md`

---

## File Structure

| File | Action | Responsibility |
|------|--------|---------------|
| `runtime/mcp_server.py` | Create | MCP server: 5 tool handlers + envelope helpers + `run_server()` entry point |
| `runtime/cli.py` | Modify | Add `serve` subcommand to `build_parser()` and dispatch in `main()` |
| `runtime/memory_cli.py` | Modify | Extract `get_status_data()` from `show_status()` |
| `runtime/findings_cli.py` | Modify | Extract `get_findings_data()` from `list_findings()` (already returns structured data — just add alias) |
| `tests/test_mcp_server.py` | Create | Unit tests for all 5 tool sync helpers + envelope |
| `tests/test_mcp_data_layer.py` | Create | Tests for `get_status_data()` |

---

## Chunk 1: Data Layer Extraction

### Task 1: Extract `get_status_data()` from `show_status()`

**Files:**
- Modify: `runtime/memory_cli.py:125-210`
- Create: `tests/test_mcp_data_layer.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_data_layer.py
"""Tests for data layer functions used by MCP server."""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock

from runtime.bridge.evermemos_client import EverMemosClient


class TestGetStatusData(unittest.TestCase):
    def test_returns_structured_dict(self) -> None:
        from runtime.memory_cli import get_status_data

        client = MagicMock()
        client.list_spaces.return_value = [
            "coding:my-repo--findings",
            "coding:my-repo--agents",
            "coding:my-repo--context",
        ]
        # findings space: 2 unique hashes
        client.fetch_history.side_effect = [
            # findings space
            [
                {"content": EverMemosClient.serialize_finding({"finding_hash": "sha256:aaa", "status": "open", "title": "A"})},
                {"content": EverMemosClient.serialize_finding({"finding_hash": "sha256:bbb", "status": "fixed", "title": "B"})},
            ],
            # agents space
            [
                {"content": EverMemosClient.serialize_agent_score({"agent": "claude", "task_category": "security"})},
            ],
            # context space (for briefing — not used in status data)
        ]
        client.briefing.return_value = "Project uses Python and FastAPI."

        result = get_status_data(client, "my-repo")

        self.assertEqual(result["space_slug"], "my-repo")
        self.assertEqual(result["findings_count"], 2)
        self.assertEqual(result["agent_scores_count"], 1)
        self.assertIn("Python", result["briefing_preview"])

    def test_empty_spaces(self) -> None:
        from runtime.memory_cli import get_status_data

        client = MagicMock()
        client.list_spaces.return_value = []
        client.briefing.return_value = None

        result = get_status_data(client, "empty-repo")

        self.assertEqual(result["findings_count"], 0)
        self.assertEqual(result["agent_scores_count"], 0)
        self.assertEqual(result["briefing_preview"], "")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_mcp_data_layer.py -v`
Expected: ImportError — `get_status_data` not defined.

- [ ] **Step 3: Extract `get_status_data()` from `show_status()`**

In `runtime/memory_cli.py`, add a new function before `show_status()`:

```python
def get_status_data(client: Any, space_slug: str) -> Dict[str, Any]:
    """Return structured status data for a repo's memory spaces.

    Returns dict with: space_slug, findings_count, agent_scores_count, briefing_preview.
    """
    from .bridge.evermemos_client import EverMemosClient

    findings_space = "coding:{slug}--findings".format(slug=space_slug)
    agents_space = "coding:{slug}--agents".format(slug=space_slug)

    available = client.list_spaces()

    # Findings count (deduplicated by finding_hash)
    findings_count = 0
    if findings_space in available:
        try:
            raw = client.fetch_history(space=findings_space, memory_type="episodic_memory", limit=100)
            seen_hashes: set = set()
            for item in raw:
                content = item.get("content", "")
                if not EverMemosClient.is_finding_entry(content):
                    continue
                try:
                    finding = EverMemosClient.deserialize_finding(content)
                    fhash = finding.get("finding_hash", "")
                    if fhash:
                        seen_hashes.add(fhash)
                except (ValueError, Exception):
                    continue
            findings_count = len(seen_hashes)
        except Exception:
            pass

    # Agent scores count (deduplicated by agent+category)
    scores_count = 0
    if agents_space in available:
        try:
            raw = client.fetch_history(space=agents_space, memory_type="episodic_memory", limit=100)
            seen_keys: set = set()
            for item in raw:
                content = item.get("content", "")
                if not EverMemosClient.is_agent_score_entry(content):
                    continue
                try:
                    score_dict = EverMemosClient.deserialize_agent_score(content)
                    key = "{a}:{c}".format(
                        a=score_dict.get("agent", ""),
                        c=score_dict.get("task_category", ""),
                    )
                    seen_keys.add(key)
                except (ValueError, Exception):
                    continue
            scores_count = len(seen_keys)
        except Exception:
            pass

    # Briefing preview
    briefing_preview = ""
    try:
        briefing = client.briefing(space="coding:{slug}--context".format(slug=space_slug))
        if briefing:
            briefing_preview = briefing[:200]
    except Exception:
        pass

    return {
        "space_slug": space_slug,
        "findings_count": findings_count,
        "agent_scores_count": scores_count,
        "briefing_preview": briefing_preview,
    }
```

Then refactor `show_status()` to call `get_status_data()` internally (extract the shared logic, keep the rendering in `show_status()`).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/test_mcp_data_layer.py -v`
Expected: 2 passed.

- [ ] **Step 5: Run full suite to ensure show_status() still works**

Run: `python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add runtime/memory_cli.py tests/test_mcp_data_layer.py
git commit -m "feat: extract get_status_data() from show_status() for MCP data layer"
```

---

## Chunk 2: MCP Server Core + Envelope

### Task 2: Create `runtime/mcp_server.py` with envelope helpers and `mco_doctor` tool

**Files:**
- Create: `runtime/mcp_server.py`
- Create: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_mcp_server.py
"""Tests for MCP server tool handlers."""
from __future__ import annotations

import unittest
from unittest.mock import patch, MagicMock

from runtime.mcp_server import _ok, _err, _sync_doctor


class TestEnvelope(unittest.TestCase):
    def test_ok_envelope(self) -> None:
        result = _ok({"key": "value"})
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["key"], "value")

    def test_err_envelope(self) -> None:
        result = _err("bad_input", "Something went wrong")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "bad_input")
        self.assertEqual(result["error"]["message"], "Something went wrong")


class TestSyncDoctor(unittest.TestCase):
    @patch("runtime.mcp_server._doctor_provider_presence")
    def test_returns_provider_status(self, mock_presence) -> None:
        mock_presence.return_value = {
            "claude": MagicMock(
                provider="claude", detected=True, auth_ok=True,
                version="1.0", binary_path="/usr/bin/claude",
            ),
        }
        result = _sync_doctor("claude")
        self.assertTrue(result["ok"])
        providers = result["data"]["providers"]
        self.assertEqual(len(providers), 1)
        self.assertEqual(providers[0]["name"], "claude")
        self.assertTrue(providers[0]["detected"])

    @patch("runtime.mcp_server._doctor_provider_presence")
    def test_invalid_provider_filtered(self, mock_presence) -> None:
        mock_presence.return_value = {}
        result = _sync_doctor("nonexistent")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["providers"], [])

    def test_empty_providers_checks_all(self) -> None:
        with patch("runtime.mcp_server._doctor_provider_presence") as mock_p:
            mock_p.return_value = {}
            result = _sync_doctor(None)
            self.assertTrue(result["ok"])
            # Called with all SUPPORTED_PROVIDERS
            called_providers = mock_p.call_args[0][0]
            self.assertTrue(len(called_providers) >= 5)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_mcp_server.py -v`
Expected: ImportError.

- [ ] **Step 3: Write `runtime/mcp_server.py` with envelope + doctor**

```python
# runtime/mcp_server.py
"""MCP server mode for MCO — exposes tools over stdio MCP protocol."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any, Dict, List, Optional

# Envelope helpers — all tool responses use this shape.

def _ok(data: Any) -> Dict[str, Any]:
    return {"ok": True, "data": data}


def _err(code: str, message: str) -> Dict[str, Any]:
    return {"ok": False, "error": {"code": code, "message": message}}


# ── Sync helpers (run inside asyncio.to_thread) ──

def _sync_doctor(providers_csv: Optional[str]) -> Dict[str, Any]:
    """Synchronous doctor implementation."""
    from .cli import _doctor_provider_presence, SUPPORTED_PROVIDERS

    if providers_csv:
        providers = [p.strip() for p in providers_csv.split(",") if p.strip()]
        providers = [p for p in providers if p in SUPPORTED_PROVIDERS]
    else:
        providers = list(SUPPORTED_PROVIDERS)

    presence_map = _doctor_provider_presence(providers)

    result_providers = []
    for provider in providers:
        presence = presence_map.get(provider)
        if presence is None:
            continue
        result_providers.append({
            "name": provider,
            "detected": bool(presence.detected),
            "auth_ok": bool(presence.auth_ok),
            "version": presence.version,
            "binary_path": presence.binary_path,
        })

    return _ok({"providers": result_providers})


async def run_server() -> None:
    """Start the MCP stdio server with all MCO tools registered."""
    from mcp.server import Server
    from mcp.server.stdio import stdio_server

    server = Server("mco")

    @server.tool()
    async def mco_doctor(providers: str = "") -> str:
        """Check provider installation and auth status.

        Args:
            providers: Comma-separated provider list (default: all).
        """
        result = await asyncio.to_thread(_sync_doctor, providers or None)
        return json.dumps(result)

    async with stdio_server() as (read, write):
        await server.run(read, write)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_mcp_server.py -v`
Expected: 5 passed.

- [ ] **Step 5: Commit**

```bash
git add runtime/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: create mcp_server module with envelope helpers and mco_doctor tool"
```

---

### Task 3: Add `serve` subcommand to CLI

**Files:**
- Modify: `runtime/cli.py:510-621` (build_parser)
- Modify: `runtime/cli.py:720+` (main dispatch)

- [ ] **Step 1: Add `serve` parser in `build_parser()`**

In `runtime/cli.py`, after the memory subcommand registration (around line 620), before `return parser`:

```python
    subparsers.add_parser(
        "serve",
        help="Start MCP server (stdio protocol)",
        description="Start a stdio MCP server exposing MCO tools for AI agents and MCP clients.",
        formatter_class=_HelpFormatter,
    )
```

- [ ] **Step 2: Add dispatch in `main()`**

In the `main()` function, add handling for `serve` command before the review/run dispatch. Find the section that checks `args.command`:

```python
    if args.command == "serve":
        try:
            from .mcp_server import run_server
        except ImportError:
            print(
                "mco serve requires the mcp package. Install with: pip install mco[memory]",
                file=sys.stderr,
            )
            return 2
        import asyncio
        asyncio.run(run_server())
        return 0
```

- [ ] **Step 3: Test that `mco serve` appears in help**

Run: `python3 -m runtime.cli -h 2>&1 | grep serve`
Expected: Shows `serve` in commands list.

- [ ] **Step 4: Run full test suite**

Run: `python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected: All tests pass.

- [ ] **Step 5: Commit**

```bash
git add runtime/cli.py
git commit -m "feat: add mco serve subcommand for MCP server mode"
```

---

## Chunk 3: Review and Run Tools

### Task 4: Add `_sync_review` and `mco_review` tool

**Files:**
- Modify: `runtime/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_mcp_server.py
from runtime.mcp_server import _sync_review


class TestSyncReview(unittest.TestCase):
    @patch("runtime.mcp_server.run_review")
    def test_returns_findings_envelope(self, mock_run) -> None:
        mock_result = MagicMock()
        mock_result.task_id = "test-123"
        mock_result.decision = "PASS"
        mock_result.terminal_state = "completed"
        mock_result.findings_count = 1
        mock_result.findings = [{"title": "Bug", "severity": "high"}]
        mock_run.return_value = mock_result

        result = _sync_review(
            repo="/tmp/repo",
            prompt="Review for bugs",
            providers="claude,codex",
        )
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["decision"], "PASS")
        self.assertEqual(result["data"]["findings_count"], 1)
        self.assertEqual(len(result["data"]["findings"]), 1)

    def test_invalid_repo(self) -> None:
        result = _sync_review(
            repo="/nonexistent/path/xyz",
            prompt="Review",
            providers="claude",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_repo")

    def test_invalid_providers(self) -> None:
        result = _sync_review(
            repo=".",
            prompt="Review",
            providers="fake_provider",
        )
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "invalid_providers")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_mcp_server.py::TestSyncReview -v`
Expected: ImportError.

- [ ] **Step 3: Implement `_sync_review`**

Add to `runtime/mcp_server.py`:

```python
def _sync_review(
    repo: str,
    prompt: str,
    providers: str,
    target_paths: str = ".",
    diff_mode: Optional[str] = None,
    diff_base: Optional[str] = None,
    memory: bool = False,
    space: Optional[str] = None,
) -> Dict[str, Any]:
    """Synchronous review implementation."""
    from pathlib import Path
    from .review_engine import ReviewRequest, run_review
    from .config import ReviewPolicy

    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        return _err("invalid_repo", f"Repository path does not exist: {repo}")

    from .cli import SUPPORTED_PROVIDERS
    provider_list = [p.strip() for p in providers.split(",") if p.strip()]
    valid_providers = [p for p in provider_list if p in SUPPORTED_PROVIDERS]
    if not valid_providers:
        return _err("invalid_providers", f"No valid providers in: {providers}")

    # Normalize diff_base → diff_mode
    effective_diff_mode = diff_mode
    if diff_base and not effective_diff_mode:
        effective_diff_mode = "branch"

    try:
        req = ReviewRequest(
            repo_root=str(repo_path),
            prompt=prompt,
            providers=valid_providers,
            artifact_base=str(repo_path / "reports" / "review"),
            policy=ReviewPolicy(),
            target_paths=[p.strip() for p in target_paths.split(",") if p.strip()],
            memory_enabled=memory,
            memory_space=space or None,
            diff_mode=effective_diff_mode,
            diff_base=diff_base or None,
        )
        result = run_review(req, review_mode=True, write_artifacts=False)
    except Exception as exc:
        return _err("execution_error", str(exc))

    return _ok({
        "task_id": result.task_id,
        "decision": result.decision,
        "terminal_state": result.terminal_state,
        "findings_count": result.findings_count,
        "findings": result.findings,
    })
```

Register the async tool in `run_server()`:

```python
    @server.tool()
    async def mco_review(
        repo: str,
        prompt: str,
        providers: str,
        target_paths: str = ".",
        diff_mode: str = "",
        diff_base: str = "",
        memory: bool = False,
        space: str = "",
    ) -> str:
        """Run structured multi-agent code review.

        Args:
            repo: Path to repository root.
            prompt: Review instructions.
            providers: Comma-separated provider list (e.g. "claude,codex,gemini").
            target_paths: Comma-separated scope paths (default: ".").
            diff_mode: "branch", "staged", or "unstaged" (default: disabled).
            diff_base: Git ref for branch diff (implies diff_mode="branch").
            memory: Enable evermemos memory layer.
            space: Memory space slug (auto-inferred if empty).
        """
        result = await asyncio.to_thread(
            _sync_review, repo, prompt, providers, target_paths,
            diff_mode or None, diff_base or None, memory, space or None,
        )
        return json.dumps(result)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_mcp_server.py -v`
Expected: 8 passed.

- [ ] **Step 5: Commit**

```bash
git add runtime/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add mco_review tool to MCP server"
```

---

### Task 5: Add `_sync_run` and `mco_run` tool

**Files:**
- Modify: `runtime/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing test**

```python
# Append to tests/test_mcp_server.py
from runtime.mcp_server import _sync_run


class TestSyncRun(unittest.TestCase):
    @patch("runtime.mcp_server.run_review")
    def test_returns_final_text_only(self, mock_run) -> None:
        mock_result = MagicMock()
        mock_result.task_id = "run-123"
        mock_result.decision = "PASS"
        mock_result.terminal_state = "completed"
        mock_result.provider_results = {
            "claude": {"success": True, "final_text": "Architecture summary...", "output_text": "Very long..."},
        }
        mock_run.return_value = mock_result

        result = _sync_run(repo=".", prompt="Summarize", providers="claude")
        self.assertTrue(result["ok"])
        data = result["data"]
        self.assertEqual(data["task_id"], "run-123")
        # Only final_text, not output_text
        self.assertIn("final_text", data["provider_results"]["claude"])
        self.assertNotIn("output_text", data["provider_results"]["claude"])
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_mcp_server.py::TestSyncRun -v`
Expected: ImportError.

- [ ] **Step 3: Implement `_sync_run`**

Add to `runtime/mcp_server.py`:

```python
def _sync_run(
    repo: str,
    prompt: str,
    providers: str,
    target_paths: str = ".",
) -> Dict[str, Any]:
    """Synchronous run implementation."""
    from pathlib import Path
    from .review_engine import ReviewRequest, run_review
    from .config import ReviewPolicy

    repo_path = Path(repo).resolve()
    if not repo_path.is_dir():
        return _err("invalid_repo", f"Repository path does not exist: {repo}")

    from .cli import SUPPORTED_PROVIDERS
    provider_list = [p.strip() for p in providers.split(",") if p.strip()]
    valid_providers = [p for p in provider_list if p in SUPPORTED_PROVIDERS]
    if not valid_providers:
        return _err("invalid_providers", f"No valid providers in: {providers}")

    try:
        req = ReviewRequest(
            repo_root=str(repo_path),
            prompt=prompt,
            providers=valid_providers,
            artifact_base=str(repo_path / "reports" / "review"),
            policy=ReviewPolicy(),
            target_paths=[p.strip() for p in target_paths.split(",") if p.strip()],
        )
        result = run_review(req, review_mode=False, write_artifacts=False)
    except Exception as exc:
        return _err("execution_error", str(exc))

    # Strip output_text from provider_results (too large for MCP)
    slim_results: Dict[str, Any] = {}
    for provider, pr in result.provider_results.items():
        slim_results[provider] = {
            "success": pr.get("success"),
            "final_text": pr.get("final_text", ""),
        }

    return _ok({
        "task_id": result.task_id,
        "decision": result.decision,
        "terminal_state": result.terminal_state,
        "provider_results": slim_results,
    })
```

Register async tool in `run_server()`:

```python
    @server.tool()
    async def mco_run(
        repo: str,
        prompt: str,
        providers: str,
        target_paths: str = ".",
    ) -> str:
        """General-purpose multi-agent task execution.

        Args:
            repo: Path to repository root.
            prompt: Task instructions.
            providers: Comma-separated provider list.
            target_paths: Comma-separated scope paths (default: ".").
        """
        result = await asyncio.to_thread(
            _sync_run, repo, prompt, providers, target_paths,
        )
        return json.dumps(result)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_mcp_server.py -v`
Expected: 9 passed.

- [ ] **Step 5: Commit**

```bash
git add runtime/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add mco_run tool to MCP server"
```

---

## Chunk 4: Memory Tools

### Task 6: Add `_sync_findings_list` and `_sync_memory_status` tools

**Files:**
- Modify: `runtime/mcp_server.py`
- Modify: `tests/test_mcp_server.py`

- [ ] **Step 1: Write the failing tests**

```python
# Append to tests/test_mcp_server.py
from runtime.mcp_server import _sync_findings_list, _sync_memory_status


class TestSyncFindingsList(unittest.TestCase):
    @patch("runtime.mcp_server.EverMemosClient")
    @patch("runtime.mcp_server.infer_space_slug", return_value="my-repo")
    def test_returns_findings(self, mock_slug, mock_client_cls) -> None:
        mock_client = MagicMock()
        mock_client_cls.return_value = mock_client
        mock_client.fetch_history.return_value = []
        with patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):
            result = _sync_findings_list(repo=".")
        self.assertTrue(result["ok"])
        self.assertIsInstance(result["data"], list)

    def test_missing_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            # Ensure EVERMEMOS_API_KEY is not set
            os.environ.pop("EVERMEMOS_API_KEY", None)
            result = _sync_findings_list(repo=".")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "missing_api_key")


class TestSyncMemoryStatus(unittest.TestCase):
    @patch("runtime.mcp_server.get_status_data")
    @patch("runtime.mcp_server.EverMemosClient")
    @patch("runtime.mcp_server.infer_space_slug", return_value="my-repo")
    def test_returns_status(self, mock_slug, mock_client_cls, mock_status) -> None:
        mock_status.return_value = {
            "space_slug": "my-repo",
            "findings_count": 5,
            "agent_scores_count": 3,
            "briefing_preview": "Hello",
        }
        with patch.dict(os.environ, {"EVERMEMOS_API_KEY": "test-key"}):
            result = _sync_memory_status(repo=".")
        self.assertTrue(result["ok"])
        self.assertEqual(result["data"]["findings_count"], 5)

    def test_missing_api_key(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            os.environ.pop("EVERMEMOS_API_KEY", None)
            result = _sync_memory_status(repo=".")
        self.assertFalse(result["ok"])
        self.assertEqual(result["error"]["code"], "missing_api_key")
```

Add `import os` to test file imports.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/test_mcp_server.py::TestSyncFindingsList tests/test_mcp_server.py::TestSyncMemoryStatus -v`
Expected: ImportError.

- [ ] **Step 3: Implement memory tool helpers**

Add to `runtime/mcp_server.py`:

```python
def _sync_findings_list(
    repo: str = ".",
    space: Optional[str] = None,
    status: Optional[str] = None,
) -> Dict[str, Any]:
    """Synchronous findings list implementation."""
    api_key = os.environ.get("EVERMEMOS_API_KEY", "")
    if not api_key:
        return _err("missing_api_key", "EVERMEMOS_API_KEY environment variable is required")

    from pathlib import Path
    from .bridge.evermemos_client import EverMemosClient
    from .bridge.space import infer_space_slug
    from .findings_cli import list_findings

    repo_path = str(Path(repo).resolve())
    slug = infer_space_slug(repo_path, explicit=space or None)
    findings_space = f"coding:{slug}--findings"

    try:
        client = EverMemosClient(api_key=api_key)
        findings = list_findings(client, findings_space, status_filter=status or None)
    except Exception as exc:
        return _err("execution_error", str(exc))

    return _ok(findings)


def _sync_memory_status(
    repo: str = ".",
    space: Optional[str] = None,
) -> Dict[str, Any]:
    """Synchronous memory status implementation."""
    api_key = os.environ.get("EVERMEMOS_API_KEY", "")
    if not api_key:
        return _err("missing_api_key", "EVERMEMOS_API_KEY environment variable is required")

    from pathlib import Path
    from .bridge.evermemos_client import EverMemosClient
    from .bridge.space import infer_space_slug
    from .memory_cli import get_status_data

    repo_path = str(Path(repo).resolve())
    slug = infer_space_slug(repo_path, explicit=space or None)

    try:
        client = EverMemosClient(api_key=api_key)
        data = get_status_data(client, slug)
    except Exception as exc:
        return _err("execution_error", str(exc))

    return _ok(data)
```

Register async tools in `run_server()`:

```python
    @server.tool()
    async def mco_findings_list(
        repo: str = ".",
        space: str = "",
        status: str = "",
    ) -> str:
        """List persisted findings from evermemos memory.

        Args:
            repo: Repository root path (for space inference).
            space: Space slug override (auto-inferred if empty).
            status: Filter by status: "open", "fixed", "rejected", etc.
        """
        result = await asyncio.to_thread(
            _sync_findings_list, repo, space or None, status or None,
        )
        return json.dumps(result)

    @server.tool()
    async def mco_memory_status(
        repo: str = ".",
        space: str = "",
    ) -> str:
        """Show memory space overview (findings count, agent scores, briefing).

        Args:
            repo: Repository root path (for space inference).
            space: Space slug override (auto-inferred if empty).
        """
        result = await asyncio.to_thread(
            _sync_memory_status, repo, space or None,
        )
        return json.dumps(result)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/test_mcp_server.py -v`
Expected: 13 passed.

- [ ] **Step 5: Run full test suite**

Run: `python3 -m unittest discover -s tests -p "test_*.py" 2>&1 | tail -3`
Expected: All tests pass.

- [ ] **Step 6: Commit**

```bash
git add runtime/mcp_server.py tests/test_mcp_server.py
git commit -m "feat: add mco_findings_list and mco_memory_status tools to MCP server"
```

---

## Chunk 5: README and Final Cleanup

### Task 7: Update README

**Files:**
- Modify: `README.md`

- [ ] **Step 1: Add MCP Server section**

After the "Cross-Session Memory" section and before "License", add:

```markdown
## MCP Server Mode

MCO can run as an MCP server, allowing AI agents and MCP-compatible clients to call MCO tools programmatically.

```bash
pip install mco[memory]  # includes mcp dependency
```

Configure in your MCP client:

```json
{
  "mcpServers": {
    "mco": {
      "command": "mco",
      "args": ["serve"]
    }
  }
}
```

Available tools: `mco_review`, `mco_run`, `mco_doctor`, `mco_findings_list`, `mco_memory_status`.
```

- [ ] **Step 2: Commit**

```bash
git add README.md
git commit -m "docs: add MCP server mode section to README"
```
