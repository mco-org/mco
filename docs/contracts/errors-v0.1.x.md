# Error and Preview Contract (`v0.1.x`)

This document freezes the machine-readable failure and preview surface for `mco run` / `mco review` in `v0.1.x`.

## Exit Codes

| Exit | Meaning |
|---|---|
| `0` | Completed successfully, or `--dry-run` preview rendered successfully. |
| `2` | Input, configuration, provider, or runtime failure. |
| `3` | Review completed but was inconclusive. |

## Top-Level Error Envelope

When `--json` is requested and command parsing, input validation, or configuration fails, stdout contains one JSON object and stderr remains empty:

```json
{
  "ok": false,
  "error": {
    "category": "input|configuration|runtime",
    "subtype": "parse_error|input_error|invalid_providers|config_error|invalid_config|runtime_error",
    "message": "...",
    "hint": "...",
    "provider": null,
    "retryable": false,
    "exit_code": 2
  }
}
```

The field order above is frozen for `v0.1.x`. `provider` is populated when a top-level failure belongs to one provider. Provider execution failures that occur after dispatch remain in the normal result payload under `provider_results`.

## Streaming Error Events

Streaming mode emits JSONL events with:

```json
{"type":"error","code":"invalid_config","message":"...","error":{"category":"configuration","subtype":"invalid_config","message":"...","hint":"...","provider":null,"retryable":false,"exit_code":2},"timestamp":"..."}
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

Provider failures classified after execution use `final_error`, including `retryable_timeout`, `retryable_rate_limit`, `retryable_transient_network`, `non_retryable_auth`, `non_retryable_invalid_input`, `non_retryable_unsupported_capability`, and `normalization_error`. Timeout details remain in `cancel_reason`; parse/normalization details remain in `parse_reason`.

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

Risk metadata is normally descriptive. Strict ACP execution additionally fails closed when its effective risk remains `unknown`.

| Level | Meaning |
|---|---|
| `read_only` | Default adapter command is intended to avoid write/shell tools. |
| `workspace_write` | Default adapter command may write inside the workspace. |
| `elevated` | Default adapter command may use broader local capabilities. |
| `approval_bypass` | Default adapter command or provider semantics bypass interactive approvals. |
| `unknown` | Custom or unclassified provider. Inspect its command before execution. |

`mco doctor --json`, MCP doctor, `mco agent list --json`, `mco agent check --json`, and `--dry-run --json` expose risk metadata for orchestrating agents. Discovery surfaces report default shim risk. Dry-run also reports `default_risk` and uses `risk` for the effective risk after supported permission overrides are resolved. ACP transport is classified as `unknown` unless a supported explicit permission override makes its launch policy auditable; strict previews then report `risk_classification_unknown` instead of assuming the shim default.

## Gates

- `tests/test_cli_json_contract.py` freezes top-level error envelopes, provider failure records, and exit codes.
- `tests/test_error_taxonomy.py` freezes retryable, auth, input, capability, and normalization classifications.
- `tests/test_review_engine.py` covers provider readiness, policy enforcement, timeout, cancellation, and parse results.
