# MCP Server Mode — Design Spec

## Overview

Add `mco serve` subcommand that starts a stdio MCP server, exposing 5 tools for AI agents and MCP-compatible clients to call MCO programmatically.

## CLI Entry Point

```bash
mco serve    # starts stdio MCP server
```

In MCP client configuration:
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

No additional CLI flags for `serve`. All parameters come through tool call arguments.

If `mcp` package is not installed, print `"mco serve requires the mcp package. Install with: pip install mco[memory]"` and exit 2.

## Tools

### `mco_review`

Run structured multi-agent code review.

**Input:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | yes | - | Path to repository root |
| `prompt` | string | yes | - | Review instructions |
| `providers` | string | yes | - | Comma-separated provider list (e.g. "claude,codex,gemini") |
| `target_paths` | string | no | "." | Comma-separated scope paths |
| `diff_mode` | string | no | null | "branch", "staged", or "unstaged" |
| `diff_base` | string | no | null | Git ref for branch diff (implies diff_mode="branch") |
| `memory` | boolean | no | false | Enable evermemos memory layer |
| `space` | string | no | null | Memory space slug (auto-inferred if omitted) |

**Output:** JSON object:
```json
{
  "task_id": "abc123",
  "decision": "PASS",
  "terminal_state": "completed",
  "findings_count": 3,
  "findings": [
    {
      "title": "SQL injection",
      "severity": "high",
      "category": "security",
      "evidence": {"file": "auth.py", "line": 42, "snippet": "..."},
      "confidence": 0.85,
      "recommendation": "Use parameterized queries",
      "detected_by": ["claude", "gemini"],
      "diff_scope": "in_diff"
    }
  ]
}
```

### `mco_run`

General-purpose multi-agent task execution (no findings schema).

**Input:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | yes | - | Path to repository root |
| `prompt` | string | yes | - | Task instructions |
| `providers` | string | yes | - | Comma-separated provider list |
| `target_paths` | string | no | "." | Comma-separated scope paths |

**Output:** JSON object:
```json
{
  "task_id": "abc123",
  "decision": "PASS",
  "terminal_state": "completed",
  "provider_results": {
    "claude": {"success": true, "final_text": "..."},
    "codex": {"success": true, "final_text": "..."}
  }
}
```

`final_text` only (not full `output_text`) to keep response size reasonable.

### `mco_doctor`

Check provider installation and auth status.

**Input:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `providers` | string | no | all | Comma-separated provider list to check |

**Output:** JSON object:
```json
{
  "providers": [
    {
      "name": "claude",
      "detected": true,
      "auth_ok": true,
      "version": "1.2.3",
      "binary_path": "/usr/local/bin/claude"
    }
  ]
}
```

### `mco_findings_list`

List persisted findings from evermemos memory.

**Input:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | no | "." | Repository root (for space inference) |
| `space` | string | no | null | Space slug (auto-inferred if omitted) |
| `status` | string | no | null | Filter: "open", "fixed", "rejected", etc. |

**Output:** JSON array of finding objects with finding_hash, status, severity, title, file, etc.

Requires `EVERMEMOS_API_KEY` environment variable. Returns error text (not crash) if missing.

### `mco_memory_status`

Show memory space overview.

**Input:**

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `repo` | string | no | "." | Repository root (for space inference) |
| `space` | string | no | null | Space slug (auto-inferred if omitted) |

**Output:** JSON object:
```json
{
  "space_slug": "my-repo",
  "findings_count": 12,
  "agent_scores_count": 5,
  "briefing_preview": "First 200 chars of briefing..."
}
```

Requires `EVERMEMOS_API_KEY` environment variable.

## async/sync Architecture

**Problem:** MCP server runs an async event loop, but MCO's core is synchronous:
- `run_review()` blocks for minutes with polling loops
- `EverMemosClient._call_tool_sync()` calls `asyncio.run()`, which crashes inside an existing event loop

**Solution:** All tool handlers use `asyncio.to_thread()` to run synchronous MCO functions in a worker thread. This cleanly separates the async MCP protocol layer from the sync MCO core.

```python
@server.tool()
async def mco_review(repo: str, prompt: str, providers: str, ...):
    result = await asyncio.to_thread(_sync_review, repo, prompt, providers, ...)
    return result
```

The `_sync_*` helper functions are plain synchronous Python that call `run_review()`, `EverMemosClient`, etc. unchanged.

## Data Layer for Memory Tools

Current `memory_cli.py` functions (`show_status`, `show_agent_stats`) return rendered text strings. MCP tools need structured data.

**New functions in `runtime/memory_cli.py`:**

```python
def get_status_data(client, space_slug) -> Dict[str, Any]:
    """Return structured status data (not rendered text)."""
    return {
        "space_slug": space_slug,
        "findings_count": ...,
        "agent_scores_count": ...,
        "briefing_preview": ...,
    }

def get_findings_data(client, space, status_filter=None) -> List[Dict[str, Any]]:
    """Return structured findings list (not rendered table)."""
    return [...]
```

Existing `show_status()` and `render_findings_table()` are refactored to call these data functions internally, preserving CLI behavior.

## Response Envelope

All tool responses use a uniform envelope so MCP clients can reliably distinguish success from failure without type-sniffing.

**Success:**
```json
{"ok": true, "data": { ... }}
```

**Failure:**
```json
{"ok": false, "error": {"code": "missing_api_key", "message": "EVERMEMOS_API_KEY environment variable is required"}}
```

`data` contains the tool-specific payload (object or array). `error.code` is a machine-readable slug; `error.message` is human-readable.

### Error Codes

| Code | When |
|------|------|
| `invalid_repo` | repo path does not exist or is not a git repo |
| `invalid_providers` | no valid provider names in providers string |
| `missing_api_key` | EVERMEMOS_API_KEY not set (findings/memory tools) |
| `execution_error` | run_review() raised an unexpected exception |
| `mcp_not_installed` | mcp package missing (only at `mco serve` startup, not tool-level) |

### Startup vs Tool Errors

- `mcp` not installed → `mco serve` prints to stderr and exits 2 (before server starts)
- All other errors → returned as `{"ok": false, ...}` envelope inside the tool response
- Provider timeout during review → `{"ok": true, ...}` with partial result (same as CLI behavior — partial is not an error)

## What Is NOT in Scope (v1)

- `findings confirm` — write operation, risk too high for v1
- `memory agent-stats` / `memory priors` — low frequency, v2
- SSE transport — stdio is sufficient for local use
- Authentication/authorization — stdio is local-only by design
- Streaming progress events — v2 (ties into Structured Streaming feature)

## Files to Create/Modify

| File | Action |
|------|--------|
| `runtime/mcp_server.py` | Create — MCP server with 5 tools |
| `runtime/cli.py` | Modify — add `serve` subcommand |
| `runtime/memory_cli.py` | Modify — add `get_status_data()`, `get_findings_data()` |
| `runtime/findings_cli.py` | Modify — refactor `list_findings()` to use data layer |
| `tests/test_mcp_server.py` | Create — tool function unit tests |
| `tests/test_mcp_data_layer.py` | Create — data layer function tests |
