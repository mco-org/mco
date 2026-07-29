#!/usr/bin/env bash
set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DATE_STR="$(date +%F)"
BASE_DIR="$ROOT_DIR/docs/probes/$DATE_STR"
OS_NAME="$(uname -s)"

case "$OS_NAME" in
  Darwin) TARGET_OS="macos" ;;
  Linux) TARGET_OS="linux" ;;
  *) TARGET_OS="windows" ;;
esac

mkdir -p "$BASE_DIR"

providers=(claude codex gemini opencode qwen hermes pi copilot grok cursor)
DEFAULT_TIMEOUT_SECONDS=45
PROBE_CWD="${PROBE_CWD:-${HOME:-$ROOT_DIR}}"
CLAUDE_BIN="$(command -v claude)"
CODEX_BIN="$(command -v codex)"
GEMINI_BIN="$(command -v gemini)"
OPENCODE_BIN="$(command -v opencode)"
QWEN_BIN="$(command -v qwen)"
HERMES_BIN="$(command -v hermes)"
PI_BIN="$(command -v pi)"
COPILOT_BIN="$(command -v copilot)"
GROK_BIN="$(command -v grok)"
CURSOR_BIN="$(command -v agent)"

provider_version() {
  case "$1" in
    claude) "$CLAUDE_BIN" --version | head -n1 | sed 's/ (Claude Code)//' ;;
    codex) "$CODEX_BIN" --version | tail -n1 | awk '{print $2}' ;;
    gemini) "$GEMINI_BIN" --version 2>&1 | tail -n1 ;;
    opencode) "$OPENCODE_BIN" --version | head -n1 ;;
    qwen) "$QWEN_BIN" --version | head -n1 ;;
    hermes) "$HERMES_BIN" --version | head -n1 ;;
    pi) "$PI_BIN" --version | head -n1 ;;
    copilot) "$COPILOT_BIN" --version | head -n1 ;;
    grok) "$GROK_BIN" --version | head -n1 ;;
    cursor) "$CURSOR_BIN" --version | head -n1 ;;
  esac
}

json_result() {
  local provider="$1"
  local version="$2"
  local capability="$3"
  local status="$4"
  local reason="$5"
  local stdout_path="$6"
  local stderr_path="$7"
  local parsed_path="$8"
  local result_path="$9"
  jq -n \
    --arg provider "$provider" \
    --arg version "$version" \
    --arg os "$TARGET_OS" \
    --arg capability "$capability" \
    --arg status "$status" \
    --arg reason "$reason" \
    --arg stdout_path "$stdout_path" \
    --arg stderr_path "$stderr_path" \
    --arg parsed_path "$parsed_path" \
    --arg timestamp "$(date -u +%FT%TZ)" \
    '{
      provider: $provider,
      provider_version: $version,
      os: $os,
      capability: $capability,
      status: $status,
      reason: $reason,
      artifacts: {
        stdout_path: $stdout_path,
        stderr_path: $stderr_path,
        parsed_output_path: $parsed_path
      },
      timestamp: $timestamp
    }' > "$result_path"
}

run_with_timeout() {
  local timeout_seconds="$1"
  shift
  python3 - "$timeout_seconds" "$@" <<'PY'
import subprocess
import sys

timeout = float(sys.argv[1])
command = sys.argv[2:]
if not command:
    sys.exit(1)

try:
    process = subprocess.Popen(command)
except Exception:
    sys.exit(1)

try:
    rc = process.wait(timeout=timeout)
except subprocess.TimeoutExpired:
    process.terminate()
    try:
        process.wait(timeout=2)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()
    sys.exit(142)

sys.exit(rc)
PY
}

run_probe() {
  local provider="$1"
  local capability="$2"
  local cmd="$3"
  local parser="$4"

  local cap_dir="$BASE_DIR/$provider/$capability"
  local raw_dir="$cap_dir/raw"
  mkdir -p "$raw_dir"

  local stdout_path="$raw_dir/stdout.log"
  local stderr_path="$raw_dir/stderr.log"
  local parsed_path="$cap_dir/parsed.json"
  local result_path="$cap_dir/result.json"

  local version
  version="$(provider_version "$provider")"

  run_with_timeout "$DEFAULT_TIMEOUT_SECONDS" bash -c "$cmd" >"$stdout_path" 2>"$stderr_path"
  local ec=$?

  local status="FAIL"
  local reason="command_failed_exit_${ec}"

  if [ "$ec" -eq 0 ]; then
    if [ -n "$parser" ]; then
      # shellcheck disable=SC2086
      bash -c "$parser" >"$parsed_path" 2>>"$stderr_path"
      local pec=$?
      if [ "$pec" -eq 0 ]; then
        status="PASS"
        reason="probe_passed"
      else
        status="FAIL"
        reason="parse_or_validation_failed_${pec}"
      fi
    else
      status="PASS"
      reason="probe_passed"
      : > "$parsed_path"
    fi
  else
    if [ "$ec" -eq 142 ]; then
      reason="command_timeout"
    fi
    : > "$parsed_path"
  fi

  json_result "$provider" "$version" "$capability" "$status" "$reason" "$stdout_path" "$stderr_path" "$parsed_path" "$result_path"
}

schema_file="$BASE_DIR/schema_c2.json"
cat > "$schema_file" <<'EOF'
{
  "type": "object",
  "properties": {
    "probe": { "type": "string", "const": "c2" },
    "ok": { "type": "boolean", "const": true }
  },
  "required": ["probe", "ok"],
  "additionalProperties": false
}
EOF

C2_JSON_JQ_FILTER='def is_c2: .probe? == "c2" and .ok? == true;
  ([.[] | .. | objects | select(is_c2)] | length > 0)
  or ([.[] | .. | strings | fromjson? | .. | objects | select(is_c2)] | length > 0)'

for provider in "${providers[@]}"; do
  mkdir -p "$BASE_DIR/$provider"
done

# C0 probes
run_probe "claude" "C0" "'$CLAUDE_BIN' auth status" ""
run_probe "codex" "C0" "'$CODEX_BIN' login status" ""
run_probe "gemini" "C0" "'$GEMINI_BIN' -p 'Reply with exactly OK'" "rg -q '(^|[^A-Za-z])OK([^A-Za-z]|$)' '$BASE_DIR/gemini/C0/raw/stdout.log'"
run_probe "opencode" "C0" "'$OPENCODE_BIN' auth list" ""
run_probe "qwen" "C0" "'$QWEN_BIN' 'Reply with exactly OK' --output-format text --auth-type qwen-oauth" ""
run_probe "hermes" "C0" "'$HERMES_BIN' status" ""
run_probe "pi" "C0" "'$PI_BIN' --list-models" ""
run_probe "copilot" "C0" "'$COPILOT_BIN' -p 'Reply with exactly OK' -s --no-ask-user --deny-tool=write --deny-tool=shell" ""
run_probe "grok" "C0" "'$GROK_BIN' models" ""
run_probe "cursor" "C0" "'$CURSOR_BIN' status" ""

# C1 probes
run_probe "claude" "C1" "'$CLAUDE_BIN' -p --permission-mode plan --output-format text 'Reply with exactly OK'" ""
run_probe "codex" "C1" "'$CODEX_BIN' --ask-for-approval never exec --skip-git-repo-check -C '$PROBE_CWD' --sandbox read-only --json 'Reply with exactly OK'" "rg -q '(^|[^A-Za-z])OK([^A-Za-z]|$)' '$BASE_DIR/codex/C1/raw/stdout.log'"
run_probe "gemini" "C1" "'$GEMINI_BIN' -p 'Reply with exactly OK' --approval-mode plan" "rg -q '(^|[^A-Za-z])OK([^A-Za-z]|$)' '$BASE_DIR/gemini/C1/raw/stdout.log'"
run_probe "opencode" "C1" "'$OPENCODE_BIN' run --agent plan 'Reply with exactly OK' --format json --dir '$PROBE_CWD'" "(! rg -q '(^|\\s)Error:' '$BASE_DIR/opencode/C1/raw/stdout.log') && (! rg -q '(^|\\s)Error:' '$BASE_DIR/opencode/C1/raw/stderr.log')"
run_probe "qwen" "C1" "'$QWEN_BIN' 'Reply with exactly OK' --output-format json --auth-type qwen-oauth --approval-mode plan" ""
run_probe "hermes" "C1" "'$HERMES_BIN' -z 'Reply with exactly OK'" "rg -q '(^|[^A-Za-z])OK([^A-Za-z]|$)' '$BASE_DIR/hermes/C1/raw/stdout.log'"
run_probe "pi" "C1" "'$PI_BIN' -p --mode json --no-session --no-context-files --no-skills --no-extensions --tools read,grep,find,ls 'Reply with exactly OK'" "rg -q '(^|[^A-Za-z])OK([^A-Za-z]|$)' '$BASE_DIR/pi/C1/raw/stdout.log'"
run_probe "copilot" "C1" "'$COPILOT_BIN' -p 'Reply with exactly OK' -s --no-ask-user --deny-tool=write --deny-tool=shell" "rg -q '(^|[^A-Za-z])OK([^A-Za-z]|$)' '$BASE_DIR/copilot/C1/raw/stdout.log'"
run_probe "grok" "C1" "'$GROK_BIN' --no-auto-update -p 'Reply with exactly OK' --output-format plain --permission-mode plan" "rg -q '(^|[^A-Za-z])OK([^A-Za-z]|$)' '$BASE_DIR/grok/C1/raw/stdout.log'"
run_probe "cursor" "C1" "'$CURSOR_BIN' -p 'Reply with exactly OK' --output-format text --mode ask --sandbox enabled" "rg -q '(^|[^A-Za-z])OK([^A-Za-z]|$)' '$BASE_DIR/cursor/C1/raw/stdout.log'"

# C2 probes
run_probe "claude" "C2" \
  "'$CLAUDE_BIN' -p --permission-mode plan --output-format json --json-schema \"\$(cat '$schema_file')\" 'Return JSON object {\"probe\":\"c2\",\"ok\":true}'" \
  "jq -e '[.. | objects | select(has(\"probe\") and has(\"ok\")) | select(.probe==\"c2\" and .ok==true)] | length > 0' '$BASE_DIR/claude/C2/raw/stdout.log'"

codex_msg_file="$BASE_DIR/codex/C2/raw/last_message.json"
run_probe "codex" "C2" \
  "rm -f '$codex_msg_file'; '$CODEX_BIN' --ask-for-approval never exec --skip-git-repo-check -C '$PROBE_CWD' --sandbox read-only --json --output-schema '$schema_file' --output-last-message '$codex_msg_file' 'Return JSON object with probe=c2 and ok=true'" \
  "jq -e '[.. | objects | select(has(\"probe\") and has(\"ok\")) | select(.probe==\"c2\" and .ok==true)] | length > 0' '$codex_msg_file'"

run_probe "gemini" "C2" \
  "'$GEMINI_BIN' -p 'Return JSON object {\"probe\":\"c2\",\"ok\":true}' --output-format json --approval-mode plan" \
  "jq -s -e '$C2_JSON_JQ_FILTER' '$BASE_DIR/gemini/C2/raw/stdout.log'"

run_probe "opencode" "C2" \
  "'$OPENCODE_BIN' run --agent plan 'Return JSON object {\"probe\":\"c2\",\"ok\":true}' --format json --dir '$PROBE_CWD'" \
  "jq -s -e '$C2_JSON_JQ_FILTER' '$BASE_DIR/opencode/C2/raw/stdout.log'"

run_probe "qwen" "C2" \
  "'$QWEN_BIN' 'Return JSON object {\"probe\":\"c2\",\"ok\":true}' --output-format json --auth-type qwen-oauth --approval-mode plan" \
  "jq -s -e '$C2_JSON_JQ_FILTER' '$BASE_DIR/qwen/C2/raw/stdout.log'"

run_probe "hermes" "C2" \
  "'$HERMES_BIN' -z 'Return JSON object {\"probe\":\"c2\",\"ok\":true}'" \
  "jq -s -e '$C2_JSON_JQ_FILTER' '$BASE_DIR/hermes/C2/raw/stdout.log'"

run_probe "pi" "C2" \
  "'$PI_BIN' -p --mode json --no-session --no-context-files --no-skills --no-extensions --tools read,grep,find,ls 'Return JSON object {\"probe\":\"c2\",\"ok\":true}'" \
  "jq -s -e '$C2_JSON_JQ_FILTER' '$BASE_DIR/pi/C2/raw/stdout.log'"

run_probe "copilot" "C2" \
  "'$COPILOT_BIN' -p 'Return JSON object {\"probe\":\"c2\",\"ok\":true}' --output-format json --no-ask-user --deny-tool=write --deny-tool=shell" \
  "jq -s -e '$C2_JSON_JQ_FILTER' '$BASE_DIR/copilot/C2/raw/stdout.log'"

run_probe "grok" "C2" \
  "'$GROK_BIN' --no-auto-update -p 'Return JSON object {\"probe\":\"c2\",\"ok\":true}' --output-format json --json-schema \"\$(cat '$schema_file')\" --permission-mode plan" \
  "jq -s -e '$C2_JSON_JQ_FILTER' '$BASE_DIR/grok/C2/raw/stdout.log'"

run_probe "cursor" "C2" \
  "'$CURSOR_BIN' -p 'Return JSON object {\"probe\":\"c2\",\"ok\":true}' --output-format json --mode ask --sandbox enabled" \
  "jq -s -e '$C2_JSON_JQ_FILTER' '$BASE_DIR/cursor/C2/raw/stdout.log'"

# C3 sample probe for Qwen (stream-json)
run_probe "qwen" "C3" \
  "'$QWEN_BIN' 'Output two short thoughts.' --output-format stream-json --auth-type qwen-oauth" \
  "jq -s -e 'length >= 2' '$BASE_DIR/qwen/C3/raw/stdout.log'"

LOCK_FILE="$BASE_DIR/lock-summary.yaml"
aggregate_exit_code=0
{
  echo "provider_locks:"
  for provider in "${providers[@]}"; do
    version="$(provider_version "$provider")"
    c0="$(jq -r '.status' "$BASE_DIR/$provider/C0/result.json" 2>/dev/null || echo FAIL)"
    c1="$(jq -r '.status' "$BASE_DIR/$provider/C1/result.json" 2>/dev/null || echo FAIL)"
    c2="$(jq -r '.status' "$BASE_DIR/$provider/C2/result.json" 2>/dev/null || echo FAIL)"
    if [ "$c0" = "PASS" ] && [ "$c1" = "PASS" ] && [ "$c2" = "PASS" ]; then
      lock_version="$version"
      gate_status="ENABLED"
    else
      lock_version="BLOCKED"
      gate_status="BLOCKED"
      aggregate_exit_code=1
    fi
    echo "  $provider:"
    echo "    min_version:"
    echo "      $TARGET_OS: \"$lock_version\""
    echo "    required_capability_status:"
    echo "      C0: $c0"
    echo "      C1: $c1"
    echo "      C2: $c2"
    echo "    gate_status: $gate_status"
  done
} > "$LOCK_FILE"

SUMMARY_MD="$BASE_DIR/summary.md"
{
  echo "# Capability Probe Summary ($DATE_STR)"
  echo
  echo "| Provider | Version | C0 | C1 | C2 | C3 | Gate |"
  echo "| --- | --- | --- | --- | --- | --- | --- |"
  for provider in "${providers[@]}"; do
    version="$(provider_version "$provider")"
    c0="$(jq -r '.status' "$BASE_DIR/$provider/C0/result.json" 2>/dev/null || echo FAIL)"
    c1="$(jq -r '.status' "$BASE_DIR/$provider/C1/result.json" 2>/dev/null || echo FAIL)"
    c2="$(jq -r '.status' "$BASE_DIR/$provider/C2/result.json" 2>/dev/null || echo FAIL)"
    c3="$(jq -r '.status' "$BASE_DIR/$provider/C3/result.json" 2>/dev/null || echo SKIP)"
    if [ "$c0" = "PASS" ] && [ "$c1" = "PASS" ] && [ "$c2" = "PASS" ]; then
      gate="ENABLED"
    else
      gate="BLOCKED"
    fi
    echo "| $provider | $version | $c0 | $c1 | $c2 | $c3 | $gate |"
  done
  echo
  echo "Artifacts root: \`$BASE_DIR\`"
} > "$SUMMARY_MD"

echo "Done. Probe artifacts in: $BASE_DIR"
exit "$aggregate_exit_code"
