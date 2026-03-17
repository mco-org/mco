<h1 align="center">MCO</h1>

<p align="center">
  <img src="./docs/assets/logos/mco-logo-readme.svg" alt="MCO Logo" width="520" />
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/@tt-a1i/mco"><img src="https://img.shields.io/npm/v/@tt-a1i/mco?style=flat-square&color=cb3837&logo=npm&logoColor=white" alt="npm version" /></a>
  <a href="https://www.npmjs.com/package/@tt-a1i/mco"><img src="https://img.shields.io/npm/dm/@tt-a1i/mco?style=flat-square&color=cb3837" alt="npm downloads" /></a>
  <a href="https://github.com/mco-org/mco/stargazers"><img src="https://img.shields.io/github/stars/mco-org/mco?style=flat-square&color=f59e0b" alt="GitHub stars" /></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="License: MIT" /></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
  <img src="https://img.shields.io/badge/Providers-5%20built--in-7c3aed?style=flat-square" alt="5 built-in providers" />
  <a href="https://pypi.org/project/evermemos-mcp/"><img src="https://img.shields.io/badge/evermemos--mcp-memory%20powered-6366f1?style=flat-square" alt="evermemos-mcp" /></a>
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
    <td align="center"><a href="https://github.com/open-claw/open-claw"><img src="https://cdn.jsdelivr.net/gh/twitter/twemoji@latest/assets/svg/1f99e.svg" alt="OpenClaw" width="48" /></a></td>
  </tr>
  <tr>
    <td align="center"><strong>Claude Code</strong></td>
    <td align="center"><strong>Gemini CLI</strong></td>
    <td align="center"><strong>Codex CLI</strong></td>
    <td align="center"><strong>OpenCode</strong></td>
    <td align="center"><strong>Qwen Code</strong></td>
    <td align="center"><strong>OpenClaw 🦞</strong></td>
  </tr>
  <tr>
    <td align="center"><code>claude</code></td>
    <td align="center"><code>gemini</code></td>
    <td align="center"><code>codex</code></td>
    <td align="center"><code>opencode</code></td>
    <td align="center"><code>qwen</code></td>
    <td align="center"><code>openclaw</code></td>
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

**Demo video (Bilibili):** [给 OpenClaw 装上兵权：组建你自己的 AI 军团](https://www.bilibili.com/video/BV1NRASz6EAH)

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
- **Consensus engine** — merged findings get `consensus_score = agreement_ratio × max_confidence` plus `confirmed` / `needs-verification` / `unverified` consensus levels
- **Cross-session memory** — `--memory` flag persists findings and agent scores via [evermemos-mcp](https://pypi.org/project/evermemos-mcp/), building institutional knowledge across runs
- **LLM synthesis** — `--synthesize` runs an extra pass to produce consensus/divergence summary across all agents
- **Live terminal streaming** — `--stream live` renders rich real-time terminal progress; `--stream jsonl` remains available for machine consumers
- **Debate mode** — `--debate` adds a second challenge round where agents critique the merged findings before final ranking
- **Divide mode** — `--divide files|dimensions` splits review work by file slices or review dimensions while preserving the existing merge + consensus pipeline
- **CI/CD integration** — `--format sarif` for GitHub Code Scanning, `--format markdown-pr` for PR comments
- **Environment health check** — `mco doctor` probes binary presence, version, and auth status for all providers
- **Token usage tracking** — `--include-token-usage` for best-effort per-agent and aggregate token consumption
- **Progress-driven timeouts** — agents run freely until completion; cancel only when output goes idle
- **Stateful sessions** — `mco session` for persistent multi-turn conversations with prompt queue and cancellation
- **ACP transport** — `--transport acp` for structured JSON-RPC communication via the Agent Client Protocol
- **Custom ACP agents** — `--agent NAME COMMAND` to register any ACP-compatible binary as a provider
- **Custom agent registry** — `.mco/agents.yaml`, `.mcorc.yaml`, or `~/.mco/agents.yaml` can register shim, ACP, or Ollama-backed agents; inspect them with `mco agent list` / `mco agent check`
- **Flexible prompt input** — `--file path`, `--file -` (stdin), or piped input for non-interactive workflows
- **Quiet mode** — `--quiet` for pipe-friendly output (final text only, no headers)
- **Config files** — `.mcorc.json` (project) and `~/.mco/config.json` (global) for persistent defaults
- **Idempotent sessions** — `mco session ensure` creates-or-returns a session in one call
- **Async send** — `--no-wait` returns immediately after queuing a prompt; retrieve results later via `session result`
- **Ctrl+C cancel** — interrupt `session send` gracefully, automatically cancels the running prompt
- **Chain mode** — `--chain` runs providers sequentially, feeding each provider's output as context to the next for challenge-and-supplement workflows
- **Per-provider perspectives** — `--perspectives-json` assigns different review focus areas (security, performance, maintainability) to each provider
- **Consensus badges** — findings show `[N/M agree]` in parallel mode or `[confirmed by N/M]` in chain mode to surface cross-agent agreement
- **Session retry with error classification** — session dispatch retries retryable errors (timeout, rate limit, network) with exponential backoff; partial output preserved on timeout
- **ACP bidirectional handlers** — agents can read/write files and run terminal commands through MCO
- **Extensible adapter contract** — uniform interface for any CLI agent, not limited to built-in providers
- **Machine-readable output** — JSON, SARIF, or Markdown output for downstream automation

## What's New in v0.9

- **Consensus Engine** — findings are no longer just deduplicated. Each merged finding now carries:
  - `agreement_ratio = detected_by_count / total_providers_ran`
  - `consensus_score = agreement_ratio × max_confidence`
  - `consensus_level = confirmed | needs-verification | unverified`
- **Real-time terminal mode** — `--stream live` adds a human-friendly TTY renderer while preserving `--stream jsonl` for automation.
- **Debate round** — `--debate` asks providers to challenge or refine merged findings before the final output.
- **Divide mode** — `--divide files` balances file ownership across providers; `--divide dimensions` assigns providers to security, performance, maintainability, correctness, and error-handling perspectives.
- **Custom agent registry** — MCO can now discover custom agents from `.mco/agents.yaml` / `~/.mco/agents.yaml`, including Ollama-backed local models.

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
| Debate findings | `mco review --debate --providers claude,codex,gemini` | Run an extra challenge round before final ranking |
| File division review | `mco review --divide files` | Split changed files across providers, balanced by file size |
| Dimension division review | `mco review --divide dimensions` | Give each provider a dedicated review dimension |
| Persistent code review | `mco review --memory` | Findings accumulate across runs; agents learn what's already been flagged |
| Diff-only review | `mco review --diff` | Review only changed files vs main branch |
| Staged changes review | `mco review --staged` | Review only git staged changes |
| Real-time event stream | `mco review --stream jsonl` | JSONL events to stdout as providers execute |
| Live terminal stream | `mco review --stream live` | Rich terminal progress view for interactive TTY sessions |
| Multi-turn session | `mco session start --provider claude` | Persistent session with conversation history |
| Cancel running prompt | `mco session cancel my-review` | Interrupt running + queued prompts immediately |
| Queue status | `mco session queue my-review` | Show running request ID and queue depth |
| Multi-session broadcast | `mco session broadcast "prompt"` | Fan out to all active sessions, aggregate results |
| ACP transport | `mco run --transport acp --providers claude` | Structured JSON-RPC communication with ACP agents |
| Custom ACP agent | `mco run --agent mybot "mybot --acp"` | Register a temporary ACP-compatible agent; works with `shim` or `acp` transport |
| Prompt from file | `mco review --file prompt.md --providers claude` | Read prompt from a file instead of inline |
| Piped prompt | `cat prompt.md \| mco run --providers claude` | Read prompt from stdin pipe |
| Quiet output | `mco run --quiet --providers claude --prompt "..."` | Print only final text, no headers |
| Config-driven run | (uses `.mcorc.json`) | Persistent project defaults without CLI flags |
| Idempotent session | `mco session ensure --provider claude --name dev` | Create or return existing session |
| Async prompt | `mco session send dev "task" --no-wait` | Queue prompt and return immediately |
| Retrieve async result | `mco session result dev 42` | Get result of a previously queued nowait request |
| Chain analysis | `mco review --chain --providers claude,codex` | Claude analyzes first, Codex challenges and supplements |
| Perspective assignment | `mco review --perspectives-json '{"claude":"security","codex":"performance"}'` | Each provider focuses on a different review area |
| List custom agents | `mco agent list` | Show built-in + configured custom agents |
| Check one custom agent | `mco agent check my-ollama` | Validate one configured agent or Ollama model wrapper |

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

### Consensus Engine

MCO v0.9 upgrades review merging from simple deduplication into a consensus analysis layer:

- `agreement_ratio = detected_by_count / total_providers_ran`
- `consensus_score = agreement_ratio × max_confidence`
- `consensus_level = confirmed | needs-verification | unverified`

Meaning of each level:

- `confirmed` — at least 50% of providers reported the finding
- `needs-verification` — 2+ providers reported it, but under 50% agreement
- `unverified` — only one provider reported it

Outputs now surface this consistently:

- **JSON** — each finding includes `consensus_score` and `consensus_level`
- **SARIF** — `confidence` is mapped from `consensus_score`
- **Markdown** — findings are grouped by consensus level
- **Chain mode** — confirmed findings are rendered as `confirmed-by` instead of `agree`

### Review Coordination Modes

| Mode | Flag | What it does |
|------|------|--------------|
| Parallel | default | All providers review the same scope independently |
| Chain | `--chain` | Run providers sequentially; each sees prior analysis |
| Debate | `--debate` | Run a second challenge round on merged findings |
| Divide by files | `--divide files` | Evenly distribute files across providers, prioritizing large files first |
| Divide by dimensions | `--divide dimensions` | Keep the same file scope, but assign each provider a review dimension |

`--divide` is mutually exclusive with `--chain` and `--debate`.

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

MCO is zero-config by default. You can also persist defaults in config files:

- **Project config**: `.mcorc.json` in the repo root
- **Global config**: `~/.mco/config.json`

Merge order: CLI flags > project config > global config > built-in defaults. Nested objects (like `policy`) are deep-merged.

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
| `--memory` | off | Enable cross-session memory via evermemos-mcp |
| `--space` | auto | Space slug for memory storage (default: inferred from git remote) |
| `--diff` | off | Review only changes vs merge-base with main/master |
| `--staged` | off | Review only staged changes |
| `--unstaged` | off | Review only unstaged working tree changes |
| `--diff-base` | auto | Git ref for branch diff (e.g. `origin/main`, `HEAD~3`). Implies `--diff` |
| `--stream` | off | `jsonl` for machine-readable events, `live` for interactive terminal rendering |
| `--transport` | `shim` | `shim` (stdout parsing) or `acp` (Agent Client Protocol JSON-RPC) |
| `--agent` | unset | Temporary custom ACP agent: `--agent NAME "command"`. Works with `shim` or `acp` transport |
| `--file` | unset | Read prompt from file path, or `-` for stdin. Mutually exclusive with `--prompt` |
| `--quiet` | off | Output only final text, no headers or formatting. Mutually exclusive with `--json`/`--stream` |
| `--chain` | off | Run providers sequentially, feeding each output as context to the next |
| `--debate` | off | Run a second challenge round on merged findings |
| `--divide` | off | `files` or `dimensions` task division across providers |
| `--perspectives-json` | unset | Per-provider review perspective JSON (e.g. `'{"claude":"security","codex":"performance"}'`) |

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

### Config File Example

```json
// .mcorc.json
{
  "providers": ["claude", "codex", "gemini"],
  "transport": "acp",
  "quiet": true,
  "policy": {
    "stall_timeout_seconds": 600,
    "enforcement_mode": "best_effort",
    "max_provider_parallelism": 3,
    "chain": false,
    "perspectives": {
      "claude": "Focus on security vulnerabilities and injection attacks",
      "codex": "Focus on performance bottlenecks and resource leaks",
      "gemini": "Focus on code maintainability and design patterns"
    }
  }
}
```

Run `mco review --help` for the full flag list.

## Custom Agents

MCO can load custom agents from:

- `.mco/agents.yaml` in the repo root
- `.mcorc.yaml` in the repo root
- `~/.mco/agents.yaml` globally

Inspect what MCO sees:

```bash
mco agent list
mco agent check my-ollama
```

Example `.mco/agents.yaml`:

```yaml
agents:
  - name: my-acp-agent
    transport: acp
    command: my-agent --acp
    permission_keys: [sandbox]

  - name: my-shim-agent
    transport: shim
    command: my-review-bot --json

  - name: my-ollama
    model: qwen2.5-coder:14b
```

How it works:

- `transport: acp` registers a custom ACP provider
- `transport: shim` registers a command-based shim provider
- `model: ...` registers an Ollama-backed provider automatically

This means local Ollama models can participate in the same `mco review` / `mco run` workflows as Claude, Codex, Gemini, OpenCode, and Qwen.

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
     ├─→ Gemini CLI     ├─→ Consensus Engine → Debate / Synthesize → Output
     ├─→ OpenCode       │
     └─→ Qwen Code   ───┘
                              │
                    ┌─────────┼─────────┐
                    ▼         ▼         ▼
                  JSON    SARIF    Markdown-PR
               (stdout)  (CI/CD)  (PR comment)

     ↕  (with --memory)
  evermemos-mcp
  ┌─────────────────────────┐
  │ findings  · agent scores│
  │ run history · priors    │
  └─────────────────────────┘
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

## Cross-Session Memory (Powered by evermemos-mcp)

MCO integrates with [evermemos-mcp](https://pypi.org/project/evermemos-mcp/) to give your agent team persistent memory across sessions. Add `--memory` once and MCO starts accumulating institutional knowledge: which findings were real, which agents are reliable for which task types, and what has already been fixed.

Fully opt-in — without `--memory`, MCO behaves exactly as before.

```bash
# Install the optional dependency
pip install mco[memory]

# Run with memory enabled
mco review \
  --repo . \
  --prompt "Review for security issues." \
  --providers claude,codex,gemini \
  --memory
```

**What memory adds:**

| Phase | What happens |
|-------|-------------|
| Pre-run | Prior findings injected into prompt with confidence grades `[HIGH]`/`[MEDIUM]`/`[LOW]` |
| Pre-run | Agent weights loaded — more reliable agents get more weight in consensus |
| Post-run | New findings persisted with finding hash for cross-run deduplication |
| Post-run | Agent scores updated (cross-validation: agents that agree get higher reliability) |
| Post-run | Passively fixed findings auto-confirmed (disappeared + file changed = fixed) |

**Finding lifecycle:**

```
open → passive_fix_candidate → fixed
            ↓
         (rejected / wontfix / accepted)
```

A finding that disappears when its file was changed is marked `passive_fix_candidate`. If it stays absent a second consecutive run, it's auto-confirmed as `fixed` — no manual intervention needed.

**Agent reliability:**

MCO tracks each agent's cross-validation rate per task category (security, performance, logic, architecture, style). Agents that consistently agree with others on real findings build up higher reliability scores. Cold-start blends repo-specific, tech-stack, and global baseline scores until enough runs accumulate.

### Memory Subcommands

```bash
mco memory status                      # Memory spaces and finding/score counts
mco memory agent-stats                 # Per-agent reliability scores
mco memory priors --category security  # Blended agent weight priors for a task type

mco findings list                      # All persisted findings
mco findings list --status open        # Filter by status
mco findings confirm <hash>            # Manually mark a finding as fixed
```

### Storage Design

- **Backend**: [evermemos-mcp](https://pypi.org/project/evermemos-mcp/) via `uvx evermemos-mcp@latest` (append-only, MCP stdio protocol)
- **Finding hash**: `sha256(repo + file_path + category + normalize(title))` — stable across runs, independent of line numbers or severity changes
- **Spaces**: `coding:<slug>--findings`, `coding:<slug>--agents`, `coding:<slug>--context`, `coding:stacks--<tech>`, `coding:global--agents`
- **Deduplication**: client-side latest-wins on read; all writes are appends

Requires `EVERMEMOS_API_KEY` environment variable. See `mco review --help` for `--space` and other memory flags.

## MCP Server Mode

MCO can run as an MCP server, allowing AI agents and MCP-compatible clients to call MCO tools programmatically over stdio.

```bash
pip install mco[memory]  # includes mcp dependency
```

Configure in your MCP client:

```json
{
  "mcpServers": {
    "mco": {
      "command": "mco",
      "args": ["serve"]
    }
  }
}
```

**Available tools:** `mco_review`, `mco_run`, `mco_doctor`, `mco_findings_list`, `mco_memory_status`

All tools return a uniform envelope: `{"ok": true, "data": ...}` on success, `{"ok": false, "error": {"code": "...", "message": "..."}}` on failure.

## License

MIT — see [LICENSE](./LICENSE)
