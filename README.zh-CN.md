# MCO

<p align="left">
  <img src="./docs/assets/logos/mco-logo.svg" alt="MCO Logo" width="520" />
</p>

**MCO — 一条提示词，五个 AI Agent，一份结果。**

[English](./README.md) | 简体中文

## MCO 是什么

MCO（Multi-CLI Orchestrator）是一个中立的编排层，将单条提示词并行分发给多个 AI 编程 Agent，汇总执行结果。不绑定任何厂商，不改变你的工作流。Fan-out、Wait-all、Collect。

你继续照常使用 Claude Code、Codex CLI、Gemini CLI、OpenCode、Qwen Code。MCO 负责把它们串联成统一的执行管线，提供结构化输出、进度驱动超时、可复现的产物。

## 核心特性

- **并行扇出** — 同时分发到所有 provider，wait-all 语义
- **进度驱动超时** — agent 自由跑完，仅在长时间无输出时取消
- **双模式** — `mco review` 结构化代码审查，`mco run` 通用任务执行
- **厂商中立** — 5 个 CLI 工具统一适配器契约，不偏向任何厂商
- **机器可读输出** — JSON 结果 + 每个 provider 独立产物树，便于下游自动化

## 支持的 Provider

| Provider | CLI | 状态 |
|----------|-----|------|
| Claude Code | `claude` | 已支持 |
| Codex CLI | `codex` | 已支持 |
| Gemini CLI | `gemini` | 已支持 |
| OpenCode | `opencode` | 已支持 |
| Qwen Code | `qwen` | 已支持 |

无需迁移项目，无需重学命令，无需绑定单一工具。

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
| `--idempotency-key` | 自动生成 | 相同 key 的重复运行返回缓存结果 |
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
prompt ─> MCO ─┬─> Claude Code  ─┐
               ├─> Codex CLI     ├─> 聚合 ─> JSON（可选产物）
               ├─> Gemini CLI    │
               ├─> OpenCode      │
               └─> Qwen Code   ──┘
```

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
- 使用相同 `--idempotency-key` 的重复运行直接返回缓存结果，不重新执行。

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
