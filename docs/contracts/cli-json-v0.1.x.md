# CLI JSON Contract (`v0.1.x`)

This document freezes the machine-readable payload contract returned by:

- `mco review --json`
- `mco run --json`

## Contract Version

- Scope: `v0.1.x`
- Compatibility rule: additive-only changes are allowed in `v0.1.x`; removal/rename/type change requires a new contract version.

## Payload Shape

Top-level JSON object with required fields:

```json
{
  "command": "review|run",
  "task_id": "string",
  "artifact_root": "string",
  "decision": "string",
  "terminal_state": "string",
  "provider_success_count": 0,
  "provider_failure_count": 0,
  "findings_count": 0,
  "parse_success_count": 0,
  "parse_failure_count": 0,
  "schema_valid_count": 0,
  "dropped_findings_count": 0
}
```

## Semantics

- `command`:
  - `review` for review-specialized flow.
  - `run` for generalized execution flow.
- `findings_count` is retained canonical findings count.
- `parse_success_count` / `parse_failure_count` are review parsing health counters.
- Failures before a normal result is available use the envelope frozen in `docs/contracts/errors-v0.1.x.md`.

## Exit Code Notes

- `mco run`:
  - returns non-zero only when `decision == FAIL`.
- `mco review`:
  - returns non-zero for `FAIL`.
  - returns `3` for `INCONCLUSIVE`.

## Gate

Contract enforcement tests:

- `tests/test_cli_json_contract.py`
