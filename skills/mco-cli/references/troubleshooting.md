# Troubleshooting and recovery

## Provider failures

Inspect each invocation's `status`, `error`, `exit_code`, `transport_status`, and `stderr`; inspect `usage` only when `--include-token-usage` was requested and the Provider reported it. A failed invocation does not discard successful answers. The aggregate is `partial` when at least one invocation succeeds and `failed` when none do.

## Timeouts and cancellation

- Use `--provider-timeouts provider=seconds` when one provider is predictably slow.
- Use `--review-hard-timeout seconds` for a global deadline across the task.
- A timed-out or cancelled invocation is recorded explicitly; it is not converted into a successful-looking answer.
- After a test or run, verify that no provider child processes remain before retrying.

## Result modes and artifacts

- `stdout`: temporary artifacts, raw answer delivery, and `artifact_root: null` in JSON.
- `artifact`: persistent `result.md`, `run.json`, and per-stage/per-invocation Markdown.
- `both`: persistent artifacts plus stdout answer delivery.

Use a stable, safe `--task-id` for reproducible artifact paths. Reusing a task ID replaces stale invocation Markdown for that stage; do not share it between concurrent processes.

## Multi-stage failures

Chain, debate, and synthesis read complete Markdown answers through `context/manifest.json`. If a context file cannot be read, the dependent invocation records the provider error. If no valid prior answer exists, synthesis records `no_valid_prior_answer` and the task remains failed or partial as appropriate.

## Skill drift

```bash
mco doctor --skill-health --json
mco skills status --json
mco skills sync --agent codex --agent claude-code
```

Sync only the explicitly selected calling Agents. Do not treat a detected installation as consent.

## Breaking migration errors

Old findings-oriented flags return guidance to use raw prompts, JSON/JSONL output, result modes, and file-backed stages. Do not retry them with hidden combinations; update the calling workflow.
