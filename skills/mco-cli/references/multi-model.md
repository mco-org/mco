# Multi-model parallel execution

Use multiple models from the same provider when you want independent opinions or implementations without changing MCO's provider abstraction.

## Why separate runs are required

MCO deduplicates `--providers` by provider ID, and `--provider-models-json` stores one model selection per provider ID. Therefore, `--providers pi,pi,pi` still produces one effective `pi` execution; it does not create three Pi instances.

To run multiple Pi models concurrently:

1. Launch one independent `mco run` or `mco review` call per model.
2. Give every call an explicit `--providers pi`, model mapping, and unique `--task-id`.
3. Use the upstream caller's parallel execution mechanism to run those calls concurrently.

## Pi example

The following independent calls evaluate the same repository with three Pi models. Run them concurrently from the upstream caller.

### Gemini 3.5 Flash

```bash
mco run --repo . --prompt "Evaluate this project with file-backed evidence." --providers pi --provider-models-json '{"pi":{"provider":"codewiz-gemini","model":"gemini-3.5-flash"}}' --task-id "eval-gemini-3-5-flash" --execution-mode read_only --result-mode stdout --json
```

### Qwen 3.7 Max

```bash
mco run --repo . --prompt "Evaluate this project with file-backed evidence." --providers pi --provider-models-json '{"pi":{"provider":"codewiz-anthropic","model":"qwen3.7-max"}}' --task-id "eval-qwen-3-7-max" --execution-mode read_only --result-mode stdout --json
```

### DeepSeek V4 Pro

```bash
mco run --repo . --prompt "Evaluate this project with file-backed evidence." --providers pi --provider-models-json '{"pi":{"provider":"seal","model":"deepseek-v4-pro"}}' --task-id "eval-deepseek-v4-pro" --execution-mode read_only --result-mode stdout --json
```

## Output and write safety

- `stdout` is the default result mode and uses a per-process temporary artifact directory. It is the simplest choice for upstream aggregation.
- When using `--result-mode artifact`, `both`, or `--save-artifacts`, keep task IDs unique so persistent artifact paths do not overlap.
- Use `read_only` when models are evaluating the same working tree.
- Do not let multiple `write` or `yolo` runs edit the same working tree concurrently. Give each writer a separate worktree, or select one model to implement after the read-only comparison.

## Aggregate results

For every run:

1. Check the outer `terminal_state`.
2. Check the Pi provider's `success`, `final_error`, and `parse_reason` fields.
3. Compare file-backed evidence across successful model outputs.
4. Treat agreement as a lead, not proof. Verify claims against source files and run the relevant tests before accepting a conclusion or change.
