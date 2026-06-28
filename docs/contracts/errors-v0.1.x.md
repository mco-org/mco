# Error and Preview Contract (`v0.1.x`)

This document freezes the machine-readable failure and preview surface for `mco run` / `mco review` in `v0.1.x`.

## Exit Codes

| Exit | Meaning |
|---|---|
| `0` | Completed successfully, or `--dry-run` preview rendered successfully. |
| `2` | Input, configuration, provider, or runtime failure. |
| `3` | Review completed but was inconclusive. |

## Top-Level Error Events

Streaming mode emits JSONL events with:

```json
{"type":"error","code":"invalid_config","message":"...","timestamp":"..."}
```

Known `code` values include:

- `parse_error`
- `config_error`
- `invalid_config`
- `invalid_providers`
- `input_error`

## Provider Result Failure Reasons

Provider-level failures appear in `provider_results[provider].reason`:

| Reason | Meaning |
|---|---|
| `adapter_not_implemented` | Selected provider has no adapter. |
| `provider_unavailable` | Binary/auth probe failed. |
| `permission_enforcement_failed` | Strict permission policy requested unsupported keys. |
| `model_selection_failed` | Strict model policy requested unsupported keys. |
| `context_policy_enforcement_failed` | Strict context policy requested unsupported or incompatible keys. |
| `executor_timeout` | Provider executor did not finish before the global executor wait ended. |
| `internal_error` | Unexpected orchestrator-side exception. |

Policy failures include audit fields such as `requested_permissions`, `unknown_permission_keys`, `requested_model`, `unknown_model_keys`, `requested_context`, `unknown_context_keys`, `incompatible_context_keys`, and `dropped_context_keys` when relevant.

## Dry Run Preview

`--dry-run --json` returns without starting agent processes:

```json
{
  "dry_run": true,
  "would_execute": false,
  "providers_detail": {
    "pi": {
      "risk": {"level": "read_only", "reason": "..."},
      "policy": {"would_fail_strict": false, "failure_reason": ""},
      "command_template": ["pi", "-p", "--mode", "json", "...", "<prompt>"]
    }
  }
}
```

Provider policy preview uses the same permission, model, and context validation path as execution. If a selected provider would fail under `enforcement_mode=strict`, `policy.would_fail_strict=true` and `policy.failure_reason` is set, but the dry run itself still exits `0` because no provider was executed.

## Provider Risk Levels

Risk metadata is descriptive, not an enforcement mechanism.

| Level | Meaning |
|---|---|
| `read_only` | Default adapter command is intended to avoid write/shell tools. |
| `workspace_write` | Default adapter command may write inside the workspace. |
| `elevated` | Default adapter command may use broader local capabilities. |
| `approval_bypass` | Default adapter command or provider semantics bypass interactive approvals. |
| `unknown` | Custom or unclassified provider. Inspect its command before execution. |

`mco doctor --json`, `mco agent list --json`, `mco agent check --json`, and `--dry-run --json` expose risk metadata for orchestrating agents.
