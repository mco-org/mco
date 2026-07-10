# Provider Permission Matrix (`v0.1.x`)

This document freezes provider permission-key behavior for `mco run` / `mco review` in `v0.1.x`.

## Global Enforcement Semantics

- `enforcement_mode=strict` (default):
  - if config requests unsupported permission keys for a provider, that provider fails closed with `reason=permission_enforcement_failed`.
- `enforcement_mode=best_effort`:
  - unsupported permission keys are dropped before adapter execution.
  - provider continues with only supported keys.

## Matrix

| Provider | `supported_permission_keys()` | Effective adapter mapping | Default behavior if key omitted |
|---|---|---|---|
| `claude` | `["permission_mode"]` | `permission_mode` -> `claude --permission-mode <value>` | `permission_mode=plan` |
| `codex` | `["sandbox"]` | `sandbox` -> `codex exec --sandbox <value>` | `sandbox=workspace-write` |
| `gemini` | `[]` | No permission-key mapping in adapter | N/A |
| `opencode` | `[]` | No permission-key mapping in adapter | N/A |
| `qwen` | `[]` | No permission-key mapping in adapter | N/A |
| `hermes` | `[]` | No permission-key mapping; oneshot approval behavior is provider-controlled | Approval prompts are bypassed |
| `pi` | `[]` | No permission-key mapping; adapter locks tools to `read,grep,find,ls` | Read-only tool allowlist; extensions disabled |
| `copilot` | `[]` | No permission-key mapping; adapter always passes `--allow-all-tools --no-ask-user` | Approval bypass |
| `grok` | `["approval_mode"]` | `always-approve` adds `grok --always-approve`; `ask` keeps the CLI default | Approval prompts remain enabled |
| `cursor` | `["mode", "force"]` | `ask` / `plan` -> `agent --mode <value>`; `agent` uses full agent mode; `force=true` adds `--force` | `mode=ask`, `force=false` (read-only) |

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
- An empty permission-key set means MCO cannot tune that provider's permissions; it does not mean the provider is read-only.
- Gemini and Qwen pass `-y`; Hermes oneshot and Copilot bypass interactive approvals. Pi is the only provider with an adapter-enforced read-only tool allowlist.
- OpenCode runs in the selected repository but exposes no permission key through MCO; treat its isolation as provider-controlled.
- Grok can modify the workspace after tool approval; `approval_mode=always-approve` explicitly bypasses those prompts.
- Cursor defaults to read-only `ask` mode. `mode=agent` enables its full write/shell-capable agent mode; `force=true` additionally bypasses approvals.
