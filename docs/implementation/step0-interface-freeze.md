# Step 0 Interface Freeze (Stage A)

Date: 2026-02-26  
Status: READY FOR STEP 1

This document freezes three implementation contracts before adapter coding:
- Provider adapter input/output interfaces (proposal §2).
- Runtime `RunResult` field contract.
- Artifact directory/output contract (proposal §13).

## 1) ProviderAdapter Contract (Frozen)
Runtime source of truth: `runtime/contracts.py`.

Required methods:
- `detect() -> ProviderPresence`
- `capabilities() -> CapabilitySet`
- `run(input_task: TaskInput) -> TaskRunRef`
- `poll(ref: TaskRunRef) -> TaskStatus`
- `cancel(ref: TaskRunRef) -> None`
- `normalize(raw: Any, ctx: NormalizeContext) -> list[NormalizedFinding]`

Frozen enums/sets:
- `ProviderId`: `claude|codex|gemini|opencode|qwen`
- `CapabilityTier`: `C0..C6`

## 2) RunResult Contract (Frozen)
Runtime source of truth: `runtime/types.py`.

Schema version:
- `RUN_RESULT_SCHEMA_VERSION = "stage-a-v2"`

Frozen field order:
1. `task_id`
2. `provider`
3. `dispatch_key`
4. `success`
5. `attempts`
6. `delays_seconds`
7. `output`
8. `final_error`
9. `warnings`
10. `deduped_dispatch`

## 3) Artifact Layout Contract (Frozen)
Runtime source of truth: `runtime/artifacts.py`.

Layout version:
- `ARTIFACT_LAYOUT_VERSION = "stage-a-v1"`

Per-task artifact root:
`<artifact_base>/<task_id>/`

Required root files:
- `summary.md`
- `decision.md`
- `findings.json`
- `run.json`

Required root directories:
- `providers/`
- `raw/`

Per-provider required files:
- `providers/<provider>.json`
- `raw/<provider>.stdout.log`
- `raw/<provider>.stderr.log`

## 4) Step 0 DoD (Definition of Done)
- [x] Frozen interfaces are codified in runtime modules.
- [x] Frozen `RunResult` fields have explicit schema version.
- [x] Frozen artifact layout has explicit schema version.
- [x] Contract-freeze tests enforce these shapes:
  - `tests/test_contract_freeze.py`

## 5) Change Policy
If any frozen field/signature/layout changes:
1. Bump schema version (`stage-a-v2`).
2. Update this document.
3. Update `tests/test_contract_freeze.py`.
4. Record migration note in `reports/gate/*-signoff.md`.

