# Task Plan: Multi-CLI Orchestration Feasibility and Value

## Goal
Define a practical architecture that supports five mainstream coding CLIs (Claude, Codex, Gemini, OpenCode, Qwen) with dynamic capability/config detection and measurable business value.

## Phases
- [x] Phase 1: Plan and setup
- [x] Phase 2: Research and constraints
- [x] Phase 3: Architecture and decision design
- [x] Phase 4: Delivery and rollout guidance
- [x] Phase 5: Implementation gate review
- [x] Phase 6: Gate documentation package completion
- [x] Phase 7: Gate execution (probes + contract + dry run)
- [x] Phase 8: Runtime implementation for G/H gate
- [x] Phase 9: Restart-recovery validation and CI gate wiring
- [x] Phase 10: Step 0 interface/DoD freeze for Stage A implementation
- [x] Phase 11: Step 1 claude/codex adapter baseline + real dry-run evidence
- [x] Phase 12: Step 2 unified `mco review` entry + dispatch loop + artifact writer
- [x] Phase 13: Step 3 baseline (5-provider adapter wiring + structured parse gate)
- [x] Phase 14: Step 3 parser hardening for event-stream outputs + 5-provider real baseline parity evidence
- [x] Phase 15: Capability probe rerun after timeout-wrapper hardening (all providers re-validated)
- [x] Phase 16: Parallel fan-out runtime (`wait-all`) + provider timeout overrides + performance benchmark
- [x] Phase 17: Step 5 stability hardening (default provider timeout profile + one-click benchmark + non-blocking scheduled CI benchmark)
- [x] Phase 18: Step 5 report standardization (fixed markdown template + renderer + parse/findings metric split)
- [x] Phase 19: GitHub engineering baseline (issue/PR templates + workflow artifact index + v0.1.0 release documentation)
- [x] Phase 20: General execution layer baseline (`mco run` + allow-path validation + provider permission enforcement)

## Key Questions
1. How to avoid a single-CLI-centered architecture and make any CLI a first-class entry point?
2. How to discover which CLIs are available/configured per user and route tasks safely?
3. Which capabilities should be required for an adapter to participate (run, stream, schema, resume)?
4. How to prove ROI and decide whether multi-model review is worth the cost?

## Decisions Made
- Use a plugin/adapter architecture with a neutral orchestration core.
- Treat CLIs as optional providers discovered at runtime.
- Add capability tiering, task state machine, idempotency keys, and security baseline before coding starts.
- Add explicit normalize strategy, native-vs-shim async polling model, risk register, and staged success metrics.
- Add a 3-artifact gate pack (`probe spec`, `adapter contract tests`, `2-provider dry run plan`) plus an implementation gate checklist.
- Gate execution result on 2026-02-26 is `PASS`: all five providers pass required capabilities (`C0/C1/C2`), runtime G/H tests pass, and dry-run coverage includes all five providers.
- Restart recovery is validated by tests using persisted runtime state files, and CI gate workflow is wired (`.github/workflows/gate.yml`).
- Step 0 is frozen with executable contracts for adapter IO, RunResult fields, and artifact layout (`runtime/contracts.py`, `runtime/artifacts.py`, `docs/implementation/step0-interface-freeze.md`).
- Step 1 adapter baseline is implemented for `claude` and `codex` (`run/poll/cancel/normalize` shim flow) with contract tests and real dry-run evidence.
- Step 2 unified review flow is implemented: `mco review` -> config load -> provider dispatch -> strict JSON normalize -> `summary.md/decision.md/findings.json/run.json` artifacts.
- Step 3 baseline is implemented: adapter registry includes gemini/opencode/qwen and parse validation is now structured JSON contract-based with schema-valid/dropped metrics.
- Step 3 parse hardening is validated on a real 5-provider run: `task-b234caf82d5b25e0` achieved `parse_success_count=5/5` and `terminal_state=COMPLETED`.
- Capability probes are re-validated after timeout-wrapper hardening in `scripts/run_capability_probes.sh`; latest summary/lock files show 5-provider C0/C1/C2 enabled.
- Step 4 parallel benchmark completed: serial `143.16s` vs parallel(2) `74.01s` (48.3% lower wall time) with `parse_success_count=5/5` on repeated run.
- Step 5 stability hardening completed: built-in timeout profile defaults (`claude=300s`, `codex=240s`), one-command benchmark script (`scripts/run_step5_parallel_benchmark.sh`), and non-blocking scheduled benchmark workflow (`.github/workflows/benchmark.yml`).
- Step 5 reporting is standardized: fixed template at `docs/templates/step5-benchmark-report.md.tpl`, renderer `scripts/render_step5_report.py`, and CI artifact index generator `scripts/collect_ci_artifacts.py`.
- GitHub collaboration baseline is completed: issue templates and PR template under `.github/`, plus release doc `docs/releases/v0.1.0.md`.
- General execution baseline is implemented: `mco run` is available for non-review tasks, review contract enforcement is now mode-based, `allow_paths` path-bound checks are enforced, and provider permission mapping supports `strict`/`best_effort` execution modes.

## Errors Encountered
- None.

## Status
**Gate pass maintained** - runtime G/H implementation, parser hardening, and five-provider real baseline parity completed.
