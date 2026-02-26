# MCO 文档索引

[English](./README.md) | 简体中文

## 先读这些
1. [multi-cli-orchestrator-proposal.md](./multi-cli-orchestrator-proposal.md)
2. [capability-research.md](./capability-research.md)
3. [notes.md](./notes.md)

## 门禁产物
1. [capability-probe-spec.md](./capability-probe-spec.md)
2. [adapter-contract-tests.md](./adapter-contract-tests.md)
3. [dry-run-plan.md](./dry-run-plan.md)
4. [implementation-gate-checklist.md](./implementation-gate-checklist.md)

## 接口冻结
1. [docs/implementation/step0-interface-freeze.md](./docs/implementation/step0-interface-freeze.md)
2. [docs/contracts/cli-json-v0.1.x.md](./docs/contracts/cli-json-v0.1.x.md)
3. [docs/contracts/provider-permissions-v0.1.x.md](./docs/contracts/provider-permissions-v0.1.x.md)

## 计划与跟踪
1. [task_plan.md](./task_plan.md)

## 发布说明
1. [CHANGELOG.md](./CHANGELOG.md)
2. [docs/releases/v0.1.2.md](./docs/releases/v0.1.2.md)
3. [docs/releases/v0.1.2.zh-CN.md](./docs/releases/v0.1.2.zh-CN.md)
4. [docs/releases/v0.1.1.md](./docs/releases/v0.1.1.md)
5. [docs/releases/v0.1.1.zh-CN.md](./docs/releases/v0.1.1.zh-CN.md)
6. [docs/releases/v0.1.0.md](./docs/releases/v0.1.0.md)
7. [docs/releases/v0.1.0.zh-CN.md](./docs/releases/v0.1.0.zh-CN.md)

## 统一 CLI（Step 2）
`mco review`：统一的审查入口。  
`mco run`：通用任务执行入口（不强制 findings schema）。

## 安装

npm 包装器（当前可用，系统需有 Python 3）：

```bash
npm i -g @tt-a1i/mco
mco --help
```

源码可编辑安装：

```bash
git clone https://github.com/tt-a1i/mco.git
cd mco
python3 -m pip install -e .
mco --help
```

Python 包（PyPI）：
- 目前尚未发布。
- 发布流程已就绪，待完成 PyPI Trusted Publisher 配置后开启。

快速开始：

```bash
./mco review \
  --repo . \
  --prompt "Review this repository for high-risk bugs and security issues." \
  --providers claude,codex
```

机器可读输出：

```bash
./mco review --repo . --prompt "Review for bugs." --providers claude,codex --json
```

仅 stdout 输出结果（不写 `summary.md/decision.md/findings.json/run.json`）：

```bash
./mco review --repo . --prompt "Review for bugs." --providers claude,codex --result-mode stdout --json
```

通用 run 模式：

```bash
./mco run --repo . --prompt "Summarize the current repo architecture." --providers claude,codex --json
```

配置文件（JSON）：

```json
{
  "providers": ["claude", "codex"],
  "artifact_base": "reports/review",
  "state_file": ".mco/state.json",
  "policy": {
    "timeout_seconds": 180,
    "stall_timeout_seconds": 900,
    "poll_interval_seconds": 1.0,
    "review_hard_timeout_seconds": 1800,
    "enforce_findings_contract": false,
    "max_retries": 1,
    "high_escalation_threshold": 1,
    "require_non_empty_findings": true,
    "max_provider_parallelism": 0,
    "allow_paths": [".", "runtime", "scripts"],
    "enforcement_mode": "strict",
    "provider_permissions": {
      "claude": {
        "permission_mode": "plan"
      },
      "codex": {
        "sandbox": "workspace-write"
      }
    },
    "provider_timeouts": {
      "claude": 300,
      "codex": 240,
      "qwen": 240
    }
  }
}
```

按配置运行：

```bash
./mco review --config ./mco.example.json --repo . --prompt "Review for bugs and security issues."
```

CLI 覆盖并发与超时：

```bash
./mco review \
  --repo . \
  --prompt "Review for bugs and security issues." \
  --providers claude,codex,gemini,opencode,qwen \
  --strict-contract \
  --max-provider-parallelism 2 \
  --stall-timeout 900 \
  --review-hard-timeout 1800 \
  --provider-timeouts qwen=900,codex=900
```

带路径硬约束的 run 模式：

```bash
./mco run \
  --repo . \
  --prompt "Compare adapter behaviors and return a short markdown summary." \
  --providers claude,codex \
  --allow-paths runtime,scripts \
  --target-paths runtime/adapters,runtime/review_engine.py \
  --enforcement-mode strict \
  --provider-permissions-json '{"codex":{"sandbox":"workspace-write"},"claude":{"permission_mode":"plan"}}' \
  --json
```

产物目录：
- `<artifact_base>/<task_id>/summary.md`
- `<artifact_base>/<task_id>/decision.md`
- `<artifact_base>/<task_id>/findings.json`
- `<artifact_base>/<task_id>/run.json`
- `<artifact_base>/<task_id>/providers/*.json`
- `<artifact_base>/<task_id>/raw/*.log`

`run.json` 审计字段：
- `effective_cwd`
- `allow_paths_hash`
- `permissions_hash`

说明：
- YAML 配置需要 `pyyaml`；否则使用 JSON 配置。
- review 提示词会附加 JSON finding 合同；是否强制由策略控制。
- 可用 `--strict-contract`（或配置 `policy.enforce_findings_contract=true`）开启严格合同。
- `run` 模式不强制 findings schema，聚焦执行与聚合。
- `result_mode=artifact`（默认）：写产物并输出简报。
- `result_mode=stdout`：输出 provider 结果，不写用户侧产物。
- `result_mode=both`：既写产物又输出 provider 结果。
- 执行模型为 `wait-all`：单 provider 失败/超时不会中断其它 provider。
- 超时是进度驱动：
  - `stall_timeout_seconds`：仅在长时间无输出进展时取消。
  - `review_hard_timeout_seconds`：仅 `review` 模式硬截止。
- `max_provider_parallelism=0`（或省略）表示全并行。
- `provider_timeouts` 为 provider 级 stall-timeout 覆盖项。
- `allow_paths` 与 `target_paths` 会对 `repo_root` 做越界校验。
- `enforcement_mode=strict`（默认）下，权限要求不满足会 fail-closed。

## Step5 性能脚本
用于产出串行 vs 全并行对比报告（写入 `reports/adapter-contract/<date>/`）：

```bash
./scripts/run_step5_parallel_benchmark.sh
```

生成的 summary JSON 包含：
- `providers_total`
- `parse_success_rate`
- `effective_findings_count`
- `zero_finding_provider_count`
