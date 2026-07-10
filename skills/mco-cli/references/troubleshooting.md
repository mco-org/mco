# Troubleshooting and recovery

## Provider failures

If a provider fails:

1. Report per-provider `success/final_error/parse_reason`.
2. Distinguish transport/auth errors from parse/contract issues.
3. Continue with successful providers (wait-all behavior).

## Skill drift

Check bundled Skill health:

```bash
mco doctor --skill-health --json
mco skills status --json
```

Repair drift explicitly:

```bash
mco skills sync --agent codex --agent claude-code
```

## Partial install recovery

If CLI installation succeeded but Skill sync failed, retry:

```bash
mco skills sync --agent codex --agent claude-code
```

Do not roll back a successful CLI install when Skill sync fails.

## Timeouts and stability

- Use provider-specific stall timeout when one provider is slow:
  - `--provider-timeouts qwen=900,codex=300`
- Set review hard deadline for CI predictability:
  - `--review-hard-timeout 1800`
- Use a stable `--task-id` when you need predictable artifact paths across retries.

## Result modes

- `artifact`: writes user-facing artifact files for CI/audit.
- `stdout`: returns results directly to caller output for chat/agent UX.
- `both`: writes artifacts and returns detailed stdout payload.

When returning to end users, prefer non-JSON stdout unless the caller explicitly requires JSON.
