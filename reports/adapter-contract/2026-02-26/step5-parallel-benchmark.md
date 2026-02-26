# Step5 Full-Parallel Benchmark (2026-02-26)

## Scenario

- Config: `/Users/tsk/multi-cli-orchestrator/mco.step3-baseline.json`
- Prompt: smoke contract-only task
- Serial run: `--max-provider-parallelism 1`
- Full-parallel run: `--max-provider-parallelism 0`

## Results

1. Serial
   - task_id: `bench-step5-serial-20260226153246`
   - wall time: `156s`
   - parse: `5` success / `0` failure
   - parse success rate: `5/5 (100.0%)`
   - effective findings: `5`
   - zero-finding providers: `0`
   - command exit: `0`
2. Full parallel
   - task_id: `bench-step5-parallel-20260226153246`
   - wall time: `68s`
   - parse: `5` success / `0` failure
   - parse success rate: `5/5 (100.0%)`
   - effective findings: `5`
   - zero-finding providers: `0`
   - command exit: `0`

## Delta

- Latency reduction (serial -> full parallel): `56.4%`
- Metrics note: parse_success_count measures contract parse success; effective_findings_count measures canonical findings retained after schema/drop filtering.
- Summary JSON: `/Users/tsk/multi-cli-orchestrator/reports/adapter-contract/2026-02-26/step5-parallel-benchmark-summary.json`
