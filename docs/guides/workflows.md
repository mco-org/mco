# MCO workflow guide

This guide collects the workflows intentionally kept out of the project README. Run `mco <command> --help` for the authoritative options installed with your version.

## Install

Install the CLI and copy the bundled Skill into selected calling agents:

```bash
npx @tt-a1i/mco@latest install --agent codex --agent claude-code --yes
mco doctor --skill-health --json
```

Install only the CLI, then sync the Skill separately:

```bash
npm i -g @tt-a1i/mco
mco skills sync --agent codex --agent claude-code
```

Installer `--agent` selects Skill destinations. Runtime `--providers` selects the agents that execute a task.

## Run and review

`mco run` is for general execution. It defaults to `--execution-mode write`.

```bash
mco run \
  --repo . \
  --prompt "Summarize the architecture." \
  --providers claude,codex
```

`mco review` is for normalized findings and severity-based decisions. It defaults to `--execution-mode read_only`.

```bash
mco review \
  --repo . \
  --prompt "Review for correctness and security issues." \
  --providers claude,codex,pi
```

## Review only changes

```bash
mco review --providers claude,codex --diff
mco review --providers claude,codex --staged
mco review --providers claude,codex --unstaged
mco review --providers claude,codex --diff-base origin/main
```

The diff flags are mutually exclusive. An explicit `--diff-base` implies branch diff mode.

## Coordination modes

| Mode | Flag | Behavior |
|------|------|----------|
| Parallel | default | All selected providers inspect the same scope independently |
| Chain | `--chain` | Each provider sees the preceding analysis |
| Debate | `--debate` | Providers challenge merged findings in a second round |
| Divide files | `--divide files` | Split file ownership across providers |
| Divide dimensions | `--divide dimensions` | Assign review dimensions such as security or performance |

`--chain`, `--debate`, and `--divide` are mutually exclusive.

Assign explicit perspectives without changing file scope:

```bash
mco review \
  --providers claude,codex \
  --perspectives-json '{"claude":"security","codex":"performance"}' \
  --prompt "Review this change."
```

## Multiple models from one provider

Provider IDs are deduplicated within one MCO call. To compare several Pi models, launch one independent call per model and run those calls concurrently from the upstream orchestrator.

```bash
mco run --providers pi \
  --provider-models-json '{"pi":{"provider":"codewiz-gemini","model":"gemini-3.5-flash"}}' \
  --task-id eval-gemini --execution-mode read_only --prompt "Evaluate this project."
```

Use unique task IDs. Do not let parallel `write` or `yolo` calls modify the same worktree.

## Result delivery

| Mode | Behavior |
|------|----------|
| `stdout` | Print the complete result and use temporary runtime artifacts; default |
| `artifact` | Persist artifacts and print a summary |
| `both` | Persist artifacts and print the complete result |

Use `--save-artifacts` to preserve artifacts while keeping stdout delivery.

## Streaming

```bash
mco review --providers claude,codex --stream live
mco review --providers claude,codex --stream jsonl
```

`live` is intended for humans. `jsonl` is intended for orchestration and automation.

## Persistent sessions

```bash
mco session start --provider claude --name dev
mco session send dev "Review the authentication flow."
mco session send dev "Now propose a fix." --no-wait
mco session result dev 2
mco session queue dev
mco session cancel dev
mco session stop dev
```

Use `mco session ensure --provider claude --name dev` when callers need create-or-return behavior.

## Memory

Cross-session memory is optional and requires `evermemos-mcp` plus `EVERMEMOS_API_KEY`.

```bash
mco review --providers claude,codex --memory --space my-project
mco memory status --space my-project
mco memory agent-stats --space my-project
```

The `--space` value is a slug. MCO adds its internal prefix and storage suffixes.

## MCP server and ACP transport

Run the MCO MCP server:

```bash
mco serve
```

Use ACP for providers that support structured JSON-RPC transport:

```bash
mco run --transport acp --providers claude --prompt "Analyze this repository."
```

ACP file and terminal handlers extend the trust boundary. Terminal access must be explicitly enabled and should only be granted to trusted agents or isolated environments.

## Failure handling

MCO waits for selected providers independently. Report `success`, `final_error`, and `parse_reason` per provider instead of hiding partial failure behind one aggregate result.

Use provider-specific stall timeouts when one CLI is predictably slower:

```bash
mco review \
  --providers claude,codex,qwen \
  --provider-timeouts qwen=900,codex=300 \
  --review-hard-timeout 1800
```
