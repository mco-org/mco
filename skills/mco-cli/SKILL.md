---
name: mco-cli
description: Use `mco` to run explicit multi-provider Agent invocations, stream raw answers, persist file-backed artifacts, and coordinate read-only chain/debate/synthesis stages.
---

# MCO CLI Skill

Use this Skill when an upstream Agent needs to dispatch one task to one or more coding Agents and preserve their raw operational answers.

## Before execution

Confirm the provider/model team with the user in natural language. Do not infer consent from installed binaries. Use either:

- `--agent [alias=]provider:model` once per invocation; or
- `--providers provider,...` for one default-model invocation per provider.

`--agent` is the model-qualified form. It supports repeated models from one provider when each repeated invocation has a distinct alias:

```bash
mco run --repo . --prompt "Inspect the parser." \
  --agent fast=pi:fast-model \
  --agent careful=pi:careful-model \
  --result-mode stdout
```

`--providers pi,codex` is an invocation-native shorthand. MCO resolves each provider's configured/default model and runs the resulting invocations through the same runtime; it is not a legacy execution path.

If MCO returns `provider_selection_required`, ask the user which Agents to use and retry with an explicit `--providers` or `--agent` selection.

## Execution defaults

- `mco run` defaults to `--execution-mode write`.
- `mco review` is a thin read-only preset and defaults to `--execution-mode read_only`.
- Review passes the explicit prompt unchanged. With no prompt, it uses a short natural-language review prompt; it does not inject a findings schema.
- Use `--execution-mode yolo` only after the user explicitly requests unrestricted execution.

## Output and status

MCO returns raw Agent answer text plus operational metadata. It does not infer findings, severity, confidence, consensus, or decisions from answer prose.

- Default text mode streams answer deltas to stdout. With multiple invocations it adds source labels between answers but does not rewrite answer content.
- `--json` prints one final JSON envelope.
- `--stream jsonl` prints JSONL events; each invocation's `output_delta` values concatenate to its formal answer.
- Progress, warnings, and provider diagnostics go to stderr. stdout remains answer text or the selected machine protocol.
- `status` is `complete`, `partial`, or `failed`; exit codes are `0`, `1`, and `2` respectively. A cancelled or timed-out invocation is recorded inside the corresponding task status.

For example, if `fast` succeeds and `slow` times out, the final envelope is `status: partial`, `exit_code: 1`, and still contains `fast`'s complete answer plus `slow`'s explicit timeout record.

Use `--result-mode stdout|artifact|both`. Temporary runs clean up their task directory and return `artifact_root: null`. Persistent modes write deterministic artifacts:

```text
<artifact-base>/<task-id>/
  result.md
  run.json
  stages/<stage>/invocations/<invocation-id>.md
  stages/<stage>/context/manifest.json   # chain/debate/synthesis inputs
  stages/<stage>/result.md               # staged result
  stages/<stage>/run.json                 # staged operational record
```

`--save-artifacts` is shorthand for upgrading the default stdout mode to `both`. Answer Markdown preserves the Agent's answer body as returned by the transport decoder.

## Multi-stage workflows

- `--chain` runs invocations sequentially. Each next Agent receives a manifest and paths to the complete prior Markdown answer; MCO does not summarize, sample, truncate, or paste the previous answer into the prompt.
- `--debate` adds a read-only stage over the prior raw answer files.
- `--synthesize` adds a read-only stage using `--synth-provider` when specified, otherwise the first selected invocation.
- Debate and synthesis prompts mark earlier files as untrusted reference material. If a prior stage partially fails, later stages continue when a valid answer exists; otherwise the dependent stage records an explicit failure.

## Parallel writing safety

Parallel writing is an explicit user choice. MCO does not create or manage worktrees and does not silently prohibit multiple write invocations.

Before dispatching parallel writers, ask the upstream Agent to partition ownership into non-overlapping `--target-paths` and state the edit-conflict risk. Use distinct aliases and task IDs, and warn the user if two writers may touch the same file. Prefer a read-only comparison before choosing one implementation when ownership cannot be partitioned safely.

## Progressive references

- [Installation and Skill sync](references/installation.md)
- [Provider selection](references/provider-selection.md)
- [Execution modes](references/execution-modes.md)
- [Multi-model and write ownership](references/multi-model.md)
- [Troubleshooting and recovery](references/troubleshooting.md)

## Breaking migration

The findings command, findings schema, semantic decision/consensus pipeline, Markdown-PR and SARIF renderers, content-based `INCONCLUSIVE`, and findings-driven memory surfaces were removed. Old flags such as `--format`, `--strict-contract`, `--memory`, `--space`, and diff-only review flags return migration guidance instead of being silently ignored.

Migrate callers to raw prompts plus `--result-mode`, `--json`, `--stream jsonl`, and file-backed chain/debate/synthesis stages.
