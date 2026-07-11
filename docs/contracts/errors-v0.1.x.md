# Error and preview contract (`v0.1.x` compatibility label)

This document describes input/configuration failures and dry-run behavior for the invocation-native `mco run` / `mco review` CLI.

## Exit codes

| Exit | Meaning |
|---:|---|
| `0` | All invocations succeeded, or a dry-run preview completed |
| `1` | The task is partial: at least one invocation succeeded and another did not |
| `2` | Input, configuration, provider, or runtime failure; no invocation succeeded |

## Top-level error envelope

When `--json` is requested and validation fails before a normal task result exists, stdout contains one object:

```json
{
  "ok": false,
  "error": {
    "category": "input|configuration|runtime",
    "subtype": "parse_error|input_error|provider_selection_required|invalid_providers|config_error|invalid_config|runtime_error",
    "message": "...",
    "hint": "...",
    "provider": null,
    "retryable": false,
    "exit_code": 2
  }
}
```

Provider processes do not start for configuration errors. Provider execution errors are retained in the normal `outputs` array, alongside any successful answers. Diagnostics are written to stderr rather than mixed into JSON stdout.

## Removed surfaces and migration errors

These commands and flags are removed. They return migration guidance rather than being silently accepted; they do not select a legacy runtime.

| Removed surface | Invocation-native replacement |
|---|---|
| `mco findings` | Use `mco run` / `mco review` output records or persistent Markdown artifacts. |
| `--format`, `--strict-contract` | Use raw text, `--json`, or `--stream jsonl`. |
| `--memory`, `--space` | Persist raw answers with `--result-mode artifact`, then pass them through a file-backed stage when needed. |
| `--diff`, `--staged`, `--unstaged`, `--diff-base` | Put scope in `--target-paths` and the raw prompt. |

## JSONL errors

In streaming mode, error events use the same operational shape and keep diagnostics on stderr. A successful invocation can still be followed by an error event for another invocation; the final `task_finished` event reports `complete`, `partial`, or `failed`.

## Dry run

`--dry-run --json` resolves providers, invocations, permissions, model routing, context policy, risk, command templates, result mode, and stage flags without starting Agent processes. It exits `0` when the preview itself rendered successfully, even when a strict policy preview reports that execution would fail.
