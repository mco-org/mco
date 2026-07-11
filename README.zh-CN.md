<p align="center">
  <img src="https://raw.githubusercontent.com/mco-org/mco/main/docs/assets/brand/mco-cover-starry.jpg" alt="MCO——十条 Agent 路径在星空下汇聚穿过宏伟的 M" width="100%" />
</p>

<h1 align="center">MCO</h1>

<p align="center"><strong>编排 AI Coding Agent，比较多方视角，更有把握地行动。</strong></p>

<p align="center">
  <a href="https://www.npmjs.com/package/@tt-a1i/mco"><img src="https://img.shields.io/npm/v/@tt-a1i/mco?style=flat-square&color=cb3837&logo=npm&logoColor=white" alt="npm version" /></a>
  <a href="https://www.npmjs.com/package/@tt-a1i/mco"><img src="https://img.shields.io/npm/dm/@tt-a1i/mco?style=flat-square&color=cb3837" alt="npm downloads" /></a>
  <a href="https://github.com/mco-org/mco/stargazers"><img src="https://img.shields.io/github/stars/mco-org/mco?style=flat-square&color=f59e0b" alt="GitHub stars" /></a>
  <a href="./LICENSE"><img src="https://img.shields.io/badge/License-MIT-22c55e?style=flat-square" alt="MIT License" /></a>
  <img src="https://img.shields.io/badge/Python-3.10%2B-3776AB?style=flat-square&logo=python&logoColor=white" alt="Python 3.10+" />
</p>

<p align="center"><a href="./README.md">English</a> · 简体中文</p>

MCO 是一个轻量、CLI 优先的 AI Coding Agent 编排层。把同一个任务交给你明确选择的 Agent 和模型，并行执行，比较原始回答，再决定下一步。

它适合代码审查、功能实现、架构分析、CI 检查，以及任何需要减少单一模型盲区的工作流。

既可以直接从终端使用，也可以由 Claude Code、Codex、Cursor、Copilot、Pi 或 OpenClaw 等上层 Agent 调用。

> MCO 正在持续维护。如果你需要持久 Agent 身份、共享任务图和浏览器工作台，可以搭配使用 [Hive](https://hivehq.dev)。

## 快速开始

安装 CLI 和内置 `mco-cli` Skill：

```bash
npx @tt-a1i/mco@latest install
```

检查本机可用的 Agent：

```bash
mco doctor --json
```

运行一次只读的多 Agent 审查：

```bash
mco review \
  --repo . \
  --prompt "审查这个仓库中的高风险 bug。" \
  --providers claude,codex,pi
```

运行允许修改工作区的编码任务：

```bash
mco run \
  --repo . \
  --prompt "实现需求并运行相关测试。" \
  --providers codex,pi \
  --execution-mode write
```

MCO 不会静默替你选择 Provider 或模型。缺少 `--providers` 和 `--agent` 时，应先询问用户希望使用哪些 Agent 和模型。

## 为什么使用 MCO

一个 Agent 只提供一个视角。MCO 把你选中的 Agent 组织成审查或执行团队：

1. **选择** — 明确指定本次任务的 Agent。
2. **分发** — 并行执行、串行挑战，或按范围分工。
3. **比较** — 保留每个 invocation 的完整原始回答和运行状态。
4. **决策** — 检查证据、分歧和失败，再采取行动。

MCO 将回答正文视为不透明内容，不会从自然语言中推断 finding、严重度、置信度、共识或自动决策。

需要明确协调审查时，可用 `--perspectives-json` 为 Provider 添加 prompt 侧重点；`--divide files` 会将选定作用域内排序后的文件按声明顺序轮转分配且不重叠，`--divide dimensions` 会按声明顺序轮转审查维度且不改变 target paths。这些选择会在 dry-run 中显示，只改变 prompt 或作用域，返回的 invocation 回答仍保持原始内容。

## 内置 Provider

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

各 Provider CLI 仍然独立负责安装、认证、模型权限和原生沙箱行为。

## 常用工作流

| 目标 | 命令 |
|------|------|
| 通用多 Agent 任务 | `mco run --providers claude,codex --prompt "..."` |
| 原始回答代码审查 | `mco review --providers claude,codex --prompt "..."` |
| 比较多个模型 | `mco run --agent fast=pi:model-a --agent careful=pi:model-b --prompt "..."` |
| 只预览、不执行 | `mco review --providers claude,pi --dry-run --json` |
| 实时终端进度 | `mco review --providers claude,codex --stream live` |
| 机器可读事件流 | `mco review --providers claude,codex --stream jsonl` |
| 文件化 chain | `mco run --agent first=pi:model-a --agent next=pi:model-b --chain --result-mode artifact` |
| debate 与 synthesis | `mco review --providers claude,codex --debate --synthesize --result-mode both` |
| 查看 Provider 模型 | `mco agent models --providers codex,pi --json` |

仅为本次运行固定模型，不修改 Provider CLI 的默认配置：

```bash
mco review \
  --providers codex,pi \
  --provider-models-json '{"codex":"gpt-5.4","pi":{"provider":"seal","model":"deepseek-v4-pro"}}' \
  --prompt "审查这个仓库中的 bug。"
```

## 权限与安全

MCO 会把统一执行档位转换成各 Provider 的原生参数：

| 档位 | 用途 | 默认场景 |
|------|------|----------|
| `read_only` | 只读检查和审查 | `mco review` |
| `write` | 新建和编辑工作区文件 | `mco run` |
| `yolo` | 使用 Provider 最宽的绕过权限 | 仅显式选择 |

重要边界：

- `--allow-paths` 只校验 MCO 请求的作用域，不是操作系统级沙箱。
- 实际沙箱强度取决于底层 Provider CLI。
- Hermes oneshot 会绕过审批，因此必须显式使用 `--execution-mode yolo`。
- ACP terminal 属于可信 Agent 能力；不可信 Agent 或提示词应在隔离环境中运行。
- MCO 不创建或管理 worktree。用户显式选择并行写入时，应通过不重叠的 `--target-paths` 划分范围，并提前提示编辑冲突风险。

完整映射见 [Provider 与权限参考](./docs/reference/providers.md)。

## 由其他 Agent 调用 MCO

MCO CLI 是自描述的。调用方 Agent 可以读取 `mco -h`，询问用户选择哪些 Provider，预览策略，然后执行任务。

> “使用 MCO，让 Claude 和 Codex 做安全审查，让 Pi 做架构审查。”

安装器与运行时存在两个不同的选择：

- 安装器 `--agent` 决定把 MCO Skill 安装给哪些调用方 Agent。
- 运行时 `--providers` 决定哪些 Agent 执行当前任务。

```bash
npx @tt-a1i/mco@latest install --agent codex --agent claude-code --yes
mco doctor --skill-health --json
```

## 工作原理

```text
用户或调用方 Agent
        │
        ▼
  mco run / review
        │
        ├── Claude ──┐
        ├── Codex    │
        ├── Gemini   ├──► 原始回答 / 文件化阶段 ──► 输出
        ├── Pi       │
        └── ...   ───┘
                              │
                       文本 · JSON · JSONL · Markdown 产物
```

Provider 进程统一封装在适配器契约后：detect、run、poll、cancel、传输解码。单个 invocation 失败不会丢弃其他 Provider 的成功回答。

## 文档

| 主题 | 文档 |
|------|------|
| 安装、首次运行和常见工作流 | [工作流指南](./docs/guides/workflows.md) |
| Provider、模型与权限映射 | [Provider 参考](./docs/reference/providers.md) |
| CLI 参数、输出、产物与退出码 | [CLI 参考](./docs/reference/cli.md) |
| 配置文件与自定义 Agent | [配置参考](./docs/reference/configuration.md) |
| 机器可读错误契约 | [错误契约](./docs/contracts/errors-v0.1.x.md) |
| Invocation 与 artifact 契约 | [Invocation 契约](./docs/contracts/invocation-runtime-v1.md) |
| Provider 权限契约 | [权限契约](./docs/contracts/provider-permissions-v0.1.x.md) |
| 发布流程 | [RELEASING.md](./RELEASING.md) |
| 版本历史 | [CHANGELOG.md](./CHANGELOG.md) |

运行 `mco <command> --help` 查看当前安装版本的权威参数列表。

## 开发

```bash
git clone https://github.com/mco-org/mco.git
cd mco
python3 -m pip install -e .
python3 -m unittest discover -s tests -p 'test_*.py'
npm test
```

## 许可证

MIT — 见 [LICENSE](./LICENSE)。
