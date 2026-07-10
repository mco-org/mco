# Provider selection

## Human workflow

Ask the user which agents should execute the task. Confirm the list in natural language before invoking MCO.

## CLI workflow

Always pass an explicit provider set:

```bash
mco run --repo . --prompt "Summarize this repo." --providers claude,codex --result-mode stdout
```

```bash
mco review --repo . --prompt "Review for bugs." --providers claude,codex,qwen --result-mode stdout
```

## Error handling

If MCO returns `provider_selection_required`:

1. Stop and ask the user which agents to use.
2. Retry with `--providers <confirmed-list>`.
3. Do not silently substitute a default provider set.

## Discovery helpers

```bash
mco agent list --json
mco doctor --json
```

Use these to show available agents, but never treat availability as implicit consent.
