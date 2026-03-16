# Structured Streaming — Design Spec

## Overview

Add `--stream jsonl` flag to `mco review` / `mco run` that outputs real-time JSONL events to stdout as providers execute.

## CLI

```bash
mco review --stream jsonl --providers claude,codex,gemini
```

### Mutual exclusion

`--stream jsonl` is mutually exclusive with:
- `--json`
- `--format report|markdown-pr|sarif`

If combined, exit 2 with error message.

### stdout protocol

When `--stream jsonl` is enabled, stdout becomes a single-protocol JSONL event stream. Each line is one JSON object. No human-readable text, no mixed formats.

### stderr in stream mode

Stream mode suppresses all non-fatal stderr output. Information that would normally go to stderr (empty diff message, missing dependency hints) is emitted as events instead. stderr is reserved exclusively for uncaught exceptions and fatal crashes.

## Event Types

9 event types. Every event has `type` and `timestamp` fields.

### `run_started`

```json
{"type": "run_started", "timestamp": "2026-03-16T12:00:00Z", "task_id": "abc123", "providers": ["claude", "codex", "gemini"], "review_mode": true}
```

Emitted once after scope normalization and diff computation, before provider dispatch.

### `provider_started`

```json
{"type": "provider_started", "timestamp": "...", "provider": "claude"}
```

Emitted when a provider subprocess is spawned.

### `provider_progress`

```json
{"type": "provider_progress", "timestamp": "...", "provider": "claude", "total_output_bytes": 4096}
```

Emitted when the polling loop detects output growth. `total_output_bytes` is the cumulative byte count of the provider's stdout, not a delta. Frequency is naturally throttled by `poll_interval_seconds` (default 1s).

### `provider_finished`

```json
{"type": "provider_finished", "timestamp": "...", "provider": "claude", "success": true, "findings_count": 3, "wall_clock_seconds": 45.2}
```

Emitted when provider execution completes (success or failure).

### `provider_error`

```json
{"type": "provider_error", "timestamp": "...", "provider": "codex", "error_kind": "timeout", "message": "No output progress for 900s"}
```

Emitted when a provider fails due to timeout, crash, or normalization error. This is a provider-level error, not a fatal run error. Other providers continue.

### `synthesis_started`

```json
{"type": "synthesis_started", "timestamp": "...", "provider": "claude"}
```

Emitted when `--synthesize` synthesis pass begins. Omitted if synthesis is not enabled.

### `synthesis_finished`

```json
{"type": "synthesis_finished", "timestamp": "...", "success": true}
```

### `error`

```json
{"type": "error", "timestamp": "...", "code": "execution_error", "message": "..."}
```

Global run-level error. Emitted for fatal errors that prevent producing a result (e.g., no valid providers, repo path invalid). When an `error` event is emitted, there is no subsequent `result` event.

### `result`

```json
{
  "type": "result",
  "timestamp": "...",
  "task_id": "abc123",
  "decision": "PASS",
  "terminal_state": "completed",
  "findings_count": 5,
  "provider_results": {"claude": {"success": true}, "codex": {"success": true}},
  "findings": [...]
}
```

Always the last event in a successful run. This is a **stream-specific final event** — its structure is defined by this spec, not by the existing `--json` payload. It includes `findings` (which `--json` does not), and omits fields like `parse_success_count` that are only relevant for the CLI summary.

**`result` fields:**
- `type`, `timestamp` — standard
- `task_id`, `decision`, `terminal_state` — from ReviewResult
- `findings_count` — integer
- `findings` — full findings array with diff_scope tags if applicable
- `provider_results` — slim per-provider summary: `{provider: {success, findings_count, wall_clock_seconds}}`
- `token_usage_summary` — included only if `--include-token-usage` was set
- `synthesis` — included only if `--synthesize` was set

## Thread Safety

Provider execution uses `ThreadPoolExecutor` (review_engine.py:930). Multiple providers emit events concurrently.

**v1 strategy: `threading.Lock` around stdout writes.**

The CLI-layer emitter wraps `print(json.dumps(event), flush=True)` in a lock. This is sufficient for v1 — events are small JSON objects, serialization is fast, lock contention is negligible.

```python
import threading

_lock = threading.Lock()

def _emit(event: dict) -> None:
    line = json.dumps(event, ensure_ascii=True)
    with _lock:
        print(line, flush=True)
```

The `stream_callback` on ReviewRequest is called from any thread. The callback implementation is responsible for thread safety.

## Implementation

### ReviewRequest change

```python
@dataclass(frozen=True)
class ReviewRequest:
    # ... existing fields ...
    stream_callback: Optional[Any] = None  # Callable[[Dict], None] or None
```

`Any` type to avoid import complexity. When not None, `run_review()` calls it at event injection points. When None, no events are emitted (existing behavior unchanged).

### Event injection points in `run_review()`

| Event | Location | Notes |
|-------|----------|-------|
| `run_started` | After scope/diff normalization, before provider dispatch | Includes task_id, providers, review_mode |
| `provider_started` | `_run_provider()` entry | Before subprocess spawn |
| `provider_progress` | Polling loop, on byte growth detection | `total_output_bytes` from cumulative counter |
| `provider_finished` | `_run_provider()` return | success, findings_count, wall_clock |
| `provider_error` | `_run_provider()` on exception/timeout | error_kind, message |
| `synthesis_started` | Before synthesis provider call | Only if --synthesize |
| `synthesis_finished` | After synthesis returns | success |
| `error` | `run_review()` catch block for fatal errors | code, message |
| `result` | `run_review()` final return | Full payload |

### Stderr suppression in stream mode

When `stream_callback` is set, existing `print(..., file=sys.stderr)` calls in `run_review()` are suppressed. Specifically:
- Empty diff message (review_engine.py:844) → becomes part of normal no-op flow, no event needed (result event with findings_count=0 is sufficient)
- Memory dependency warning (review_engine.py:97) → emitted as `error` event if it would prevent memory from loading

### CLI changes

Add to argument group:

```python
output.add_argument(
    "--stream",
    choices=["jsonl"],
    default=None,
    help="Output JSONL event stream to stdout (mutually exclusive with --json and --format)",
)
```

Validation in `main()`:

```python
if args.stream and args.json:
    print("--stream and --json are mutually exclusive", file=sys.stderr)
    return 2
if args.stream and args.format not in ("report", None):
    print("--stream and --format are mutually exclusive", file=sys.stderr)
    return 2
```

### Exit code

Same as non-stream mode: 0 for PASS, 2 for FAIL/error, 3 for INCONCLUSIVE. The `result` event is emitted before the exit.

## What Is NOT in Scope (v1)

- TUI display — v2
- `--stream sse` — v2
- Streaming findings as they're parsed (per-provider, before merge) — v2
- MCP server streaming notifications — v2

## Files to Create/Modify

| File | Action |
|------|--------|
| `runtime/review_engine.py` | Modify — add `stream_callback` to ReviewRequest, inject events at 9 points |
| `runtime/cli.py` | Modify — add `--stream` flag, mutual exclusion, create thread-safe emitter |
| `tests/test_streaming.py` | Create — event sequence tests, mutex tests, callback injection tests |
