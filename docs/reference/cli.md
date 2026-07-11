# CLI reference

The installed help output is authoritative:

```bash
mco --help
mco run --help
mco review --help
```

## Commands

| Command | Purpose |
|---------|---------|
| `mco run` | General multi-Agent invocation |
| `mco review` | Thin read-only raw-answer preset over the same invocation runtime |
| `mco doctor` | Provider presence, auth, version, risk, and Skill checks |
| `mco agent` | List, inspect, and discover provider models |
| `mco skills` | Read, inspect, and sync the bundled Skill |
| `mco session` | Persistent multi-turn provider sessions |
| `mco serve` | Run the MCP server |

The old findings command and findings-oriented memory commands were removed. Calling them returns migration guidance and does not start a provider.

## Invocation selection

| Option | Purpose |
|--------|---------|
| `--agent [alias=]provider:model` | Repeatable explicit invocation declaration |
| `--providers provider,...` | Invocation-native shorthand: one configured/default model per provider |
| `--provider-models-json` | Model mapping used by the provider shorthand |
| `--target-paths` | Comma-separated task scope paths |
| `--task-id` | Safe stable task/artifact identifier |
| `--prompt` / `--file` | Inline prompt, prompt file, or stdin with `--file -` |

Aliases must be unique. Repeating the same provider/model without distinct aliases is rejected. Configuration and provider/model validation happen before any Agent invocation starts.

## Runtime and access options

| Option | Default | Purpose |
|--------|---------|---------|
| `--execution-mode` | run: `write`; review: `read_only` | Provider permission profile |
| `--allow-paths` | `.` | Fail-closed MCO scope boundary |
| `--enforcement-mode` | `strict` | Reject unsupported provider policy or use `best_effort` |
| `--provider-permissions-json` | unset | Provider-specific permission overrides |
| `--provider-context-json` | unset | Provider context policy |
| `--provider-timeouts` | unset | Provider-specific timeout overrides |
| `--stall-timeout` | `900` | Per-invocation timeout in seconds |
| `--review-hard-timeout` | `1800` | Global task deadline; `0` disables |
| `--max-provider-parallelism` | `0` | Parallelism policy for configured execution |

## Output options

| Option | Purpose |
|--------|---------|
| `--result-mode stdout` | Stream/return answers and clean up temporary artifacts |
| `--result-mode artifact` | Persist artifacts and return the operational result |
| `--result-mode both` | Persist artifacts and stream/return answers |
| `--save-artifacts` | Upgrade the default stdout mode to `both` |
| `--json` | Print one final machine-readable envelope |
| `--stream jsonl` | Print machine-readable event lines as invocations progress |
| `--stream live` | Human live mode; non-TTY output falls back to JSONL |
| `--include-token-usage` | Preserve reliable provider usage metadata when available |

`--json`, `--quiet`, and `--stream` are mutually exclusive. In JSON/JSONL modes stdout contains only the selected protocol. Provider diagnostics and progress warnings go to stderr.

## Multi-stage options

| Option | Behavior |
|--------|----------|
| `--chain` | Run invocations sequentially and pass complete prior Markdown through a manifest |
| `--debate` | Add a read-only stage over prior raw answers |
| `--synthesize` | Add a read-only synthesis stage over the latest valid raw answers |
| `--synth-provider` | Select the provider invocation used for synthesis |

Chain and debate are mutually exclusive. The removed divide/perspectives flags return migration guidance. Debate and synthesis mark earlier answer files as untrusted reference material. A valid earlier answer allows later stages to continue after a partial failure; no valid input produces an explicit dependent-stage failure.

`mco review` uses the same runtime. Its default prompt is a short natural-language review request, and an explicit `--prompt` is passed unchanged. It never injects a findings schema.

## Artifacts

With persistent result mode, `<artifact-base>/<task-id>/` contains:

```text
result.md
run.json
stages/<stage>/invocations/<invocation-id>.md
stages/<stage>/context/manifest.json
stages/<stage>/result.md
stages/<stage>/run.json
provider-runs/                 # internal transport/provider evidence
```

`result.md` is deterministic in declaration order. Per-invocation Markdown preserves the decoded Agent answer body. Temporary execution removes its task directory and reports `artifact_root: null`.

## Exit codes and task status

| Code | Meaning |
|------|---------|
| `0` | All invocations completed successfully (`complete`) |
| `1` | At least one invocation succeeded and at least one did not (`partial`) |
| `2` | No invocation completed successfully, or input/configuration failed (`failed`) |

Invocation-level status remains explicit: `success`, `failed`, `timeout`, or `cancelled`. The task status is only `complete`, `partial`, or `failed`.

## Removed surfaces and migration

The findings command/schema, semantic normalization, deduplication, confidence, consensus, passive lifecycle, findings-driven memory, Markdown-PR, SARIF, and content-based `INCONCLUSIVE` surfaces are gone. The old `--format`, `--strict-contract`, `--memory`, `--space`, `--diff`, `--staged`, `--unstaged`, and `--diff-base` flags return migration errors. Use `--target-paths` and a raw prompt for scope, then select text, JSON, JSONL, or file-backed artifacts.
