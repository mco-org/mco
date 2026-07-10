# Provider Permission Matrix (`v0.1.x`)

This document freezes provider permission-key behavior for `mco run` / `mco review` in `v0.1.x`.

MCO first resolves `execution_mode`, then translates it into provider permission keys. Defaults are `write` for `run` and `read_only` for `review`; `yolo` is never implicit. Provider-specific overrides are merged on top.

## Global Enforcement Semantics

- `enforcement_mode=strict` (default):
  - if config requests unsupported permission keys for a provider, that provider fails closed with `reason=permission_enforcement_failed`.
- `enforcement_mode=best_effort`:
  - unsupported permission keys are dropped before adapter execution.
  - provider continues with only supported keys.

## Matrix

| Provider | `supported_permission_keys()` | `read_only` | `write` | `yolo` |
|---|---|---|---|---|
| `claude` | `["permission_mode"]` | `plan` | `acceptEdits` | `bypassPermissions` |
| `codex` | `["sandbox", "approval_policy", "bypass"]` | `read-only`, approvals never | `workspace-write`, approvals never | dangerous bypass flag |
| `gemini` | `["approval_mode"]` | `plan` | `auto_edit` | `yolo` |
| `opencode` | `["agent_mode", "auto"]` | `plan`, no auto approval | `build --auto` | `build --auto` (broadest CLI profile) |
| `qwen` | `["approval_mode"]` | `plan` | `auto-edit` | `yolo` |
| `hermes` | `["yolo"]` | unsupported | unsupported | `--yolo` |
| `pi` | `["tool_profile"]` | read/search/list tools | adds write/edit | adds bash |
| `copilot` | `["access"]` | deny write and shell | allow write, deny shell | `--allow-all` |
| `grok` | `["permission_mode", "approval_mode"]` | `plan` | `acceptEdits` | `bypassPermissions` |
| `cursor` | `["mode", "force", "sandbox"]` | ask mode, sandbox enabled | agent force, sandbox enabled | agent force, sandbox disabled |

## Strict vs Best-Effort Examples

Given config:

```json
{
  "policy": {
    "enforcement_mode": "strict",
    "provider_permissions": {
      "gemini": { "sandbox": "workspace-write" }
    }
  }
}
```

- `strict`: `gemini` fails with `permission_enforcement_failed`.
- `best_effort`: `sandbox` is dropped (since unsupported), `gemini` still runs.

## Important Boundary

- `allow_paths` is orchestrator-level validation, not OS-kernel sandboxing.
- Real process sandboxing/isolation remains provider-specific.
- `write` means “can modify project files”, not identical isolation across vendors. MCO uses the narrowest provider-native profile that still permits normal coding work.
- Hermes oneshot auto-bypasses approvals. MCO therefore fails closed for Hermes under `read_only` and `write` instead of claiming a boundary Hermes cannot enforce.
- OpenCode currently exposes no separate mode broader than `build --auto`; its `write` and `yolo` mappings are therefore identical.
- Pi is the strongest tool-granular mapping: `write` enables file write/edit but withholds bash; `yolo` adds bash.
- ACP permission flags are currently auditable only where the ACP adapter exposes matching permission keys. Strict mode fails closed when a requested execution profile cannot be enforced.
