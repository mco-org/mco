# Provider and invocation selection

## Human workflow

Resolve any saved top-level `providers` default, then show and confirm the provider/model team in natural language before invoking MCO. If no saved default exists, ask the user which providers and models should execute the task.

## Model-qualified workflow

Use one repeatable `--agent` option for each invocation:

```bash
mco run --repo . --prompt "Summarize this repo." \
  --agent claude=claude:default \
  --agent codex=codex:gpt-5.6-sol
```

Aliases must be unique. Repeating the same provider/model without an alias is rejected. This is the preferred form when comparing multiple models from one provider.

## Provider shorthand

Use `--providers` when one default/configured model per provider is enough:

```bash
mco review --repo . --prompt "Review for bugs." --providers claude,codex,qwen
```

MCO converts the shorthand to invocation records before dispatch. It does not route this form through a separate legacy engine.

When neither CLI selection is present, a top-level `providers` configuration supplies the saved default. Detected binaries alone never select a team.

## Error handling

If MCO returns `provider_selection_required`:

1. Stop and ask the user which providers/models to use.
2. Retry with the confirmed `--providers` or `--agent` list.
3. Do not silently substitute a team inferred from detected binaries.

## Discovery helpers

```bash
mco agent list --json
mco agent models --providers codex,pi --json
mco doctor --json
```

Discovery is best effort and is not consent. A partial model catalog must not be treated as proof that an otherwise invocable model is unavailable.
