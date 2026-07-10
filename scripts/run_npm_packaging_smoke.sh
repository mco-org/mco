#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

PACK_DIR="$(mktemp -d)"
INSTALL_DIR="$(mktemp -d)"
trap 'rm -rf "$PACK_DIR" "$INSTALL_DIR"' EXIT

npm pack --dry-run >/dev/null
npm pack --pack-destination "$PACK_DIR" >/dev/null
TARBALL="$(ls "$PACK_DIR"/tt-a1i-mco-*.tgz)"
tar -tzf "$TARBALL" > "$PACK_DIR/contents.txt"
for required_path in \
  package/bin/mco.js \
  package/mco \
  package/runtime/adapters/copilot.py \
  package/runtime/adapters/cursor.py \
  package/runtime/adapters/grok.py \
  package/runtime/provider_risk.py \
  package/runtime/skill_health.py \
  package/runtime/schemas/review_findings.schema.json \
  package/skills/mco-cli/SKILL.md
do
  if ! grep -Fxq "$required_path" "$PACK_DIR/contents.txt"; then
    echo "npm packaging smoke: missing $required_path" >&2
    exit 1
  fi
done

npm install "$TARBALL" --prefix "$INSTALL_DIR" --no-audit --no-fund
"$INSTALL_DIR/node_modules/.bin/mco" --help >/dev/null
"$INSTALL_DIR/node_modules/.bin/mco" --version >/dev/null

PACKAGE_ROOT="$INSTALL_DIR/node_modules/@tt-a1i/mco"
PYTHONPATH="$PACKAGE_ROOT" python3 - "$PACKAGE_ROOT" "$INSTALL_DIR" <<'PY'
import sys
from pathlib import Path

from runtime.skill_health import check_skill_health

package_root = Path(sys.argv[1])
cwd = Path(sys.argv[2])
health, _ = check_skill_health(enabled=True, package_root=package_root, cwd=cwd)
reference = health.get("reference", {})
if health.get("status") == "unknown" or reference.get("status") != "ok":
    raise SystemExit("bundled skill reference is unavailable after npm install")
PY

echo "npm packaging smoke: PASS"
