# CLI reference

This page is a compact reference for stable MCO concepts. The installed help output remains authoritative:

```bash
mco --help
mco run --help
mco review --help
```

## Commands

| Command | Purpose |
|---------|---------|
| `mco run` | General multi-agent execution |
| `mco review` | Structured findings and review decisions |
| `mco doctor` | Provider presence, auth, version, and risk checks |
| `mco agent` | List, inspect, and discover provider models |
| `mco skills` | Read, inspect, and sync the bundled Skill |
| `mco session` | Persistent multi-turn provider sessions |
| `mco memory` | Inspect optional cross-session memory |
| `mco findings` | Query stored findings |
| `mco serve` | Run the MCP server |

## Runtime options

| Option | Default | Purpose |
|--------|---------|---------|
| `--providers` | required | Explicit comma-separated provider IDs |
| `--execution-mode` | run: `write`; review: `read_only` | Unified permission profile |
| `--repo` | `.` | Repository root |
| `--prompt` / `--file` | unset | Inline, file, or stdin prompt |
| `--target-paths` | `.` | Task scope |
| `--allow-paths` | `.` | Orchestrator-level allowed scope |
| `--enforcement-mode` | `strict` | Fail closed or use best effort |
| `--stall-timeout` | `900` | Cancel a provider after no output progress |
| `--review-hard-timeout` | `1800` | Global review deadline; `0` disables |
| `--max-provider-parallelism` | `0` | `0` runs all selected providers concurrently |
| `--provider-timeouts` | unset | Provider-specific stall timeout overrides |
| `--provider-models-json` | unset | Model routing by provider ID |
| `--provider-context-json` | unset | Skills, context file, and plugin policy |
| `--provider-permissions-json` | unset | Expert provider permission overrides |
| `--perspectives-json` | unset | Review focus by provider |
| `--dry-run` | off | Resolve policy and commands without execution |
| `--task-id` | generated | Stable task and artifact identifier |

## Output options

| Option | Purpose |
|--------|---------|
| `--json` | Machine-readable final envelope |
| `--quiet` | Final text only |
| `--stream jsonl` | Machine-readable progress events |
| `--stream live` | Human-readable live terminal progress |
| `--format report` | Human-readable review report |
| `--format markdown-pr` | PR-ready Markdown |
| `--format sarif` | SARIF 2.1.0 for code scanning |
| `--include-token-usage` | Best-effort provider and aggregate usage |

`--quiet`, `--json`, and `--stream` are mutually exclusive output surfaces.

## Coordination options

| Option | Purpose |
|--------|---------|
| `--chain` | Feed each provider's output into the next |
| `--debate` | Add a challenge round after initial merging |
| `--divide files` | Split files across providers |
| `--divide dimensions` | Assign review dimensions |
| `--synthesize` | Run an extra consensus/divergence summary |
| `--synth-provider` | Choose the synthesis provider |

Chain, debate, and divide modes are mutually exclusive.

## Result modes and artifacts

| Mode | Stdout | Persistent artifacts |
|------|--------|----------------------|
| `stdout` | complete result | no |
| `artifact` | summary | yes |
| `both` | complete result | yes |

`--save-artifacts` upgrades stdout mode to preserve artifacts as well.

```text
reports/review/<task_id>/
  summary.md
  decision.md
  findings.json
  run.json
  providers/
  raw/
```

Review artifacts include normalized findings. Run mode does not enforce the review findings schema.

## Exit codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `2` | Input, configuration, policy, or runtime failure |
| `3` | Inconclusive strict review contract |

Machine-readable failures follow the contract in [errors-v0.1.x.md](../contracts/errors-v0.1.x.md).

## Consensus fields

Merged review findings can include:

- `agreement_ratio = detected_by_count / total_providers_ran`
- `consensus_score = agreement_ratio × max_confidence`
- `consensus_level = confirmed | needs-verification | unverified`

Consensus reflects model agreement. It does not replace source inspection or tests.
