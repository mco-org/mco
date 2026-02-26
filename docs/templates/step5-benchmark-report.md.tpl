# Step5 Full-Parallel Benchmark ($date)

## Scenario

- Providers: `$providers`
- Prompt: smoke contract-only task
- Serial run: `--max-provider-parallelism 1`
- Full-parallel run: `--max-provider-parallelism 0`

## Results

1. Serial
   - task_id: `$serial_task_id`
   - wall time: `$serial_wall_time`
   - parse: `$serial_parse_success` success / `$serial_parse_failure` failure
   - parse success rate: `$serial_parse_ratio`
   - effective findings: `$serial_effective_findings`
   - zero-finding providers: `$serial_zero_finding_providers`
   - command exit: `$serial_exit_code`
2. Full parallel
   - task_id: `$parallel_task_id`
   - wall time: `$parallel_wall_time`
   - parse: `$parallel_parse_success` success / `$parallel_parse_failure` failure
   - parse success rate: `$parallel_parse_ratio`
   - effective findings: `$parallel_effective_findings`
   - zero-finding providers: `$parallel_zero_finding_providers`
   - command exit: `$parallel_exit_code`

## Delta

- Latency reduction (serial -> full parallel): `$latency_reduction`
- Metrics note: $metric_note
- Summary JSON: `$summary_json_path`
