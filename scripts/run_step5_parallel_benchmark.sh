#!/usr/bin/env bash
set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATE_STR="$(date +%F)"
OUT_DIR="$ROOT_DIR/reports/adapter-contract/$DATE_STR"
mkdir -p "$OUT_DIR"
TEMPLATE_PATH="$ROOT_DIR/docs/templates/step5-benchmark-report.md.tpl"
PROVIDERS="${1:-claude,codex,gemini,opencode,qwen,hermes,pi}"

PROMPT="Smoke benchmark for parallel review. No tools. Return a concise natural-language answer."
RUN_TAG="$(date +%Y%m%d%H%M%S)"
SERIAL_TASK_ID="bench-step5-serial-$RUN_TAG"
PARALLEL_TASK_ID="bench-step5-parallel-$RUN_TAG"

run_case() {
  local label="$1"
  local parallelism="$2"
  local task_id="$3"
  local stdout_log="$OUT_DIR/step5-${label}.stdout.log"
  local stderr_log="$OUT_DIR/step5-${label}.stderr.log"
  local result_json="$OUT_DIR/step5-${label}.result.json"

  local started ended duration exit_code
  started="$(date +%s)"
  set +e
  "$ROOT_DIR/mco" review \
    --repo "$ROOT_DIR" \
    --prompt "$PROMPT" \
    --providers "$PROVIDERS" \
    --save-artifacts \
    --task-id "$task_id" \
    --max-provider-parallelism "$parallelism" \
    --json >"$stdout_log" 2>"$stderr_log"
  exit_code=$?
  set -e
  ended="$(date +%s)"
  duration=$((ended - started))

  local payload_line
  payload_line="$(tail -n 1 "$stdout_log" | tr -d '\r')"
  if printf '%s' "$payload_line" | jq -e . >/dev/null 2>&1; then
    printf '%s\n' "$payload_line" | jq \
      --arg benchmark_case "$label" \
      --argjson max_provider_parallelism "$parallelism" \
      --argjson wall_time_seconds "$duration" \
      --argjson command_exit_code "$exit_code" \
      --arg stdout_log "$stdout_log" \
      --arg stderr_log "$stderr_log" \
      '. + {
        benchmark_case: $benchmark_case,
        max_provider_parallelism: $max_provider_parallelism,
        wall_time_seconds: $wall_time_seconds,
        command_exit_code: $command_exit_code,
        stdout_log: $stdout_log,
        stderr_log: $stderr_log
      }' >"$result_json"
  else
    jq -n \
      --arg benchmark_case "$label" \
      --argjson max_provider_parallelism "$parallelism" \
      --argjson wall_time_seconds "$duration" \
      --argjson command_exit_code "$exit_code" \
      --arg parse_error "missing_json_payload" \
      --arg stdout_log "$stdout_log" \
      --arg stderr_log "$stderr_log" \
      '{
        benchmark_case: $benchmark_case,
        max_provider_parallelism: $max_provider_parallelism,
        wall_time_seconds: $wall_time_seconds,
        command_exit_code: $command_exit_code,
        parse_error: $parse_error,
        stdout_log: $stdout_log,
        stderr_log: $stderr_log
      }' >"$result_json"
  fi

  local invocations_total successful_count failed_count
  invocations_total="$(jq -r '((.outputs // []) | length)' "$result_json")"
  successful_count="$(jq -r '[.outputs // [] | .[] | select(.status == "success")] | length' "$result_json")"
  failed_count="$(jq -r '[.outputs // [] | .[] | select(.status != "success")] | length' "$result_json")"

  jq \
    --argjson invocations_total "$invocations_total" \
    --argjson successful_count "$successful_count" \
    --argjson failed_count "$failed_count" \
    '. + {
      invocations_total: $invocations_total,
      successful_count: $successful_count,
      failed_count: $failed_count,
      success_rate: (if $invocations_total > 0 then ($successful_count / $invocations_total) else null end)
    }' "$result_json" >"$result_json.tmp" && mv "$result_json.tmp" "$result_json"
  echo "$result_json"
}

SERIAL_JSON="$(run_case "serial" "1" "$SERIAL_TASK_ID")"
PARALLEL_JSON="$(run_case "full-parallel" "0" "$PARALLEL_TASK_ID")"

SUMMARY_JSON="$OUT_DIR/step5-parallel-benchmark-summary.json"
REPORT_MD="$OUT_DIR/step5-parallel-benchmark.md"

jq -n \
  --arg generated_at "$(date -u +%FT%TZ)" \
  --arg providers "$PROVIDERS" \
  --arg prompt "$PROMPT" \
  --arg serial_result "$SERIAL_JSON" \
  --arg parallel_result "$PARALLEL_JSON" \
  --slurpfile serial "$SERIAL_JSON" \
  --slurpfile parallel "$PARALLEL_JSON" \
  '{
    generated_at: $generated_at,
    providers: $providers,
    prompt: $prompt,
    serial_result_path: $serial_result,
    parallel_result_path: $parallel_result,
    serial: $serial[0],
    parallel: $parallel[0],
    benchmark_ok: (($serial[0].command_exit_code // 1) == 0 and ($parallel[0].command_exit_code // 1) == 0),
    metric_note: "invocations_total counts declared invocations; successful_count and failed_count report operational outcomes.",
    latency_reduction_percent: (
      if ($serial[0].wall_time_seconds // 0) > 0 and ($parallel[0].wall_time_seconds // 0) >= 0
      then ((($serial[0].wall_time_seconds - $parallel[0].wall_time_seconds) / $serial[0].wall_time_seconds) * 100)
      else null
      end
    )
  }' >"$SUMMARY_JSON"

SERIAL_EXIT="$(jq -r '.serial.command_exit_code // 999' "$SUMMARY_JSON")"
PARALLEL_EXIT="$(jq -r '.parallel.command_exit_code // 999' "$SUMMARY_JSON")"

python3 "$ROOT_DIR/scripts/render_step5_report.py" \
  --template "$TEMPLATE_PATH" \
  --summary-json "$SUMMARY_JSON" \
  --output "$REPORT_MD"

echo "Step5 benchmark report: $REPORT_MD"
echo "Step5 benchmark summary: $SUMMARY_JSON"

if [ "$SERIAL_EXIT" -ne 0 ] || [ "$PARALLEL_EXIT" -ne 0 ]; then
  exit 1
fi
exit 0
