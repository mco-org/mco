#!/usr/bin/env bash
set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATE_STR="$(date +%F)"
OUT_DIR="$ROOT_DIR/reports/adapter-contract/$DATE_STR"
mkdir -p "$OUT_DIR"

RAW_LOG="$OUT_DIR/runtime-gh-raw.log"
REPORT_MD="$OUT_DIR/runtime-gh-report.md"
RESULT_JSON="$OUT_DIR/runtime-gh-result.json"

set +e
python3 -m unittest discover -s "$ROOT_DIR/tests" -p "test_*.py" >"$RAW_LOG" 2>&1
TEST_EXIT=$?
set -e

RAN_LINE="$(rg '^Ran [0-9]+ tests? in ' "$RAW_LOG" || true)"
if [ -z "$RAN_LINE" ]; then
  RAN_LINE="Ran 0 tests in 0.000s"
fi

if [ "$TEST_EXIT" -eq 0 ]; then
  GH_STATUS="PASS"
else
  GH_STATUS="FAIL"
fi

{
  echo "# Runtime Gate Report ($DATE_STR)"
  echo
  echo "- Status: $GH_STATUS"
  echo "- $RAN_LINE"
  echo "- Raw log: \`$RAW_LOG\`"
  echo
  echo "## Gate Mapping"
  echo "- A1 (adapter contract tests for 5 providers): covered by \`tests/test_adapter_contracts.py\`"
  echo "- R2 (unified review flow + strict JSON contract gate): covered by \`tests/test_review_engine.py\`"
  echo "- CFG (review config loading defaults/overrides): covered by \`tests/test_config.py\`"
  echo "- S0 (interface + artifact contract freeze): covered by \`tests/test_contract_freeze.py\`"
  echo "- G (error taxonomy): covered by \`tests/test_error_taxonomy.py\`"
  echo "- H (retry semantics): covered by \`tests/test_retry_semantics.py\`"
} > "$REPORT_MD"

jq -n \
  --arg date "$DATE_STR" \
  --arg status "$GH_STATUS" \
  --arg ran "$RAN_LINE" \
  --arg raw "$RAW_LOG" \
  '{
    date: $date,
    status: $status,
    ran: $ran,
    raw_log: $raw
  }' > "$RESULT_JSON"

echo "Runtime G/H status: $GH_STATUS"
echo "Report: $REPORT_MD"

exit "$TEST_EXIT"
