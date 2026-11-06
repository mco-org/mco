# Agent CLI compatibility — 2026-11-07

This audit targets the latest stable releases available on the audit date. It does not promise compatibility with future CLI changes. Validation used isolated installations on macOS arm64; the user's global CLI installations and configuration were not upgraded. Claude Code was excluded from live requests; its offline regression tests remain enabled.

## Version and live-validation matrix

| Agent | Audited release | Live result through MCO |
|---|---|---|
| Antigravity | 1.5.2 | Headless answer and file reading passed. Explicit `yolo` created a file with the expected bytes. `write` can stop when a command needs approval; it is not silently elevated. |
| Pi | 1.5.0 | Explicit provider/model routing, file reading and `write` passed. A failed default endpoint also exercised the corrected error/retry handling. |
| OpenCode | 2.2.5 | CLI started with the updated flags. Configured routes returned authentication errors; the official free route returned HTTP 429 (quota exhausted). Successful inference is not verified in this environment. |
| Hermes | v0.23.0 source release | Current headless gateway path was exercised. After installing the release's optional SDK in the isolated environment, the configured local model endpoint refused connections. Successful inference is not verified. The tag archive reports `vunknown` because it has no Git metadata. |
| Kimi Code | 2.5.2 | Headless answer, file reading and `write` passed. The read-only profile exposed only read/search tools and did not create a requested forbidden file. Codex→Kimi chain and Kimi run→debate→synthesis also passed. |
| Codex | 0.167.0 | Headless answer, file reading and sandboxed `write` passed. Nonfatal MCP startup diagnostics did not discard the answer. |
| Grok Build | 1.0.77 | After login, file reading and explicit `yolo` file writing passed. A headless command refusal reproduced a zero-exit false success; MCO now reports that refusal as failure. |

Successful file-write checks compared the generated file to the fixture byte for byte and confirmed that the original fixture was unchanged. Each task used a disposable directory and a bounded timeout. These small tasks verify integration behavior; they are not a quality, speed, or security benchmark.

## Automated validation

- Python 3.11 with the optional MCP dependency: 528 tests, 526 passed and 2 Windows-only tests skipped.
- Node: 20 tests, 19 passed and 1 Windows-only test skipped.
- Skill format and package/runtime version alignment passed.
- npm and wheel packaging/install smoke checks passed, including installed Kimi profile resolution.

## Integration coverage

- Kimi registration, CLI/MCP selection, model overrides, session answer extraction, tool profiles, and npm/wheel resources are covered by offline tests.
- Pi and Hermes retain the configured model provider through the CLI, MCP, parallel invocations, chain, debate, and synthesis; explicit invocation models remain authoritative.
- JSONL decoding preserves Unicode line and paragraph separators inside answer strings. Pi error, cancellation, exhausted retries, and token-limit truncation are failures, even when its JSON-mode process exits zero.
- Codex nonzero exits remain failures. Grok's documented headless permission-refusal diagnostic is a failure even when its process exits zero. Grok does not expose reliable structured permission-denial records; this deliberately conservative check can also flag a run that later recovered with another tool.
- File-backed stage inputs are independent of ambient-context configuration. Read-only debate/synthesis cannot fall back to Hermes's unrestricted mode.
- Package tests install npm and wheel artifacts outside the source tree and resolve both Kimi profiles from the installed package before constructing read/write commands.

Native ACP support is unchanged. Kimi uses the shim fallback under `--transport acp`; this audit does not claim a new native ACP implementation. Provider-native permissions and tool allowlists do not constitute an MCO OS sandbox. Kimi profiles do not disable arbitrary installed hooks or plugin initialization.

## Reproduce

Install and authenticate the selected CLI independently, then run against a disposable repository:

```sh
mco review --repo /path/to/fixture --providers kimi \
  --prompt 'Read fixture.txt and return its contents. Do not modify files.' \
  --invocation-hard-timeout 90 --review-hard-timeout 100 --json

mco run --repo /path/to/fixture --providers pi --execution-mode write \
  --provider-models-json '{"pi":{"provider":"YOUR_PROVIDER","model":"YOUR_MODEL"}}' \
  --prompt 'Copy fixture.txt to result.txt using file tools only.' \
  --invocation-hard-timeout 90 --review-hard-timeout 100 --json
```

Use `read_only` for reading. Hermes requires an explicit `yolo` selection; Antigravity and Grok `write` may refuse commands that need interactive approval. Do not automatically retry these refusals with elevated permissions. For reproducible Antigravity tests, `AGY_CLI_DISABLE_AUTO_UPDATE=true` disables its updater.

## Official sources

- [Antigravity releases](https://github.com/google-antigravity/antigravity-cli/releases), [execution modes](https://antigravity.google/docs/cli/modes/), [headless execution](https://antigravity.google/docs/cli/headless/).
- [Pi releases](https://github.com/earendil-works/pi/releases), [CLI](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/cli.md), [JSON protocol](https://github.com/earendil-works/pi/blob/main/packages/coding-agent/docs/json.md).
- [OpenCode v2.2.5](https://github.com/anomalyco/opencode/releases/tag/v2.2.5), [v2 commands](https://dev.opencode.ai/v2/docs/cli/commands/), [plugin behavior](https://dev.opencode.ai/v2/docs/cli/plugins/).
- [Hermes v0.23.0](https://github.com/NousResearch/hermes-agent/releases/tag/v0.23.0), [gateway CLI source](https://github.com/NousResearch/hermes-agent/blob/v0.23.0/hermes_cli/gateway_chat.py).
- [Kimi Code CLI](https://moonshotai.github.io/kimi-code/en/reference/kimi-command), [tool profiles](https://moonshotai.github.io/kimi-code/en/customization/agents), [migration from Python CLI](https://moonshotai.github.io/kimi-code/en/guides/migration).
- [Codex v0.167.0](https://github.com/openai/codex/releases), [noninteractive execution](https://developers.openai.com/codex/noninteractive).
- [Grok CLI reference](https://docs.x.ai/build/cli/reference), [headless execution](https://docs.x.ai/build/cli/headless-scripting), [permissions](https://docs.x.ai/build/features/permissions).
