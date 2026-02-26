# Runtime Gate Report (2026-02-26)

- Status: PASS
- Ran 62 tests in 4.145s
- Raw log: `/Users/tsk/multi-cli-orchestrator/reports/adapter-contract/2026-02-26/runtime-gh-raw.log`

## Gate Mapping
- A1 (adapter contract tests for 5 providers): covered by `tests/test_adapter_contracts.py`
- R2 (unified review flow + strict JSON contract gate): covered by `tests/test_review_engine.py`
- CFG (review config loading defaults/overrides): covered by `tests/test_config.py`
- S0 (interface + artifact contract freeze): covered by `tests/test_contract_freeze.py`
- G (error taxonomy): covered by `tests/test_error_taxonomy.py`
- H (retry semantics + dispatch/notify idempotency): covered by `tests/test_retry_semantics.py`
