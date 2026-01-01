#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"

echo "== Plugin unit tests (pytest) =="
python3 -m pytest -q "$ROOT_DIR/tests/plugin/unit"

echo ""
echo "== Plugin integration tests (calibre-debug) =="
CALIBRE_DEBUG="/Applications/calibre.app/Contents/MacOS/calibre-debug"
if [[ ! -x "$CALIBRE_DEBUG" ]]; then
  echo "ERROR: calibre-debug not found at $CALIBRE_DEBUG"
  echo "Install Calibre or adjust the path."
  exit 1
fi

"$CALIBRE_DEBUG" -e "$ROOT_DIR/tests/plugin/test_plugin_integration.py"

echo ""
echo "== Plugin protocol compliance (headless) =="
python3 "$ROOT_DIR/tests/plugin/integration/headless_protocol_compliance.py"
