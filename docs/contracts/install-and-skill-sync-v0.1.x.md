# Install and Skill Sync Contract (v0.1.x)

This document freezes the installer and runtime Skill-sync behavior introduced in the MCO npm wrapper.

## One-command install

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
npx @tt-a1i/mco@latest install --agent codex --dry-run --json
```

## Runtime Skill commands

```bash
mco skills read [--json]
mco skills status [--json]
mco skills sync --agent AGENT [--agent AGENT ...] [--dry-run] [--json]
```

Rules:

- `skills sync` requires at least one explicit `--agent`.
- Non-interactive and dry-run installer flows require explicit `--agent` selection unless `--yes` accepts detected agents; selection failures happen before global installation.
- Installer `--agent` selects calling agents that receive the `mco-cli` Skill.
- Runtime `--providers` selects agents that execute an MCO task.
- `--yes` accepts only detected agents; it does not mean “all possible agents”.
- No detected agents plus no `--agent` returns `agent_selection_required`.
- Skill installation source is the installed npm package root, not GitHub `main`.
- The Skills CLI is invoked argv-only with mandatory `--copy`.

## JSON success envelope

```json
{
  "ok": true,
  "action": "install",
  "cli": {"status": "installed", "version": "0.10.x"},
  "skills": {
    "status": "installed",
    "name": "mco-cli",
    "agents": ["claude-code", "codex"]
  },
  "doctor": {"status": "completed", "overall_ok": false}
}
```

`doctor.overall_ok=false` is informational during installation because provider CLIs may not yet be authenticated. It must not make installation fail.

## Failure semantics

### Partial success

If CLI installation succeeds but Skill sync fails:

- The CLI remains installed/upgraded.
- The installer exits non-zero.
- The response includes a retry command such as `mco skills sync --agent codex`.

### No detected agents

In non-interactive mode without `--agent`:

- The installer may install/upgrade the CLI.
- Skill sync is skipped.
- The response uses subtype `agent_selection_required`.

### Skills CLI unavailable or network failure

- Report the child exit code and stderr.
- Do not roll back a successful CLI install.
- Exit non-zero with retry guidance.

### Idempotency

Re-running the installer should:

- Keep or upgrade the CLI to the exact npm package version.
- Resynchronize the Skill copy without creating duplicate files.

## Dry-run guarantees

`--dry-run` must not:

- Run `npm install`
- Invoke the tested `npx skills@1.5.15`
- Invoke global `mco`
- Write files

It returns the exact planned argv arrays instead.

## Non-goals

- Standalone PyInstaller/native binaries
- Automatic provider login or credential configuration
- Background auto-updater
- Writing directly to every vendor-specific Skill directory from MCO
