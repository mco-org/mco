<h1 align="center">MCO</h1>

<p align="center">
  <img src="./docs/assets/logos/mco-logo-readme.svg" alt="MCO Logo" width="520" />
</p>

<p align="center">
  <a href="https://www.npmjs.com/package/@tt-a1i/mco"><img src="https://img.shields.io/npm/v/@tt-a1i/mco?style=flat-square&color=cb3837&logo=npm&logoColor=white" alt="npm version" /></a>
  <a href="https://www.npmjs.com/package/@tt-a1i/mco"><img src="https://img.shields.io/npm/dm/@tt-a1i/mco?style=flat-square&color=cb3837" alt="npm downloads" /></a>
  <a href="https://github.com/mco-org/mco/stargazers"><img src="https://img.shields.io/github/stars/mco-org/mco?style=flat-square&color=f59e0b" alt="GitHub stars" /></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="License: MIT" /></a>
  <img src="https://img.shields.io/badge/Python-3.9%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.9+" />
  <img src="https://img.shields.io/badge/Providers-5%20built--in-7c3aed?style=flat-square" alt="5 built-in providers" />
</p>

<p align="center"><strong>Orchestrate AI Coding Agents. Any Prompt. Any Agent. Any IDE.</strong></p>

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
</table>

> One agent is a tool. Five agents are a team.
>
> Work like a Tech Lead: assign one task to multiple agents, run in parallel, compare outcomes before acting.

---

**Table of Contents**: [Quick Start](#quick-start) | [Why Multiple Agents?](#why-multiple-agents) | [Use Cases](#use-cases) | [Usage](#usage) | [How It Works](#how-it-works) | [Configuration](#configuration) | [License](#license)

---

## Quick Start

```bash
# Install (Python 3 required on PATH)
npm i -g @tt-a1i/mco

# Check your agents are ready
mco doctor

# Run your first multi-agent review
mco review \
  --repo . \
  --prompt "Review this repository for high-risk bugs and security issues." \
  --providers claude,codex,qwen
```

<details>
<summary><strong>Install from source</strong></summary>

```bash
git clone https://github.com/mco-org/mco.git
cd mco
python3 -m pip install -e .
```

</details>

---

## Why Multiple Agents?

No single AI model sees everything. Each has its own strengths and blind spots:

- **Agent A** spots a race condition in async code &mdash; but overlooks an SQL injection in the ORM layer.
- **Agent B** finds the injection immediately &mdash; but misses the race condition entirely.
- **Agent C** catches neither &mdash; but flags a subtle memory leak that the other two missed.

By running 3&ndash;5 agents in parallel, you get a **union of perspectives** rather than relying on any single model. MCO automates this workflow:

1. **Assign** &mdash; Give MCO a task and a list of agents
2. **Execute in parallel** &mdash; Wall-clock time &asymp; the slowest agent, not the sum
3. **Deduplicate** &mdash; Identical findings are merged with `detected_by` provenance
4. **Synthesize** &mdash; Optionally, one agent summarizes consensus and divergence

---

## Key Highlights

- **Parallel fan-out** &mdash; dispatch to multiple agents simultaneously, wait-all semantics
- **Any IDE, any agent** &mdash; works from Claude Code, Cursor, Trae, Copilot, Windsurf, or plain shell
- **Agent-to-agent orchestration** &mdash; agents can dispatch tasks to other agents through MCO
- **Dual mode** &mdash; `mco review` for structured findings, `mco run` for general tasks
- **Cross-agent deduplication** &mdash; identical findings merged automatically with source tracking
- **LLM synthesis** &mdash; `--synthesize` for consensus/divergence summary
- **CI/CD integration** &mdash; `--format sarif` for GitHub Code Scanning, `--format markdown-pr` for PR comments
- **Extensible** &mdash; adding a new agent CLI requires just three hooks: auth check, command builder, output normalizer

---

## Use Cases

| Scenario | Command | What happens |
|----------|---------|--------------|
| PR code review | `mco review --format markdown-pr` | Multiple agents review in parallel, output a PR-ready comment |
| Security scan in CI | `mco review --format sarif` | Results upload directly to GitHub Code Scanning |
| Architecture analysis | `mco run --providers claude,gemini,qwen` | Multi-perspective architecture assessment |
| Pre-deploy health check | `mco doctor --json` | Verify all agents are installed and authenticated |
| Consensus decision | `mco review --synthesize` | Summarize what agents agree on and where they diverge |

---

## Usage

### Review Mode

Structured code review with normalized findings (severity, category, evidence, recommendations):

```bash
mco review \
  --repo . \
  --prompt "Review for security vulnerabilities and performance issues." \
  --providers claude,codex,gemini,opencode,qwen \
  --json
```

### Run Mode

General-purpose multi-agent execution &mdash; no forced output schema:

```bash
mco run \
  --repo . \
  --prompt "Summarize the architecture of this project." \
  --providers claude,codex \
  --json
```

### Doctor

Verify agents are installed, reachable, and authenticated:

```bash
mco doctor
mco doctor --json
```

### Output Formats

| Format | Flag | Use case |
|--------|------|----------|
| Human-readable report | `--format report` (default) | Terminal reading |
| PR Markdown | `--format markdown-pr` | Post as GitHub PR comment |
| SARIF 2.1.0 | `--format sarif` | Upload to GitHub Code Scanning |
| Machine JSON | `--json` | Downstream automation |

### Agent-Friendly CLI

MCO is fully self-describing. Any AI agent can learn the interface by running `mco -h`:

> *"Use mco to dispatch a security review to Claude and Codex, and a performance analysis to Gemini and Qwen &mdash; run them in parallel."*

The agent reads the help output, composes the commands, and orchestrates the workflow autonomously.

---

## How It Works

```
You (or your IDE agent)
     |
     v
  mco review / mco run
     |
     +---> Claude Code  ---+
     +---> Codex CLI       |
     +---> Gemini CLI      +---> Deduplicate --> Synthesize --> Output
     +---> OpenCode        |
     +---> Qwen Code    ---+
                                |
                      +---------+---------+
                      v         v         v
                    JSON      SARIF   Markdown-PR
                 (stdout)   (CI/CD)  (PR comment)
```

Each provider runs as an independent subprocess through a uniform adapter contract:

1. **Detect** &mdash; check binary presence and auth status
2. **Run** &mdash; spawn CLI process with prompt, capture stdout/stderr
3. **Poll** &mdash; monitor output progress for activity detection
4. **Cancel** &mdash; SIGTERM/SIGKILL on stall timeout or hard deadline
5. **Normalize** &mdash; extract structured findings from raw output

Execution model is **wait-all**: one provider's failure never blocks others. Transient errors are retried automatically with exponential backoff.

---

## Works with OpenClaw

Running [OpenClaw](https://github.com/open-claw/open-claw) on your machine? It can use MCO as its multi-agent backbone:

> *"Use mco to run a security review on this repo with Claude, Codex, and Gemini. Synthesize the results."*

OpenClaw reads `mco -h`, learns the CLI, and orchestrates the entire workflow autonomously. This works the same way from **Claude Code, Cursor, Trae, Copilot, Windsurf**, or any agent that can run shell commands.

---

## Configuration

<details>
<summary><strong>Key Runtime Flags</strong></summary>

MCO is zero-config by default. Override behavior with CLI flags:

| Flag | Default | Description |
|------|---------|-------------|
| `--providers` | `claude,codex` | Comma-separated provider list |
| `--stall-timeout` | `900` | Cancel when no output progress (seconds) |
| `--review-hard-timeout` | `1800` | Hard deadline for review mode; `0` disables |
| `--max-provider-parallelism` | `0` | `0` = full parallelism |
| `--enforcement-mode` | `strict` | `strict` fails closed on unmet permissions |
| `--strict-contract` | off | Enforce strict findings JSON contract |
| `--format` | `report` | Output: `report`, `markdown-pr`, `sarif` |
| `--include-token-usage` | off | Per-provider and aggregate token usage |
| `--synthesize` | off | Extra LLM pass for consensus summary |
| `--synth-provider` | `claude` | Which provider runs synthesis |
| `--save-artifacts` | off | Write artifacts while keeping stdout delivery |

Run `mco review --help` for the full flag list.

</details>

<details>
<summary><strong>Result Modes &amp; Path Constraints</strong></summary>

**Result Modes:**

| Mode | Behavior |
|------|----------|
| `--result-mode stdout` | Print full result, skip artifact files (default) |
| `--result-mode artifact` | Write artifact files, print summary |
| `--result-mode both` | Write artifacts and print full result |

**Path Constraints:**

```bash
mco run \
  --repo . \
  --prompt "Analyze the adapter layer." \
  --providers claude,codex \
  --allow-paths runtime,scripts \
  --target-paths runtime/adapters \
  --enforcement-mode strict
```

</details>

<details>
<summary><strong>Exit Codes</strong></summary>

| Code | Meaning |
|------|---------|
| `0` | Success |
| `2` | FAIL / input / config / runtime error |
| `3` | INCONCLUSIVE (review mode only, with `--strict-contract`) |

</details>

<details>
<summary><strong>Artifacts</strong></summary>

When artifact writing is enabled (`--save-artifacts` or `--result-mode artifact/both`):

```
reports/review/<task_id>/
  summary.md          # Human-readable summary
  decision.md         # PASS / FAIL / ESCALATE / PARTIAL
  findings.json       # Aggregated normalized findings
  run.json            # Machine-readable execution metadata
  providers/          # Per-provider result JSON
  raw/                # Raw stdout/stderr logs
```

</details>

---

## License

MIT &mdash; see [LICENSE](./LICENSE)
