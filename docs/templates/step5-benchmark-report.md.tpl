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
   - successful invocations: `$serial_success_count`
   - failed invocations: `$serial_failed_count`
   - success rate: `$serial_success_ratio`
   - command exit: `$serial_exit_code`
2. Full parallel
   - task_id: `$parallel_task_id`
   - wall time: `$parallel_wall_time`
   - successful invocations: `$parallel_success_count`
   - failed invocations: `$parallel_failed_count`
   - success rate: `$parallel_success_ratio`
   - command exit: `$parallel_exit_code`

## Delta

- Latency reduction (serial -> full parallel): `$latency_reduction`
- Metrics note: $metric_note
- Summary JSON: `$summary_json_path`
