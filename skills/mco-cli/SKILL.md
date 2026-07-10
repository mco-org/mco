---
name: mco-cli
description: Use `mco` to orchestrate multi-provider agent execution (`run`/`review`), choose result mode (`artifact`/`stdout`/`both`), and return user-readable output by default.
---

# MCO CLI Skill

## When to use

Use this skill when you need to:

- Run one or more coding agents in parallel from a single CLI entrypoint.
- Execute repository review tasks with severity-based decisions.
- Return user-readable result summaries (default non-JSON output).
- Produce machine-readable JSON for upstream automation.

## Mandatory provider selection

Before running `mco run` or `mco review`, ask the user in natural language which agents they want to use. Do not infer a provider set from availability alone. Pass the confirmed choice through `--providers`. If MCO returns `provider_selection_required`, pause and ask the user before retrying.

## Execution defaults

- `mco run` defaults to `--execution-mode write`.
- `mco review` defaults to `--execution-mode read_only`.
- Use `--execution-mode yolo` only after the user explicitly requests unrestricted/bypass execution.

## Progressive references

- [Installation and Skill sync](references/installation.md)
- [Provider selection](references/provider-selection.md)
- [Execution modes](references/execution-modes.md)
- [Troubleshooting and recovery](references/troubleshooting.md)

## Minimal response template

When returning to end users:

1. Execution overview (decision, terminal_state, success/failure count)
2. Provider-by-provider status
3. Key findings grouped by severity
4. Actionable next steps
