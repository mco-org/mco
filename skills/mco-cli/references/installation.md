# Installation and Skill sync

## One-command setup

```bash
npx @tt-a1i/mco@latest install
```

Supported flags:

```text
--agent <id>       Repeatable calling-agent target
--yes              Accept detected defaults without prompts
--skip-skills      Install/upgrade CLI only
--dry-run          Print the exact plan without mutation or network install
--json             Stable JSON envelope
```

Examples:

```bash
npx @tt-a1i/mco@latest install --agent claude-code --agent codex --yes
npx @tt-a1i/mco@latest install --dry-run --json
```

## Runtime Skill commands

```bash
mco skills read [--json]
mco skills status [--json]
mco skills sync --agent claude-code --agent codex [--dry-run] [--json]
```

Rules:

- Installer `--agent` selects calling agents that receive the `mco-cli` Skill.
- Runtime `--providers` selects agents that execute an MCO task.
- Skill sync requires explicit `--agent`; it never installs into every known agent implicitly.
- Skill installation source is the installed npm package root, always copied with `--copy`.

## Manual CLI-only install

```bash
npm i -g @tt-a1i/mco
```

Then sync the Skill explicitly:

```bash
mco skills sync --agent codex --agent claude-code
```
