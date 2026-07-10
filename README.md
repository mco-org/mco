<p align="center">
  <img src="https://raw.githubusercontent.com/mco-org/mco/main/docs/assets/brand/mco-cover-starry.jpg" alt="MCO — ten agent paths converging through a monumental M beneath a starry sky" width="100%" />
</p>

<h1 align="center">MCO</h1>

<p align="center"><strong>Orchestrate AI coding agents. Compare perspectives. Act with confidence.</strong></p>

<p align="center">
  <a href="https://www.npmjs.com/package/@tt-a1i/mco"><img src="https://img.shields.io/npm/v/@tt-a1i/mco?style=flat-square&color=cb3837&logo=npm&logoColor=white" alt="npm version" /></a>
  <a href="https://www.npmjs.com/package/@tt-a1i/mco"><img src="https://img.shields.io/npm/dm/@tt-a1i/mco?style=flat-square&color=cb3837" alt="npm downloads" /></a>
  <a href="https://github.com/mco-org/mco/stargazers"><img src="https://img.shields.io/github/stars/mco-org/mco?style=flat-square&color=f59e0b" alt="GitHub stars" /></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="MIT License" /></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
</p>

<p align="center">English · <a href="./README.zh-CN.md">简体中文</a></p>

MCO is a lightweight, CLI-first orchestration layer for AI coding agents. Give one task to the agents you choose, run them in parallel, and compare the results before you act.

Use MCO for code review, implementation, architecture analysis, CI checks, and any workflow where one model's blind spots matter.

It works from a terminal or from another coding agent such as Claude Code, Codex, Cursor, Copilot, Pi, or OpenClaw.

> MCO is actively maintained. For a browser workbench with persistent agent identity and a shared task graph, see [Hive](https://hivehq.dev).

## Quick start

Install the CLI and its bundled `mco-cli` Skill:

```bash
npx @tt-a1i/mco@latest install
```

Check the agents available on your machine:

```bash
mco doctor --json
```

Run a read-only multi-agent review:

```bash
mco review \
  --repo . \
  --prompt "Review this repository for high-risk bugs." \
  --providers claude,codex,pi
```

Run a coding task with workspace write access:

```bash
mco run \
  --repo . \
  --prompt "Implement the requested change and run the relevant tests." \
  --providers codex,pi \
  --execution-mode write
```

MCO never silently chooses a provider team. If `--providers` is missing, ask the user which agents to use.

## Why MCO

One agent gives you one perspective. MCO turns selected agents into a review or execution team:

1. **Choose** — explicitly select the agents for the task.
2. **Dispatch** — run them in parallel, chain their work, or divide the scope.
3. **Compare** — retain provider-level output and merge duplicate findings.
4. **Decide** — inspect evidence, consensus, disagreements, and failures before acting.

For structured reviews, MCO normalizes findings, preserves `detected_by` provenance, and assigns consensus levels. Agreement is evidence to investigate, not automatic truth.

## Built-in providers

| Provider | CLI | Provider ID |
|----------|-----|-------------|
| Claude Code | `claude` | `claude` |
| Codex CLI | `codex` | `codex` |
| Gemini CLI | `gemini` | `gemini` |
| OpenCode | `opencode` | `opencode` |
| Qwen Code | `qwen` | `qwen` |
| GitHub Copilot CLI | `copilot` | `copilot` |
| Hermes | `hermes` | `hermes` |
| Pi | `pi` | `pi` |
| [Grok Build](https://docs.x.ai/build/overview) | `grok` | `grok` |
| [Cursor CLI](https://cursor.com/docs/cli/overview) | `cursor` / `agent` | `cursor` |

Each provider CLI remains responsible for its own installation, authentication, model access, and native sandbox behavior.

## Common workflows

| Goal | Command |
|------|---------|
| General multi-agent task | `mco run --providers claude,codex --prompt "..."` |
| Structured code review | `mco review --providers claude,codex --prompt "..."` |
| Review current branch diff | `mco review --providers claude,codex --diff` |
| Preview without execution | `mco review --providers claude,pi --dry-run --json` |
| PR-ready Markdown | `mco review --providers claude,codex --format markdown-pr` |
| GitHub Code Scanning | `mco review --providers claude,codex --format sarif` |
| Live terminal progress | `mco review --providers claude,codex --stream live` |
| Machine-readable events | `mco review --providers claude,codex --stream jsonl` |
| Discover provider models | `mco agent models --providers codex,pi --json` |

Pin a model for one run without changing the provider CLI's default:

```bash
mco review \
  --providers codex,pi \
  --provider-models-json '{"codex":"gpt-5.4","pi":{"provider":"seal","model":"deepseek-v4-pro"}}' \
  --prompt "Review this repository for bugs."
```

## Permissions and safety

MCO translates one execution profile into each provider's native flags:

| Mode | Intended use | Default |
|------|--------------|---------|
| `read_only` | Inspect and review without workspace mutation | `mco review` |
| `write` | Create and edit workspace files | `mco run` |
| `yolo` | Use the provider's broadest bypass profile | Explicit opt-in only |

Important boundaries:

- `--allow-paths` validates MCO's requested scope; it is not an operating-system sandbox.
- Provider sandbox strength depends on the underlying CLI.
- Hermes oneshot bypasses approvals and therefore requires explicit `--execution-mode yolo`.
- ACP terminal access is a trusted-agent capability. Use isolation for untrusted agents or prompts.
- Run parallel writers in separate worktrees; do not let multiple agents edit one working tree concurrently.

See [Provider and permission reference](./docs/reference/providers.md) for the complete mapping.

## Use MCO from another agent

MCO's CLI is self-describing. A calling agent can read `mco -h`, ask which providers the user wants, preview the policy, and then execute.

> “Use MCO to run a security review with Claude and Codex, and an architecture review with Pi.”

The installer and runtime use two different selections:

- Installer `--agent` chooses which calling agents receive the MCO Skill.
- Runtime `--providers` chooses which agents execute the current task.

```bash
npx @tt-a1i/mco@latest install --agent codex --agent claude-code --yes
mco doctor --skill-health --json
```

## How it works

```text
You or a calling agent
        │
        ▼
  mco run / review
        │
        ├── Claude ──┐
        ├── Codex    │
        ├── Gemini   ├──► merge / consensus / synthesis ──► output
        ├── Pi       │
        └── ...   ───┘
                              │
                       JSON · SARIF · Markdown
```

Provider processes are isolated behind a shared adapter contract: detect, run, poll, cancel, and normalize. One provider failure does not discard successful provider results.

## Documentation

| Topic | Guide |
|-------|-------|
| Installation, first run, and common workflows | [Workflow guide](./docs/guides/workflows.md) |
| Providers, models, and permission mappings | [Provider reference](./docs/reference/providers.md) |
| CLI flags, outputs, artifacts, and exit codes | [CLI reference](./docs/reference/cli.md) |
| Config files and custom agents | [Configuration reference](./docs/reference/configuration.md) |
| Machine-readable error contract | [Error contract](./docs/contracts/errors-v0.1.x.md) |
| Provider permission contract | [Permission contract](./docs/contracts/provider-permissions-v0.1.x.md) |
| Release process | [RELEASING.md](./RELEASING.md) |
| Release history | [CHANGELOG.md](./CHANGELOG.md) |

Run `mco <command> --help` for the authoritative option list installed with your version.

## Development

```bash
git clone https://github.com/mco-org/mco.git
cd mco
python3 -m pip install -e .
python3 -m unittest discover -s tests -p 'test_*.py'
npm test
```

## License

MIT — see [LICENSE](./LICENSE).
