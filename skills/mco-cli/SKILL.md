---
name: mco-cli
description: Use `mco` to orchestrate multi-provider agent execution (`run`/`review`), choose result mode (`artifact`/`stdout`/`both`), and return user-readable output by default.
---

# MCO CLI Skill

## When to use

Use this skill when you need to:

- Run one or more coding agents in parallel from a single CLI entrypoint.
- Execute repository review tasks with severity-based decisions.
- Return user-readable result summaries (default non-JSON output).
- Produce machine-readable JSON for upstream automation.

## Core commands

Before running `mco run` or `mco review`, ask the user in natural language which agents they want to use. Do not infer a provider set from availability alone. Pass the confirmed choice through `--providers`. If MCO returns `provider_selection_required`, pause and ask the user before retrying.

### 1) General execution

```bash
./mco run \
  --repo . \
  --prompt "<task>" \
  --providers claude,codex,qwen \
  --result-mode stdout
```

Use for generic agent tasks. This mode does not require findings schema.

### 2) Review execution

```bash
./mco review \
  --repo . \
  --prompt "<review task>" \
  --providers claude,qwen \
  --result-mode stdout
```

Use for bug/security/test-gap style review scenarios.

### 3) Strict gate review (CI style)

```bash
./mco review \
  --repo . \
  --prompt "<review task>" \
  --providers claude,codex \
  --strict-contract \
  --result-mode artifact \
  --json
```

Use when machine-enforced findings contract is required.

## Result mode policy

- `artifact`:
  - Writes user-facing artifact files (`summary.md`, `decision.md`, `findings.json`, `run.json`).
  - Best for CI/audit.
- `stdout`:
  - Returns results directly to caller output.
  - Best for chat/agent UX rendering.
- `both`:
  - Writes artifacts and returns detailed stdout payload.

## Output policy for user-facing responses

When returning to end users:

1. Prefer non-JSON `stdout` output from `mco` for readability.
2. If JSON is required by caller, parse and reformat into:
   - Execution Summary
   - Provider Details
   - Risk/Findings Summary
   - Next Actions
3. Never dump raw event streams unless user explicitly asks for raw logs.

## Recommended defaults

- There is no implicit provider set. Ask the user and pass `--providers` explicitly.
- `--result-mode stdout` for interactive agents.
- `--result-mode artifact --json` for CI pipelines.
- `--strict-contract` only for gate workflows.
- Narrow scope with `--target-paths` for faster review.

## Timeout and stability tips

- Use provider-specific stall timeout when one provider is slow:
  - `--provider-timeouts qwen=900,codex=300`
- Set review hard deadline for CI predictability:
  - `--review-hard-timeout 1800`
- Use a stable `--task-id` when you need predictable artifact paths across retries.

## Failure handling

If a provider fails:

1. Report per-provider `success/final_error/parse_reason`.
2. Distinguish transport/auth errors from parse/contract issues.
3. Continue with successful providers (wait-all behavior).

## Minimal response template (to user)

Use this structure in final answers:

1. Execution overview (decision, terminal_state, success/failure count)
2. Provider-by-provider status
3. Key findings grouped by severity
4. Actionable next steps

