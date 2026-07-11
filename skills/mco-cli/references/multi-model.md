# Multi-model parallel execution

Use repeatable `--agent` declarations when one provider should run more than one model in the same MCO task.

```bash
mco run --repo . --prompt "Evaluate this project." \
  --agent gemini=pi:gemini-3-5-flash \
  --agent qwen=pi:qwen3-7-max \
  --agent deepseek=pi:deepseek-v4-pro \
  --result-mode both --task-id model-comparison
```

Each alias becomes an independent invocation. MCO preserves declaration order in the final result and keeps each answer in its own artifact. `--providers pi` remains useful when the provider's configured/default model is sufficient; `--provider-models-json` can supply the default model mapping for that provider.

## Parallel writing safety

Before running multiple `write` or `yolo` invocations, partition file ownership explicitly:

```bash
mco run --repo . --target-paths runtime/parser.py \
  --agent parser=codex:gpt-5.6-sol --task-id parser-change
mco run --repo . --target-paths tests/test_parser.py \
  --agent tests=pi:code-model --task-id parser-tests
```

The examples are independent calls. MCO does not create or manage worktrees, and it does not ban a user from selecting parallel writers. The upstream Agent must warn about conflicts, use non-overlapping paths where possible, and identify any shared files that can still race.

Use `read_only` when several models inspect the same working tree. Use unique task IDs for persistent artifacts so separate calls do not overwrite one another.

## Output handoff

For each invocation, inspect `status`, `output`, `error`, `exit_code`, and `artifact_path`. In JSONL mode, concatenate only that invocation's `output_delta` events to reconstruct its formal answer. Treat agreement as an input for human or upstream-Agent judgment, never as a semantic consensus field.
