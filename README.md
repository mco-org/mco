# MCO

<p align="left">
  <img src="./docs/assets/logos/mco-logo.svg" alt="MCO Logo" width="520" />
</p>

**MCO — One Prompt. Five AI Agents. One Result.**

English | [简体中文](./README.zh-CN.md)

## What is MCO

MCO (Multi-CLI Orchestrator) is a neutral orchestration layer that dispatches a single prompt to multiple AI coding agents in parallel and aggregates their results. No vendor lock-in. No workflow rewrite. Just fan-out, wait-all, and collect.

You keep using Claude Code, Codex CLI, Gemini CLI, OpenCode, and Qwen Code as they are. MCO wires them into a unified execution pipeline with structured output, progress-driven timeouts, and reproducible artifacts.

## Key Highlights

- **Parallel fan-out** — dispatch to all providers simultaneously, wait-all semantics
- **Progress-driven timeouts** — agents run freely until completion; cancel only when output goes idle
- **Dual mode** — `mco review` for structured code review findings, `mco run` for general task execution
- **Provider-neutral** — uniform adapter contract across 5 CLI tools, no favoring any vendor
- **Machine-readable output** — JSON result payloads and per-provider artifact trees for downstream automation

## Supported Providers

| Provider | CLI | Status |
|----------|-----|--------|
| Claude Code | `claude` | Supported |
| Codex CLI | `codex` | Supported |
| Gemini CLI | `gemini` | Supported |
| OpenCode | `opencode` | Supported |
| Qwen Code | `qwen` | Supported |

No project migration. No command relearning. No single-tool lock-in.

## Quick Start

Install via npm (Python 3 required on PATH):

```bash
npm i -g @tt-a1i/mco
```

Or install from source:

```bash
git clone https://github.com/mco-org/mco.git
cd mco
python3 -m pip install -e .
```

Run your first multi-agent review:

```bash
mco review \
  --repo . \
  --prompt "Review this repository for high-risk bugs and security issues." \
  --providers claude,codex,qwen
```

## Usage

### Review Mode

Structured code review with findings schema. Each provider returns normalized findings with severity, category, evidence, and recommendations.

```bash
mco review \
  --repo . \
  --prompt "Review for security vulnerabilities and performance issues." \
  --providers claude,codex,gemini,opencode,qwen \
  --json
```

### Run Mode

General-purpose multi-agent execution. No forced output schema — providers complete the task freely.

```bash
mco run \
  --repo . \
  --prompt "Summarize the architecture of this project." \
  --providers claude,codex \
  --json
```

### Result Modes

| Mode | Behavior |
|------|----------|
| `--result-mode stdout` | Print full result to stdout, skip artifact files (default) |
| `--result-mode artifact` | Write artifact files, print summary |
| `--result-mode both` | Write artifacts and print full result |

Use `--save-artifacts` to keep stdout mode while still writing artifacts.

### Path Constraints

Restrict which files agents can access:

```bash
mco run \
  --repo . \
  --prompt "Analyze the adapter layer." \
  --providers claude,codex \
  --allow-paths runtime,scripts \
  --target-paths runtime/adapters \
  --enforcement-mode strict
```

## Defaults and Overrides

MCO is zero-config by default. You can run it directly with built-in defaults and override behavior with CLI flags only.

### Key Runtime Flags

| Flag | Default | Description |
|------|---------|-------------|
| `--providers` | `claude,codex` | Comma-separated provider list |
| `--stall-timeout` | `900` | Cancel when no output progress for this duration (seconds) |
| `--review-hard-timeout` | `1800` | Hard deadline for review mode; `0` disables |
| `--max-provider-parallelism` | `0` | `0` = full parallelism across selected providers |
| `--enforcement-mode` | `strict` | `strict` fails closed on unmet permissions |
| `--strict-contract` | off | Enforce strict findings JSON contract (review mode) |
| `--provider-timeouts` | unset | Per-provider stall-timeout overrides (`provider=seconds`) |
| `--provider-permissions-json` | unset | Provider permission mapping JSON (see below) |
| `--save-artifacts` | off | Write artifacts while keeping stdout result delivery |
| `--task-id` | auto-generated | Stable task identifier for artifact paths |
| `--idempotency-key` | auto-generated | Deduplicate repeated runs with the same key |
| `--artifact-base` | `reports/review` | Base directory for artifact output |

Default provider permissions:

| Provider | Key | Default |
|----------|-----|---------|
| `claude` | `permission_mode` | `plan` |
| `codex` | `sandbox` | `workspace-write` |

Override example:

```bash
mco review \
  --repo . \
  --prompt "Review for bugs." \
  --providers claude,codex,qwen \
  --save-artifacts \
  --stall-timeout 900 \
  --review-hard-timeout 1800 \
  --max-provider-parallelism 0 \
  --provider-timeouts qwen=900,codex=900
```

Run `mco review --help` for the full flag list.

## Exit Codes

| Code | Meaning |
|------|---------|
| `0` | Success |
| `2` | FAIL / input / config / runtime error |
| `3` | INCONCLUSIVE (review mode only, with `--strict-contract`) |

## How It Works

```
prompt ─> MCO ─┬─> Claude Code  ─┐
               ├─> Codex CLI     ├─> aggregate ─> JSON (+ optional artifacts)
               ├─> Gemini CLI    │
               ├─> OpenCode      │
               └─> Qwen Code   ──┘
```

Each provider runs as an independent subprocess through a uniform adapter contract:

1. **Detect** — check binary presence and auth status
2. **Run** — spawn CLI process with prompt, capture stdout/stderr
3. **Poll** — monitor process + output byte growth for progress detection
4. **Cancel** — SIGTERM/SIGKILL on stall timeout or hard deadline
5. **Normalize** — extract structured findings from raw output

Execution model is **wait-all**: one provider's timeout or failure never stops others.

### Retry and Resilience

- Transient errors (timeout, rate-limit, network) are retried automatically with exponential backoff (default: 1 retry).
- A single provider failure never blocks other providers.
- Repeated runs with the same `--idempotency-key` return cached results without re-dispatching.

### Running Inside Claude Code

MCO automatically strips the `CLAUDECODE` environment variable before spawning provider subprocesses. You can safely run `mco` from within a Claude Code session.

## Artifacts

When artifact writing is enabled (`--save-artifacts` or `--result-mode artifact/both`), MCO writes:

```
reports/review/<task_id>/
  summary.md          # Human-readable summary
  decision.md         # PASS / FAIL / ESCALATE / PARTIAL
  findings.json       # Aggregated normalized findings (review mode)
  run.json            # Machine-readable execution metadata
  providers/          # Per-provider result JSON
  raw/                # Raw stdout/stderr logs
```

## License

UNLICENSED
