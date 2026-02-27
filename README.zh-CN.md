# MCO

<p align="left">
  <img src="./docs/assets/logos/mco-logo.svg" alt="MCO Logo" width="520" />
</p>

**MCO — 编排 AI 编程 Agent。任意提示词，任意 Agent，任意 IDE。**

[English](./README.md) | 简体中文

## MCO 是什么

MCO（Multi-CLI Orchestrator）是一个中立的 AI 编程 Agent 编排层。它将提示词并行分发给多个 Agent CLI，汇总执行结果，直接返回结构化 JSON。不绑定任何厂商，不改变你的工作流。

MCO 设计为被调用方 Agent 驱动 — 来自 Claude Code、Cursor、Trae、Copilot、Windsurf 或任何 AI IDE。调用方 Agent 自行组织上下文、分配任务，通过 MCO 将工作并行扇出到多个 Agent。Agent 之间也可以互相调度：Claude Code 可以通过 MCO 分发任务给 Codex 和 Gemini，反之亦然。

## 核心特性

- **并行扇出** — 同时分发到多个 Agent，wait-all 语义
- **任意 IDE，任意 Agent** — 在 Claude Code、Cursor、Trae、Copilot、Windsurf 或命令行中使用
- **Agent 互相调度** — Agent 之间可以通过 MCO 互相分发任务
- **进度驱动超时** — Agent 自由跑完，仅在长时间无输出时取消
- **双模式** — `mco review` 结构化代码审查，`mco run` 通用任务执行
- **可扩展适配器** — 统一接口适配任意 CLI Agent，不限于内置 provider
- **机器可读输出** — JSON 结果直接返回 stdout，便于下游自动化

## 内置 Provider

| Provider | CLI | 状态 |
|----------|-----|------|
| Claude Code | `claude` | 已支持 |
| Codex CLI | `codex` | 已支持 |
| Gemini CLI | `gemini` | 已支持 |
| OpenCode | `opencode` | 已支持 |
| Qwen Code | `qwen` | 已支持 |

适配器架构可扩展 — 添加新的 Agent CLI 只需实现三个钩子：认证检查、命令构建、输出标准化。

## 为什么要多 Agent？

没有任何一个 AI 模型能看到所有问题。每个模型有各自的训练数据、推理风格和盲区。只用一个 Agent 做代码审查，你得到的是一个视角 — 它漏掉的，你也漏掉了。

**代码审查**是最能体现差异的场景。实际使用中：

- 一个 Agent 发现了异步代码中的竞态条件，却忽略了 ORM 层的 SQL 注入。
- 另一个立刻定位了注入问题，却完全没注意到竞态条件。
- 第三个两个都没发现，但找到了资源清理路径中一个隐蔽的内存泄漏，而前两个对此毫无察觉。

这不是假设 — 不同模型确实擅长不同的事。有的长于安全分析，有的擅长逻辑流，有的对性能模式更敏感。并行跑 3-5 个 Agent 审查同一份代码，你得到的是**视角的并集**而非交集。结果比你挑任何单一 Agent 都更全面。

MCO 让这件事变得实际可行：一条命令，所有 Agent 同时跑，结果聚合到一份 findings 报告。额外开销几乎为零 — 总耗时约等于最慢的那个 Agent，而不是所有 Agent 的总和。

这个原则不限于代码审查：

- **架构分析** — 不同 Agent 暴露不同的设计风险和取舍
- **Bug 排查** — 更广的代码路径和边界条件覆盖
- **重构评估** — 多视角评判变更的影响范围和安全性

问题不是"哪个 AI Agent 最好" — 而是"为什么只用一个？"

## 快速开始

通过 npm 安装（需要系统有 Python 3）：

```bash
npm i -g @tt-a1i/mco
```

或从源码安装：

```bash
git clone https://github.com/mco-org/mco.git
cd mco
python3 -m pip install -e .
```

运行第一次多 Agent 审查：

```bash
mco review \
  --repo . \
  --prompt "Review this repository for high-risk bugs and security issues." \
  --providers claude,codex,qwen
```

### Agent 友好的 CLI

MCO 的 CLI 完全自描述。运行 `mco -h` 或 `mco review -h` 即可看到分组参数、默认值和用法示例 — 全在终端里。这意味着任何能执行 shell 命令的 AI Agent 都可以通过阅读帮助输出自主学会使用 MCO，无需文档，无需预训练。

实际使用中，你只需要告诉 IDE 里的 Agent 你想要什么：

> "用 mco 把安全审查分发给 Claude 和 Codex，性能分析分发给 Gemini 和 Qwen — 并行执行。"

Agent 读取 `mco -h`，理解参数，组装命令，自主编排整个流程。你描述意图，Agent 处理剩下的一切。

## 使用方式

### Review 模式

结构化代码审查，输出标准化的 findings（含严重级别、分类、证据、建议）。

```bash
mco review \
  --repo . \
  --prompt "Review for security vulnerabilities and performance issues." \
  --providers claude,codex,gemini,opencode,qwen \
  --json
```

### Run 模式

通用多 Agent 任务执行，不强制输出格式，provider 自由完成任务。

```bash
mco run \
  --repo . \
  --prompt "Summarize the architecture of this project." \
  --providers claude,codex \
  --json
```

### 结果模式

| 模式 | 行为 |
|------|------|
| `--result-mode stdout` | 完整结果输出到 stdout，不写产物文件（默认） |
| `--result-mode artifact` | 写产物文件，输出摘要 |
| `--result-mode both` | 既写产物又输出完整结果 |

使用 `--save-artifacts` 可在保持 stdout 返回的同时写入产物。

### 路径约束

限制 agent 可访问的文件范围：

```bash
mco run \
  --repo . \
  --prompt "Analyze the adapter layer." \
  --providers claude,codex \
  --allow-paths runtime,scripts \
  --target-paths runtime/adapters \
  --enforcement-mode strict
```

## 默认值与参数覆盖

MCO 默认零配置可用。直接运行即可，按需通过命令行参数覆盖行为。

### 关键运行参数

| 参数 | 默认值 | 说明 |
|------|--------|------|
| `--providers` | `claude,codex` | 逗号分隔 provider 列表 |
| `--stall-timeout` | `900` | 无输出进展超过此时间才取消（秒） |
| `--review-hard-timeout` | `1800` | review 模式硬截止；`0` = 禁用 |
| `--max-provider-parallelism` | `0` | `0` = 选中 provider 全并行 |
| `--enforcement-mode` | `strict` | 权限不满足时 fail-closed |
| `--strict-contract` | 关闭 | 强制 findings JSON 契约（review 模式） |
| `--provider-timeouts` | 未设置 | provider 级 stall timeout 覆盖（`provider=seconds`） |
| `--provider-permissions-json` | 未设置 | provider 权限映射 JSON（见下方） |
| `--save-artifacts` | 关闭 | 在默认 stdout 模式下同时写入产物 |
| `--task-id` | 自动生成 | 稳定的任务标识符，用于产物路径 |
| `--artifact-base` | `reports/review` | 产物输出基础目录 |

默认 provider 权限：

| Provider | 权限 Key | 默认值 |
|----------|----------|--------|
| `claude` | `permission_mode` | `plan` |
| `codex` | `sandbox` | `workspace-write` |

示例：

```bash
mco review \
  --repo . \
  --prompt "Review for bugs." \
  --providers claude,codex,qwen \
  --save-artifacts \
  --stall-timeout 900 \
  --review-hard-timeout 1800 \
  --max-provider-parallelism 0 \
  --provider-timeouts qwen=900,codex=900
```

运行 `mco review --help` 查看完整参数列表。

## 退出码

| 退出码 | 含义 |
|--------|------|
| `0` | 成功 |
| `2` | FAIL / 输入 / 配置 / 运行时错误 |
| `3` | INCONCLUSIVE（仅 review 模式，启用 `--strict-contract` 时） |

## 工作原理

```
Cursor / Trae / Copilot / Claude Code / 命令行
         │
         ▼
      mco run / mco review
         │
         ├─> Claude Code  ─┐
         ├─> Codex CLI     ├─> 聚合 ─> JSON（可选产物）
         ├─> Gemini CLI    │
         ├─> OpenCode      │
         └─> Qwen Code   ──┘
```

调用方 Agent（或用户）传入提示词和 provider 列表调用 `mco`，MCO 并行扇出到所有选中的 Agent，等待全部完成。

每个 provider 通过统一的适配器契约作为独立子进程运行：

1. **Detect** — 检测二进制文件和认证状态
2. **Run** — 启动 CLI 进程，传入提示词，捕获 stdout/stderr
3. **Poll** — 监控进程状态 + 输出字节增长，判断活跃度
4. **Cancel** — stall timeout 或硬截止时 SIGTERM/SIGKILL
5. **Normalize** — 从原始输出中提取结构化 findings

执行模型是 **wait-all**：单个 provider 超时或失败不会中断其他 provider。

### 重试与容错

- 瞬态错误（超时、限流、网络抖动）自动重试，指数退避（默认重试 1 次）。
- 单个 provider 失败不影响其他 provider。
- 每次调用都会真实执行 provider 并返回新输出（不复用结果缓存）。

### 在 Claude Code 内运行

MCO 在启动 provider 子进程前会自动清理 `CLAUDECODE` 环境变量，可以安全地在 Claude Code 会话中运行 `mco`。

## 产物结构

当启用产物写入（`--save-artifacts` 或 `--result-mode artifact/both`）时，会生成：

```
reports/review/<task_id>/
  summary.md          # 人类可读摘要
  decision.md         # PASS / FAIL / ESCALATE / PARTIAL
  findings.json       # 聚合后的标准化 findings（review 模式）
  run.json            # 机器可读执行元数据
  providers/          # 各 provider 结果 JSON
  raw/                # 原始 stdout/stderr 日志
```

## 许可证

UNLICENSED
