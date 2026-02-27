# MCO

<p align="left">
  <img src="./docs/assets/logos/mco-logo.svg" alt="MCO Logo" width="520" />
</p>

**MCO — Orchestrate AI Coding Agents. Any Prompt. Any Agent. Any IDE.**

English | [简体中文](./README.zh-CN.md)

## What is MCO

MCO (Multi-CLI Orchestrator) is a neutral orchestration layer for AI coding agents. It dispatches prompts to multiple agent CLIs in parallel, aggregates results, and returns structured JSON. No vendor lock-in. No workflow rewrite.

MCO is designed to be called by an orchestrating agent — from Claude Code, Cursor, Trae, Copilot, Windsurf, or any AI-powered IDE. The calling agent organizes context, assigns tasks, and uses MCO to fan out work across multiple agents simultaneously. Agents can also orchestrate each other: Claude Code can dispatch tasks to Codex and Gemini via MCO, and vice versa.

## Key Highlights

- **Parallel fan-out** — dispatch to multiple agents simultaneously, wait-all semantics
- **Any IDE, any agent** — works from Claude Code, Cursor, Trae, Copilot, Windsurf, or plain shell
- **Agent-to-agent orchestration** — agents can dispatch tasks to other agents through MCO
- **Progress-driven timeouts** — agents run freely until completion; cancel only when output goes idle
- **Dual mode** — `mco review` for structured code review findings, `mco run` for general task execution
- **Extensible adapter contract** — uniform interface for any CLI agent, not limited to built-in providers
- **Machine-readable output** — JSON result payloads returned directly to stdout for downstream automation

## Built-in Providers

| Provider | CLI | Status |
|----------|-----|--------|
| Claude Code | `claude` | Supported |
| Codex CLI | `codex` | Supported |
| Gemini CLI | `gemini` | Supported |
| OpenCode | `opencode` | Supported |
| Qwen Code | `qwen` | Supported |

The adapter architecture is extensible — adding a new agent CLI requires implementing three hooks: auth check, command builder, and output normalizer.

## Why Multi-Agent?

No single AI model sees everything. Each model has its own training data, reasoning style, and blind spots. When you run a code review with only one agent, you get one perspective — and whatever it misses, you miss.

**Code review** is where this matters most. In practice:

- One agent catches a race condition in your async code but overlooks an SQL injection in the ORM layer.
- Another spots the injection immediately but misses the race condition entirely.
- A third flags neither of those but finds a subtle memory leak in the resource cleanup path that the other two ignored.

These aren't hypothetical — different models genuinely have different strengths. Some are better at security analysis, some at logic flow, some at performance patterns. By running 3-5 agents in parallel on the same codebase, you get a **union of perspectives** rather than the intersection. The result is a more thorough review than any single agent could produce, regardless of which one you pick.

MCO makes this practical: one command, all agents run simultaneously, and results are aggregated into a single findings report. The overhead is near zero — the wall-clock time is roughly equal to the slowest agent, not the sum of all agents.

This principle extends beyond code review:

- **Architecture analysis** — different agents surface different design risks and trade-offs
- **Bug hunting** — broader coverage across code paths and edge cases
- **Refactoring assessment** — multiple perspectives on impact and safety of proposed changes

The question isn't "which AI agent is best" — it's "why limit yourself to one?"

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

### Agent-Friendly CLI

MCO's CLI is fully self-describing. Run `mco -h` or `mco review -h` to see grouped flags, defaults, and usage examples — all in the terminal. This means any AI agent that can execute shell commands can learn MCO's interface autonomously by reading the help output, without requiring documentation or prior training.

In practice, you simply tell your IDE agent what you want:

> "Use mco to dispatch a security review to Claude and Codex, and a performance analysis to Gemini and Qwen — run them in parallel."

The agent reads `mco -h`, understands the flags, composes the commands, and orchestrates the entire workflow on its own. You describe the intent; the agent handles the rest.

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
Cursor / Trae / Copilot / Claude Code / shell
         │
         ▼
      mco run / mco review
         │
         ├─> Claude Code  ─┐
         ├─> Codex CLI     ├─> aggregate ─> JSON (+ optional artifacts)
         ├─> Gemini CLI    │
         ├─> OpenCode      │
         └─> Qwen Code   ──┘
```

The calling agent (or user) invokes `mco` with a prompt and a list of providers. MCO fans out to all selected agents in parallel and waits for all to finish.

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
- Every invocation executes providers and returns fresh output (no result-cache replay).

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

MIT — see [LICENSE](./LICENSE)
