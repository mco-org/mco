# Multi-CLI Orchestrator Docs Index

## Read First
1. [multi-cli-orchestrator-proposal.md](./multi-cli-orchestrator-proposal.md)
2. [capability-research.md](./capability-research.md)
3. [notes.md](./notes.md)

## Gate Artifacts
1. [capability-probe-spec.md](./capability-probe-spec.md)
2. [adapter-contract-tests.md](./adapter-contract-tests.md)
3. [dry-run-plan.md](./dry-run-plan.md)
4. [implementation-gate-checklist.md](./implementation-gate-checklist.md)

## Implementation Freeze
1. [docs/implementation/step0-interface-freeze.md](./docs/implementation/step0-interface-freeze.md)

## Planning and Tracking
1. [task_plan.md](./task_plan.md)

## Release Notes
1. [docs/releases/v0.1.1.md](./docs/releases/v0.1.1.md)
2. [docs/releases/v0.1.1.zh-CN.md](./docs/releases/v0.1.1.zh-CN.md)
3. [docs/releases/v0.1.0.md](./docs/releases/v0.1.0.md)
4. [docs/releases/v0.1.0.zh-CN.md](./docs/releases/v0.1.0.zh-CN.md)

## Unified CLI (Step 2)
`mco review` is the unified entrypoint for running a review task.

`mco run` is the generalized execution entrypoint for agent-style task orchestration (no forced findings schema).

Quick start:
```bash
./mco review \
  --repo . \
  --prompt "Review this repository for high-risk bugs and security issues." \
  --providers claude,codex
```

Machine-readable output:
```bash
./mco review --repo . --prompt "Review for bugs." --providers claude,codex --json
```

General run mode:
```bash
./mco run --repo . --prompt "Summarize the current repo architecture." --providers claude,codex --json
```

Config file (JSON):
```json
{
  "providers": ["claude", "codex"],
  "artifact_base": "reports/review",
  "state_file": ".mco/state.json",
  "policy": {
    "timeout_seconds": 180,
    "max_retries": 1,
    "high_escalation_threshold": 1,
    "require_non_empty_findings": true,
    "max_provider_parallelism": 0,
    "allow_paths": [".", "runtime", "scripts"],
    "enforcement_mode": "strict",
    "provider_permissions": {
      "claude": {
        "permission_mode": "plan"
      },
      "codex": {
        "sandbox": "workspace-write"
      }
    },
    "provider_timeouts": {
      "claude": 300,
      "codex": 240,
      "qwen": 240
    }
  }
}
```

Run with config:
```bash
./mco review --config ./mco.example.json --repo . --prompt "Review for bugs and security issues."
```

Override fan-out and per-provider timeout from CLI:
```bash
./mco review \
  --repo . \
  --prompt "Review for bugs and security issues." \
  --providers claude,codex,gemini,opencode,qwen \
  --max-provider-parallelism 2 \
  --provider-timeouts qwen=240,codex=120
```

Run mode with hard path constraints:
```bash
./mco run \
  --repo . \
  --prompt "Compare adapter behaviors and return a short markdown summary." \
  --providers claude,codex \
  --allow-paths runtime,scripts \
  --target-paths runtime/adapters,runtime/review_engine.py \
  --enforcement-mode strict \
  --provider-permissions-json '{"codex":{"sandbox":"workspace-write"},"claude":{"permission_mode":"plan"}}' \
  --json
```

Artifacts are written to:
- `<artifact_base>/<task_id>/summary.md`
- `<artifact_base>/<task_id>/decision.md`
- `<artifact_base>/<task_id>/findings.json`
- `<artifact_base>/<task_id>/run.json`
- `<artifact_base>/<task_id>/providers/*.json`
- `<artifact_base>/<task_id>/raw/*.log`

Notes:
- YAML config requires `pyyaml` installed; otherwise use JSON config.
- Review prompt is wrapped with a strict JSON finding contract by default.
- `run` mode does not force findings schema; it focuses on execution aggregation and provider success.
- Execution model is `wait-all`: one provider timeout/failure does not stop others.
- `max_provider_parallelism=0` (or omitted) means full parallelism across selected providers.
- Built-in provider timeout profile defaults to `claude=300s` and `codex=240s`; config/CLI overrides still take precedence.
- `allow_paths` and `target_paths` are validated against `repo_root`; path escape is rejected.
- `enforcement_mode=strict` (default) fails closed when provider permission requirements cannot be honored.

## Step5 Benchmark Script
Use this script to generate serial vs full-parallel evidence and write reports under `reports/adapter-contract/<date>/`:

```bash
./scripts/run_step5_parallel_benchmark.sh
```

The generated summary JSON includes separated parse-vs-findings metrics:
- `providers_total`
- `parse_success_rate`
- `effective_findings_count`
- `zero_finding_provider_count`
