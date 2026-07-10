# Execution modes

MCO supports `--execution-mode read_only|write|yolo`.

## Defaults

- `mco run` defaults to `write`.
- `mco review` defaults to `read_only`.

## Examples

General execution:

```bash
mco run --repo . --prompt "<task>" --providers claude,codex --execution-mode write --result-mode stdout
```

Read-only review:

```bash
mco review --repo . --prompt "<review task>" --providers claude,qwen --execution-mode read_only --result-mode stdout
```

Explicit unrestricted mode:

```bash
mco run --repo . --prompt "<task>" --providers hermes --execution-mode yolo --result-mode stdout
```

## Policy

- Use `read_only` for inspection and review.
- Use `write` for normal coding tasks.
- Use `yolo` only after the user explicitly requests unrestricted/bypass execution.
- Hermes oneshot is approval-bypassing by design and therefore requires explicit `--execution-mode yolo`.
