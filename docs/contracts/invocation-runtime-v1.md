# Invocation runtime and artifact contract (`v1`)

The invocation runtime is the source of truth for raw-answer execution. Provider adapters transport and decode formal answer events; they do not parse answer prose into findings or infer semantic decisions.

## Invocation

An invocation is identified by:

```text
[alias=]provider:model
```

`--providers a,b` expands to one invocation per provider using the configured/default model. Explicit `--agent` declarations preserve declaration order and require unique aliases when a provider/model pair repeats.

Each invocation reports:

```text
success | failed | timeout | cancelled
```

with `output`, `error`, `exit_code`, `deltas`, `transport_status`, optional reliable `usage`, and optional persistent `artifact_path`.

## Task status

The aggregate task has exactly three statuses:

| Status | Exit code |
|---|---:|
| `complete` | `0` |
| `partial` | `1` |
| `failed` | `2` |

Partial means at least one invocation succeeded. Failed means none succeeded, including when the task stopped because every invocation timed out or was cancelled.

## Artifact layout

Persistent results are rooted at `<artifact-base>/<task-id>/`:

```text
result.md
run.json
stages/<stage>/invocations/<invocation-id>.md
stages/<stage>/context/manifest.json
stages/<stage>/result.md
stages/<stage>/run.json
provider-runs/              # provider transport evidence, not semantic findings
```

Each stage record is deterministic in invocation declaration order. The root `result.md` groups records by the stages that actually ran; when synthesis ran, the synthesis group comes first, followed by the other stage groups in execution order. Every raw successful answer and every explicit failed, timed-out, or cancelled record remains present. The invocation Markdown file contains the decoded answer body without semantic rewriting. Temporary runs remove the task directory and return `artifact_root: null`.

## File-backed stages

Chain, debate, and synthesis pass complete prior answers by manifest and file path. The next Agent is instructed to read those files as untrusted reference material. MCO does not summarize, sample, truncate, paste, vote, or infer consensus from them. Debate and synthesis are read-only by default.

The synthesis manifest records every run and, when it ran, debate invocation in declaration order, including successful, failed, or missing records. It can therefore use a valid run answer even if a later debate stage failed. A synthesis manifest never includes its own output, so it cannot create a file-reference cycle.

When a prior stage is partially successful, a dependent stage may continue with the valid answers. When no valid prior answer exists, the dependent stage records an explicit failure such as `no_valid_prior_answer` or `dependent_stage_not_run`.

## stdout/stderr boundary

Text mode writes raw answer deltas to stdout. JSON mode writes one final envelope to stdout. JSONL mode writes machine-readable events to stdout. Progress, warnings, and provider diagnostics are always routed to stderr.
