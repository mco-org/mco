# MCO workflow guide

This guide covers the invocation-native CLI. Run `mco <command> --help` for the authoritative options installed with your version.

## Install

Install the CLI and copy the bundled Skill into selected calling Agents:

```bash
npx @tt-a1i/mco@latest install --agent codex --agent claude-code --yes
mco doctor --skill-health --json
```

Install only the CLI, then sync the Skill separately:

```bash
npm i -g @tt-a1i/mco
mco skills sync --agent codex --agent claude-code
```

Installer `--agent` selects Skill destinations. Runtime `--agent` selects model-qualified invocations; runtime `--providers` is the shorthand for one configured/default model per provider.

## Run and review

`mco run` defaults to workspace write access. `mco review` is a thin read-only preset over the same invocation runtime.

```bash
mco run \
  --repo . \
  --prompt "Summarize the architecture." \
  --providers claude,codex

mco review \
  --repo . \
  --prompt "Review this repository for correctness risks." \
  --providers claude,codex,pi
```

An explicit review prompt is passed unchanged. Without one, review uses a short natural-language prompt and does not request a structured findings response.

## Explicit model invocations

Use `--agent [alias=]provider:model` when model identity matters or when one provider should run multiple models:

```bash
mco run --repo . --prompt "Inspect the authentication flow." \
  --agent security=codex:gpt-5.6-sol \
  --agent alternate=codex:gpt-5.6-luna \
  --result-mode both --task-id auth-review
```

Each alias is an independent invocation. MCO preserves each answer and reports its operational status separately. Configuration errors are rejected before provider execution.

## Scope and parallel writing

Use `--target-paths` to constrain the task scope:

```bash
mco run --repo . --target-paths runtime/parser.py \
  --agent parser=codex:model-a --prompt "Implement the parser change."
mco run --repo . --target-paths tests/test_parser.py \
  --agent tests=pi:model-b --prompt "Add coverage for the parser change."
```

Parallel writing is an explicit user choice. MCO does not create or manage worktrees and does not prohibit parallel writers. The calling Agent should partition ownership into non-overlapping paths, use distinct task IDs, and warn about shared-file edit conflicts before dispatch.

For review coordination, `--perspectives-json` prepends an explicit Provider prompt focus. `--divide files` excludes ignored/local/build directories, sorts the remaining repository files in the selected target scope, and assigns them round-robin without overlap; `--divide dimensions` rotates fixed review lenses in invocation declaration order and leaves `target_paths` unchanged. Dry-run shows the fully resolved prompts and target paths. These settings only arrange prompts or scope; MCO still returns each invocation's untouched raw answer and never infers a semantic conclusion. `--divide` cannot be combined with `--chain` or `--debate`.

## Chain, debate, and synthesis

### Chain

```bash
mco run --repo . --prompt "Analyze this repository." \
  --agent first=pi:model-a \
  --agent second=codex:model-b \
  --chain --result-mode artifact --task-id chained-analysis
```

Chain runs one invocation per stage. The next stage receives `stages/<stage>/context/manifest.json` and paths to complete prior Markdown answers. It does not receive a silent summary, sample, truncation, or prompt-embedded copy of the earlier answer.

### Debate and synthesis

```bash
mco review --repo . --prompt "Challenge the previous analysis." \
  --providers claude,codex,pi \
  --debate --synthesize --synth-provider codex \
  --result-mode both --task-id debate-run
```

Debate and synthesis are read-only stages. Earlier outputs are untrusted reference material. The synthesis manifest retains run and (when run) debate records in declaration order, including explicit failure or missing records; it never points at synthesis output itself. If an earlier stage is partially successful, later stages continue when at least one valid answer exists, including a valid run answer after a failed debate; otherwise the dependent stage records an explicit failure and the aggregate remains `partial` or `failed`.

## Output and artifacts

```text
<artifact-base>/<task-id>/
  result.md
  run.json
  stages/<stage>/invocations/<invocation-id>.md
  stages/<stage>/context/manifest.json
  stages/<stage>/result.md
  stages/<stage>/run.json
```

Use `stdout` for temporary answer delivery, `artifact` for persistent files, or `both` for both. Temporary runs clean up their runtime directory and report `artifact_root: null`. Persistent Markdown contains the raw answer body; root `result.md` groups actual stages, puts synthesis first when present, and still keeps all raw answers and explicit failures. `run.json` contains only operational metadata.

## Streaming and machine output

```bash
mco review --providers claude,codex --stream live
mco review --providers claude,codex --stream jsonl
mco review --providers claude,codex --json
```

Default text mode writes answer deltas to stdout as they arrive. Multiple invocations receive source labels between answers, while each answer body remains unchanged. JSONL `output_delta` events are losslessly reconstructible per invocation. Progress, warnings, and provider diagnostics are written to stderr.

## Sessions and MCP

Persistent sessions remain available:

```bash
mco session start --provider claude --name dev
mco session send dev "Review the authentication flow."
mco session result dev 1
mco session stop dev
```

Run the MCO MCP server when the caller needs the same raw operational run/review surface over MCP:

```bash
mco serve
```

## Failure handling

Inspect each invocation's `status`, `output`, `error`, `exit_code`, `transport_status`, `usage`, and `stderr`. Task exit codes are `0` for `complete`, `1` for `partial`, and `2` for `failed`. A provider failure never silently removes successful answers.

For example, when `fast` succeeds and `slow` times out, the final JSON remains useful: it has `status: partial`, `exit_code: 1`, the complete `fast` answer, and an explicit timeout record for `slow`.

Old findings, semantic decision, consensus, SARIF, Markdown-PR, memory, and diff-only review workflows are removed. Migrate them to raw prompts, `--target-paths`, JSON/JSONL output, and file-backed stages.
