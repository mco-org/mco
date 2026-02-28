<h1 align="center">MCO</h1>

<p align="center">
  <img src="./docs/assets/logos/mco-logo-readme.svg" alt="MCO Logo" width="520" />
</p>

<p align="center">
  <img src="https://img.shields.io/npm/v/@tt-a1i/mco" alt="npm version" />
  <img src="https://img.shields.io/badge/License-MIT-blue.svg" alt="License: MIT" />
  <img src="https://img.shields.io/badge/providers-5%20built--in-green" alt="Providers: 5 built-in" />
</p>

<p align="center"><strong>MCO — Orchestrate AI Coding Agents. Any Prompt. Any Agent. Any IDE.</strong></p>

<p align="center"><strong>MCO equips your primary agent with an agent team: dispatch Claude, Codex, Gemini, OpenCode, and Qwen in parallel to execute tasks, review outputs, and synthesize consensus.</strong></p>

<p align="center">English | <a href="./README.zh-CN.md">简体中文</a></p>

<table align="center">
  <tr>
    <td align="center"><a href="https://github.com/anthropics/claude-code"><img src="https://github.com/anthropics.png?size=96" alt="Claude Code" width="48" /></a></td>
    <td align="center"><a href="https://github.com/google-gemini/gemini-cli"><img src="https://github.com/google-gemini.png?size=96" alt="Gemini CLI" width="48" /></a></td>
    <td align="center"><a href="https://github.com/openai/codex"><img src="https://github.com/openai.png?size=96" alt="Codex CLI" width="48" /></a></td>
    <td align="center"><a href="https://github.com/sst/opencode"><img src="https://raw.githubusercontent.com/sst/opencode/master/packages/console/app/src/asset/brand/opencode-logo-light-square.svg" alt="OpenCode" width="48" /></a></td>
    <td align="center"><a href="https://github.com/QwenLM/qwen-code"><img src="https://github.com/QwenLM.png?size=96" alt="Qwen Code" width="48" /></a></td>
  </tr>
  <tr>
    <td align="center"><strong>Claude Code</strong></td>
    <td align="center"><strong>Gemini CLI</strong></td>
    <td align="center"><strong>Codex CLI</strong></td>
    <td align="center"><strong>OpenCode</strong></td>
    <td align="center"><strong>Qwen Code</strong></td>
  </tr>
  <tr>
    <td align="center"><code>claude</code></td>
    <td align="center"><code>gemini</code></td>
    <td align="center"><code>codex</code></td>
    <td align="center"><code>opencode</code></td>
    <td align="center"><code>qwen</code></td>
  </tr>
</table>

> AI coding agents are now standard tools for every developer. But one agent is just one perspective.
>
> Work like a Tech Lead: assign one task to multiple agents, run in parallel, and compare outcomes before acting.
>
> One command. Five agents working at once.

### Works with OpenClaw

Running [OpenClaw](https://github.com/open-claw/open-claw) on your machine? It can use MCO as its multi-agent backbone. Just tell OpenClaw what you need:

> "Use mco to run a security review on this repo with Claude, Codex, and Gemini. Synthesize the results."

OpenClaw reads `mco -h`, learns the CLI, and orchestrates the entire workflow autonomously. Your local machine becomes a multi-agent review team — OpenClaw is the manager, MCO is the dispatcher, and Claude/Codex/Gemini/OpenCode/Qwen are the team members.

This works the same way from **Claude Code, Cursor, Trae, Copilot, Windsurf**, or any agent that can run shell commands.

## What is MCO

MCO (Multi-CLI Orchestrator) is a neutral orchestration layer for AI coding agents. It dispatches prompts to multiple agent CLIs in parallel, aggregates results, and returns structured output — JSON, SARIF, or PR-ready Markdown. No vendor lock-in. No workflow rewrite.

With the rise of agentic coding — led by projects like [OpenClaw](https://github.com/open-claw/open-claw) and the broad availability of Claude Code, Codex CLI, Gemini CLI, and more — every developer now has access to powerful AI agents. MCO takes the next step: instead of relying on a single agent, you orchestrate a team.

MCO is designed to be called by any orchestrating agent or AI-powered IDE — Claude Code, Cursor, Trae, Copilot, Windsurf, or **OpenClaw**. The calling agent organizes context, assigns tasks, and uses MCO to fan out work across multiple agents simultaneously. For example, OpenClaw running on your machine can call `mco review` to dispatch code reviews to Claude, Codex, and Gemini in parallel — turning your local setup into a multi-agent review team with a single command. Agents can also orchestrate each other: Claude Code can dispatch tasks to Codex and Gemini via MCO, and vice versa.

## One Agent is a Tool. Five Agents are a Team.

No single AI model sees everything. Each model has its own training data, reasoning style, and blind spots. Using just one agent is like having a team of five engineers and only asking one for their opinion.

**MCO turns this into a team workflow:**

1. **Assign** — You give MCO a task and a list of agents. Like a Tech Lead assigning the same code review to five team members.
2. **Execute in parallel** — All agents work simultaneously. Wall-clock time ≈ the slowest agent, not the sum.
3. **Review and deduplicate** — MCO collects each agent's findings, deduplicates identical issues across agents, and tracks which agents found what (`detected_by`).
4. **Synthesize consensus** — Optionally, one agent summarizes the combined results: what everyone agrees on, where they diverge, and what to do next.

**In practice, different agents catch different things:**

- One agent spots a race condition in your async code but overlooks an SQL injection in the ORM layer.
- Another finds the injection immediately but misses the race condition entirely.
- A third catches neither of those but flags a subtle memory leak in the resource cleanup path.

These aren't hypothetical — different models genuinely have different strengths. Some are better at security analysis, some at logic flow, some at performance patterns. By running 3–5 agents in parallel on the same codebase, you get a **union of perspectives** rather than the intersection. The result is a more thorough review than any single agent could produce, regardless of which one you pick.

This principle extends beyond code review:

- **Architecture analysis** — different agents surface different design risks and trade-offs
- **Bug hunting** — broader coverage across code paths and edge cases
- **Refactoring assessment** — multiple perspectives on impact and safety of proposed changes

The question isn't "which AI agent is best" — it's "why limit yourself to one?"

## Key Highlights

- **Parallel fan-out** — dispatch to multiple agents simultaneously, wait-all semantics
- **Any IDE, any agent** — works from Claude Code, Cursor, Trae, Copilot, Windsurf, or plain shell
- **Agent-to-agent orchestration** — agents can dispatch tasks to other agents through MCO
- **Dual mode** — `mco review` for structured code review findings, `mco run` for general task execution
- **Cross-agent deduplication** — identical findings from multiple agents are merged automatically with `detected_by` provenance
- **LLM synthesis** — `--synthesize` runs an extra pass to produce consensus/divergence summary across all agents
- **CI/CD integration** — `--format sarif` for GitHub Code Scanning, `--format markdown-pr` for PR comments
- **Environment health check** — `mco doctor` probes binary presence, version, and auth status for all providers
- **Token usage tracking** — `--include-token-usage` for best-effort per-agent and aggregate token consumption
- **Progress-driven timeouts** — agents run freely until completion; cancel only when output goes idle
- **Extensible adapter contract** — uniform interface for any CLI agent, not limited to built-in providers
- **Machine-readable output** — JSON, SARIF, or Markdown output for downstream automation

## Built-in Providers

| Provider | CLI | Status |
|----------|-----|--------|
| Claude Code | `claude` | Supported |
| Codex CLI | `codex` | Supported |
| Gemini CLI | `gemini` | Supported |
| OpenCode | `opencode` | Supported |
| Qwen Code | `qwen` | Supported |

The adapter architecture is extensible — adding a new agent CLI requires implementing three hooks: auth check, command builder, and output normalizer.

## Use Cases

| Scenario | Command | What happens |
|----------|---------|--------------|
| PR code review | `mco review --format markdown-pr` | Multiple agents review in parallel, output a PR-ready comment |
| Security scan in CI | `mco review --format sarif` | Results upload directly to GitHub Code Scanning |
| Architecture analysis | `mco run --providers claude,gemini,qwen` | Multi-perspective architecture assessment |
| Pre-deploy health check | `mco doctor --json` | Verify all agents are installed and authenticated |
| Consensus decision | `mco review --synthesize` | Summarize what agents agree on and where they diverge |

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

### Doctor

Check that your agents are installed, reachable, and authenticated before running tasks:

```bash
mco doctor
mco doctor --json
```

### Output Formats (Review Mode)

| Format | Flag | Use case |
|--------|------|----------|
| Human-readable report | `--format report` (default) | Terminal reading |
| PR Markdown | `--format markdown-pr` | Post as GitHub PR comment |
| SARIF 2.1.0 | `--format sarif` | Upload to GitHub Code Scanning |
| Machine JSON | `--json` | Downstream automation |

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
| `--format` | `report` | Output format: `report`, `markdown-pr`, `sarif` (review-only for last two) |
| `--include-token-usage` | off | Best-effort per-provider and aggregate token usage |
| `--synthesize` | off | Run extra LLM pass for consensus/divergence summary |
| `--synth-provider` | `claude` | Which provider runs the synthesis pass |
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
You (Tech Lead)
     │
     ▼
  mco review / mco run
     │
     ├─→ Claude Code  ──┐
     ├─→ Codex CLI      │
     ├─→ Gemini CLI     ├─→ Deduplicate → Synthesize → Output
     ├─→ OpenCode       │
     └─→ Qwen Code   ───┘
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
                  JSON    SARIF    Markdown-PR
               (stdout)  (CI/CD)  (PR comment)
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
