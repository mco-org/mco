# Provider and permission reference

MCO ships ten built-in provider adapters. A provider must still be installed and authenticated independently before MCO can use it.

## Built-in providers

| Provider | Provider ID | CLI detection | Notes |
|----------|-------------|---------------|-------|
| Claude Code | `claude` | `claude` | Native permission modes |
| Codex CLI | `codex` | `codex` | Native sandbox and approval controls |
| Gemini CLI | `gemini` | `gemini` | Plan, auto-edit, and yolo approval modes |
| OpenCode | `opencode` | `opencode` | Plan/build agent modes |
| Qwen Code | `qwen` | `qwen` | Plan, auto-edit, and yolo approval modes |
| GitHub Copilot CLI | `copilot` | `copilot` | Read, write, and allow-all access profiles |
| Hermes | `hermes` | `hermes` | Oneshot execution bypasses approvals |
| Pi | `pi` | `pi` | Explicit tool allowlists |
| Grok Build | `grok` | `grok` | Plan, accept-edits, and bypass modes |
| Cursor CLI | `cursor` | `cursor` or `agent` | Ask, sandboxed-agent, and unsandboxed-agent profiles |

## Unified execution modes

| Provider | `read_only` | `write` | `yolo` |
|----------|-------------|---------|--------|
| Claude | `plan` | `acceptEdits` | `bypassPermissions` |
| Codex | read-only sandbox | workspace-write sandbox | bypass profile |
| Gemini | `plan` | `auto_edit` | `yolo` |
| OpenCode | plan agent | build agent | build with automatic actions |
| Qwen | `plan` | `auto-edit` | `yolo` |
| Copilot | read-only access | file-write access | allow-all access |
| Hermes | unsupported | unsupported | `--yolo` oneshot |
| Pi | read/grep/find/ls | adds write/edit | adds bash |
| Grok | `plan` | `acceptEdits` | `bypassPermissions` |
| Cursor | ask + sandbox | agent + sandbox | agent without sandbox |

Provider-specific overrides remain available through `--provider-permissions-json`. Strict enforcement fails closed when MCO cannot express a requested boundary.

`--allow-paths` validates the scope requested by MCO. It does not create an operating-system sandbox or override the underlying provider's capabilities.

## Provider selection

`mco run` and `mco review` require an explicit provider/model team:

```bash
mco review --providers claude,codex,pi --prompt "Review this repository."
```

For model-qualified dispatch, repeat `--agent`:

```bash
mco run --agent fast=pi:fast-model --agent careful=pi:careful-model --prompt "Compare these models."
```

If neither `--providers` nor `--agent` is supplied, MCO returns `provider_selection_required`. Calling Agents should ask the user rather than infer consent from installed binaries.

## Model discovery and routing

MCO normally preserves each CLI's configured default model.

```bash
mco agent models --providers codex,hermes,pi --json
```

Pin one configured model per provider for one run:

```bash
mco review \
  --providers codex,pi \
  --provider-models-json '{"codex":"gpt-5.4","pi":{"provider":"seal","model":"deepseek-v4-pro"}}' \
  --prompt "Review for bugs."
```

The model catalog is best-effort and depends on what each installed CLI exposes.

Model discovery may be incomplete. An incomplete catalog must not be treated as proof that a model-qualified invocation cannot be attempted; only a confirmed invalid model or provider configuration should fail fast.

## Context policy

Use `--provider-context-json` to control supported provider context surfaces:

```bash
mco run \
  --providers pi \
  --provider-context-json '{"pi":{"skills":"disabled","context_files":false}}' \
  --prompt "Analyze this repository."
```

Absent keys preserve the provider's own defaults. Unsupported keys fail closed in strict enforcement mode.

File-backed chain, debate, and synthesis context is a separate, read-only input surface: MCO copies complete prior-answer Markdown and its manifest into the stage `context/` directory, then grants read access only to that directory. It does not broaden repository or system write access. ACP permits reads there and rejects writes; Codex context runs force its read-only sandbox rather than granting a writable extra directory. A Provider that cannot read the context files records `context_file_unsupported` instead of silently omitting them.

## Risk inspection

Inspect default and effective provider risk before execution:

```bash
mco doctor --json
mco agent list --json
mco review --providers claude,pi --dry-run --json
```

Dry-run resolves provider presence, policy, risk, model routing, context policy, command templates, and artifact settings without starting provider processes.
