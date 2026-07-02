#!/usr/bin/env bash
set -u
set -o pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT_DIR"

npm pack --dry-run

PACK_DIR="$(mktemp -d)"
INSTALL_DIR="$(mktemp -d)"
trap 'rm -rf "$PACK_DIR" "$INSTALL_DIR"' EXIT

npm pack --pack-destination "$PACK_DIR" >/dev/null
TARBALL="$(ls "$PACK_DIR"/tt-a1i-mco-*.tgz)"
npm install "$TARBALL" --prefix "$INSTALL_DIR" --no-audit --no-fund
"$INSTALL_DIR/node_modules/.bin/mco" --help >/dev/null

echo "npm packaging smoke: PASS"
