#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PACK_DIR="$(mktemp -d)"
INSTALL_DIR="$(mktemp -d)"
SMOKE_HOME="$(mktemp -d)"
SMOKE_NPM_PREFIX="$(mktemp -d)"
SMOKE_NPM_CACHE="$(mktemp -d)"
WHEEL_DIR="$(mktemp -d)"
WHEEL_VENV="$(mktemp -d)"
trap 'rm -rf "$PACK_DIR" "$INSTALL_DIR" "$SMOKE_HOME" "$SMOKE_NPM_PREFIX" "$SMOKE_NPM_CACHE" "$WHEEL_DIR" "$WHEEL_VENV"' EXIT

export HOME="$SMOKE_HOME"
export npm_config_prefix="$SMOKE_NPM_PREFIX"
export npm_config_cache="$SMOKE_NPM_CACHE"

npm test
python3 scripts/check_skill_format.py skills/mco-cli
python3 scripts/check_package_version.py

npm pack --dry-run >/dev/null
npm pack --pack-destination "$PACK_DIR" >/dev/null
TARBALL="$(ls "$PACK_DIR"/tt-a1i-mco-*.tgz)"
tar -tzf "$TARBALL" > "$PACK_DIR/contents.txt"
for required_path in \
  package/bin/mco.js \
  package/mco \
  package/runtime/adapters/copilot.py \
  package/runtime/adapters/cursor.py \
  package/runtime/provider_risk.py \
  package/runtime/skill_health.py \
  package/runtime/skill_manager.py \
  package/runtime/data/skill_calling_agents.json \
  package/scripts/install-wizard.js \
  package/scripts/install-runtime.js \
  package/skills/mco-cli/SKILL.md \
  package/skills/mco-cli/references/installation.md \
  package/skills/mco-cli/references/provider-selection.md \
  package/skills/mco-cli/references/execution-modes.md \
  package/skills/mco-cli/references/multi-model.md \
  package/skills/mco-cli/references/troubleshooting.md
do
  if ! grep -Fxq "$required_path" "$PACK_DIR/contents.txt"; then
    echo "npm packaging smoke: missing $required_path" >&2
    exit 1
  fi
done

npm install "$TARBALL" --prefix "$INSTALL_DIR" --no-audit --no-fund
MCO_BIN="$INSTALL_DIR/node_modules/.bin/mco"
"$MCO_BIN" --help >/dev/null
"$MCO_BIN" --version >/dev/null
"$MCO_BIN" skills read >/dev/null
"$MCO_BIN" skills status --json >/dev/null
"$MCO_BIN" install --agent codex --dry-run --json >/dev/null

NODE_BIN="$(command -v node)"
MCO_JS="$INSTALL_DIR/node_modules/@tt-a1i/mco/bin/mco.js"
set +e
env PATH="/usr/bin:/bin" "$NODE_BIN" "$MCO_JS" install --dry-run --json > "$PACK_DIR/no-agent-install.json" 2>&1
NO_AGENT_EXIT=$?
set -e
if [ "$NO_AGENT_EXIT" -ne 2 ]; then
  echo "npm packaging smoke: expected exit 2 for no-agent dry-run, got $NO_AGENT_EXIT" >&2
  cat "$PACK_DIR/no-agent-install.json" >&2
  exit 1
fi
if ! grep -q 'agent_selection_required' "$PACK_DIR/no-agent-install.json"; then
  echo "npm packaging smoke: missing agent_selection_required in no-agent dry-run output" >&2
  cat "$PACK_DIR/no-agent-install.json" >&2
  exit 1
fi

PACKAGE_ROOT="$INSTALL_DIR/node_modules/@tt-a1i/mco"
PYTHONPATH="$PACKAGE_ROOT" python3 - "$PACKAGE_ROOT" "$INSTALL_DIR" <<'PY'
import sys
from pathlib import Path

from runtime.skill_agents import known_skill_agents
from runtime.skill_health import check_skill_health

package_root = Path(sys.argv[1])
cwd = Path(sys.argv[2])
agents = known_skill_agents()
if "codex" not in agents or "pi" not in agents:
    raise SystemExit(f"skill calling agent manifest unavailable after npm install: {sorted(agents)}")
health, _ = check_skill_health(enabled=True, package_root=package_root, cwd=cwd)
reference = health.get("reference", {})
if health.get("status") == "unknown" or reference.get("status") != "ok":
    raise SystemExit("bundled skill reference is unavailable after npm install")
PY

python3 -m pip wheel . --wheel-dir "$WHEEL_DIR" --no-deps -q
WHEEL_FILE="$(ls "$WHEEL_DIR"/*.whl)"
python3 -m zipfile -l "$WHEEL_FILE" | grep -Fq 'runtime/data/skill_calling_agents.json' || {
  echo "wheel packaging smoke: missing runtime/data/skill_calling_agents.json" >&2
  exit 1
}
for required_path in \
  skills/mco-cli/SKILL.md \
  skills/mco-cli/references/installation.md \
  skills/mco-cli/references/provider-selection.md \
  skills/mco-cli/references/execution-modes.md \
  skills/mco-cli/references/multi-model.md \
  skills/mco-cli/references/troubleshooting.md
do
  if ! python3 -m zipfile -l "$WHEEL_FILE" | grep -Fq "$required_path"; then
    echo "wheel packaging smoke: missing $required_path" >&2
    exit 1
  fi
done
python3 -m venv "$WHEEL_VENV"
"$WHEEL_VENV/bin/pip" install "$WHEEL_FILE" -q
"$WHEEL_VENV/bin/python" - <<'PY'
from runtime.skill_agents import known_skill_agents

agents = known_skill_agents()
required = {"codex", "pi", "hermes-agent", "github-copilot", "qwen-code"}
missing = required - agents
if missing:
    raise SystemExit(f"wheel install smoke: manifest missing agents: {sorted(missing)}")
PY
"$WHEEL_VENV/bin/mco" skills read >/dev/null
"$WHEEL_VENV/bin/mco" skills status --json | "$WHEEL_VENV/bin/python" -c '
import json
import sys

payload = json.load(sys.stdin)
health = payload.get("skill_health", {})
reference = health.get("reference", {})
if health.get("status") == "unknown" or reference.get("status") != "ok":
    raise SystemExit("wheel install smoke: bundled skill reference is unavailable")
'
"$WHEEL_VENV/bin/mco" skills sync --agent codex --dry-run --json >/dev/null

echo "npm packaging smoke: PASS"
