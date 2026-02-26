# MCO Docs Index

English | [简体中文](./README.zh-CN.md)

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
2. [docs/contracts/cli-json-v0.1.x.md](./docs/contracts/cli-json-v0.1.x.md)
3. [docs/contracts/provider-permissions-v0.1.x.md](./docs/contracts/provider-permissions-v0.1.x.md)

## Planning and Tracking
1. [task_plan.md](./task_plan.md)

## Release Notes
1. [CHANGELOG.md](./CHANGELOG.md)
2. [docs/releases/v0.1.2.md](./docs/releases/v0.1.2.md)
3. [docs/releases/v0.1.2.zh-CN.md](./docs/releases/v0.1.2.zh-CN.md)
4. [docs/releases/v0.1.1.md](./docs/releases/v0.1.1.md)
5. [docs/releases/v0.1.1.zh-CN.md](./docs/releases/v0.1.1.zh-CN.md)
6. [docs/releases/v0.1.0.md](./docs/releases/v0.1.0.md)
7. [docs/releases/v0.1.0.zh-CN.md](./docs/releases/v0.1.0.zh-CN.md)

## Unified CLI (Step 2)
`mco review` is the unified entrypoint for running a review task.

`mco run` is the generalized execution entrypoint for agent-style task orchestration (no forced findings schema).

## Installation

NPM wrapper (available now, Python 3 required on PATH):

```bash
npm i -g @tt-a1i/mco
mco --help
```

Install from source (editable):

```bash
git clone https://github.com/tt-a1i/mco.git
cd mco
python3 -m pip install -e .
mco --help
```

Python package via PyPI:
- Not published yet.
- Publish workflow is ready and will be enabled after PyPI Trusted Publisher setup.

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

Stdout-only result mode (for caller rendering, no `summary.md/decision.md/findings.json/run.json` write):
```bash
./mco review --repo . --prompt "Review for bugs." --providers claude,codex --result-mode stdout --json
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
    "stall_timeout_seconds": 900,
    "poll_interval_seconds": 1.0,
    "review_hard_timeout_seconds": 1800,
    "enforce_findings_contract": false,
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
  --strict-contract \
  --max-provider-parallelism 2 \
  --stall-timeout 900 \
  --review-hard-timeout 1800 \
  --provider-timeouts qwen=900,codex=900
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

`run.json` includes audit fields for reproducibility:
- `effective_cwd`
- `allow_paths_hash`
- `permissions_hash`

Notes:
- YAML config requires `pyyaml` installed; otherwise use JSON config.
- Review prompt is wrapped with a JSON finding contract, but strict parse enforcement is optional.
- Enable strict gate behavior with `--strict-contract` (or `policy.enforce_findings_contract=true` in config).
- `run` mode does not force findings schema; it focuses on execution aggregation and provider success.
- `result_mode=artifact` (default): write user-facing artifacts and print compact result.
- `result_mode=stdout`: print provider-level result payload to stdout, skip user-facing artifact files.
- `result_mode=both`: write artifacts and print provider-level payload.
- Execution model is `wait-all`: one provider timeout/failure does not stop others.
- Timeout behavior is progress-driven:
  - `stall_timeout_seconds`: cancel only when output progress is idle beyond threshold.
  - `review_hard_timeout_seconds`: hard deadline applied only in `review` mode.
- `max_provider_parallelism=0` (or omitted) means full parallelism across selected providers.
- `provider_timeouts` are provider-specific stall-timeout overrides.
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
