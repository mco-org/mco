# CLI JSON Contract (`v0.1.x` compatibility label)

This document describes the raw operational envelope emitted by `mco run --json` and `mco review --json` in the invocation-native runtime. The payload is deliberately not a findings or semantic decision contract.

## Final envelope

```json
{
  "stage": "run",
  "task_id": "task-123",
  "status": "complete",
  "outputs": [
    {
      "stage": "run",
      "invocation_id": "fast",
      "provider": "pi",
      "model": "model-a",
      "status": "success",
      "output": "raw Agent answer",
      "error": null,
      "exit_code": 0,
      "deltas": ["raw ", "Agent answer"],
      "transport_status": "succeeded",
      "usage": null,
      "artifact_path": null
    }
  ],
  "exit_code": 0,
  "artifact_root": null
}
```

The `outputs` array preserves declaration order. The JSON CLI envelope omits provider `stderr` from stdout; diagnostics remain available on stderr. `artifact_root` is `null` for temporary execution and is the persistent task directory for `artifact` or `both` result modes.

## Status and exit code

| Task status | Exit code | Meaning |
|---|---:|---|
| `complete` | `0` | Every invocation succeeded |
| `partial` | `1` | At least one invocation succeeded and at least one did not |
| `failed` | `2` | No invocation succeeded, or input/configuration failed |

Invocation status is operational: `success`, `failed`, `timeout`, or `cancelled`. A task never invents a semantic conclusion from an Agent answer.

## Invocation selection

`--providers a,b` expands to one default/configured model invocation per provider. Repeated `--agent [alias=]provider:model` declarations create explicit invocation records. Invalid aliases, duplicate invocations, unknown providers, and confirmed invalid configuration fail before dispatch.

## JSONL stream

`--stream jsonl` emits events with the same invocation identifiers. For any invocation, concatenate its `output_delta` event `delta` fields in order to reconstruct the formal answer. `invocation_started`, `invocation_finished`, and `task_finished` carry operational metadata only.

## Stages and artifacts

Chain, debate, and synthesis events include `stage`. Persistent artifacts use:

```text
<artifact-base>/<task-id>/
  result.md
  run.json
  stages/<stage>/invocations/<invocation-id>.md
  stages/<stage>/context/manifest.json
  stages/<stage>/result.md
  stages/<stage>/run.json
```

Earlier stage answers are passed by file path and manifest. Their bodies are not silently summarized or truncated.

## Compatibility

This is a breaking replacement for the former structured findings payload. Removed fields include findings counts, schema validity, parse counters, decisions, consensus, and dropped-finding counts. Callers must consume raw `output` plus operational status, or use the file-backed artifacts.
