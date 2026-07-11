# Provider and invocation selection

## Human workflow

Ask the user which providers and models should execute the task. Confirm the list in natural language before invoking MCO.

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

## Error handling

If MCO returns `provider_selection_required`:

1. Stop and ask the user which providers/models to use.
2. Retry with the confirmed `--providers` or `--agent` list.
3. Do not silently substitute a default provider team.

## Discovery helpers

```bash
mco agent list --json
mco agent models --providers codex,pi --json
mco doctor --json
```

Discovery is best effort and is not consent. A partial model catalog must not be treated as proof that an otherwise invocable model is unavailable.
