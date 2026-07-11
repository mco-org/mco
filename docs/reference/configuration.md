# Configuration and custom agents

MCO works without a config file once providers or model-qualified invocations are explicitly selected. Configuration is useful for project defaults, model routing, context policy, and custom agents.

## Runtime configuration

Runtime config is loaded in this order:

1. CLI arguments
2. Project `.mcorc.json`
3. Global `~/.mco/config.json`
4. Built-in defaults

Nested policy objects are deep-merged.

```json
{
  "providers": ["claude", "codex", "pi"],
  "transport": "shim",
  "policy": {
    "stall_timeout_seconds": 600,
    "enforcement_mode": "strict",
    "max_provider_parallelism": 3,
    "provider_models": {
      "codex": "gpt-5.4",
      "pi": {"provider": "seal", "model": "deepseek-v4-pro"}
    },
    "provider_context": {
      "pi": {"skills": "disabled", "context_files": false}
    },
    "perspectives": {
      "claude": "security",
      "codex": "performance"
    },
    "divide": "dimensions"
  }
}
```

`providers` supplies the `--providers` shorthand. Calling Agents should still confirm the provider/model team with the user instead of treating a discoverable binary as consent. Use repeatable `--agent [alias=]provider:model` when a task needs multiple models from one provider.

`perspectives` and `divide` are explicit coordination settings. A perspective adds a Provider prompt focus; `divide: "files"` partitions sorted regular files in the selected target scope without overlap, while `divide: "dimensions"` rotates fixed review lenses by invocation declaration order without changing target paths. They are visible in dry-run and never parse, rank, or rewrite Agent answers.

## Custom agent registry

Agent definitions are loaded in this order:

1. `.mco/agents.yaml`
2. `.mcorc.yaml`
3. `~/.mco/agents.yaml`

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

Inspect configured agents before execution:

```bash
mco agent list
mco agent check my-acp-agent
mco agent check my-ollama
```

## Registry transports

- `transport: shim` launches a command and decodes its provider transport into an opaque answer.
- `transport: acp` launches an ACP-compatible JSON-RPC process.
- `model: ...` creates an Ollama-backed adapter.

Temporary ACP agents can also be registered for one invocation:

```bash
mco run \
  --custom-agent mybot "mybot --acp" \
  --providers mybot \
  --prompt "Analyze this repository."
```

Registration does not select an invocation. The registered name must still appear in `--providers` or in an `--agent alias=name:model` declaration.

## Skill installation

The bundled `mco-cli` Skill is copied from the installed package into explicit calling-agent destinations:

```bash
mco skills read
mco skills status --json
mco skills sync --agent codex --agent claude-code
```

Skill synchronization never installs into every known agent implicitly. Use `mco doctor --skill-health --json` to inspect missing, matching, or drifted installations.
