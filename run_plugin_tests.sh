#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "$0")/.." && pwd)"
DEFAULT_PLUGIN_LIB_PATH="$ROOT_DIR/tests/plugin/fixtures/CalibreTestLocal"
DEFAULT_CALIBRE_CONFIG_DIR="$ROOT_DIR/tests/plugin/.calibre-config"
ENV_FILE="$ROOT_DIR/tests/server/.env"

if [[ -f "$ENV_FILE" ]]; then
  set -a
  # shellcheck disable=SC1090
  source "$ENV_FILE"
  set +a
fi

# Allow headless protocol suite to auto-register user when missing.
export TEST_AUTO_REGISTER="${TEST_AUTO_REGISTER:-1}"
export CALIBRE_CONFIG_DIRECTORY="${CALIBRE_CONFIG_DIRECTORY:-$DEFAULT_CALIBRE_CONFIG_DIR}"
mkdir -p "$CALIBRE_CONFIG_DIRECTORY"

echo "Test guide: tests/README.md"
echo "Quick start: ./tests/run_plugin_tests.sh"
echo ""

echo "== Plugin unit tests (pytest) =="
python3 -m pytest -q "$ROOT_DIR/tests/plugin/unit"

echo ""
echo "== Rebuild Calibre plugin =="
REBUILD_SCRIPT="$ROOT_DIR/sync_calimob/local-dev/rebuild-plugin.sh"
if [[ -x "$REBUILD_SCRIPT" ]]; then
  "$REBUILD_SCRIPT"
else
  echo "NOTICE: Rebuild script not executable, invoking via bash."
  bash "$REBUILD_SCRIPT"
fi

echo ""
echo "== Plugin integration tests (calibre-debug) =="
CALIBRE_DEBUG="/Applications/calibre.app/Contents/MacOS/calibre-debug"
if [[ ! -x "$CALIBRE_DEBUG" ]]; then
  echo "ERROR: calibre-debug not found at $CALIBRE_DEBUG"
  echo "Install Calibre or adjust the path."
  exit 1
fi

# Ensure the test user has sufficient tier so plugin integration can create libraries
(
  cd "$ROOT_DIR/html"
  if [[ -f ".env" ]]; then
    set -a
    source ".env"
    set +a
  fi
  php artisan subscription:set "${TEST_USER_EMAIL:-dmasotti+test1@gmail.com}" enterprise --status=active --days=3650 >/dev/null
) >/dev/null 2>&1

"$CALIBRE_DEBUG" -e "$ROOT_DIR/tests/plugin/test_plugin_integration.py"

echo ""
echo "== Plugin protocol compliance (headless) =="
CALIMOB_TEST_LIBRARY_PATH="${CALIMOB_TEST_LIBRARY_PATH:-$DEFAULT_PLUGIN_LIB_PATH}" \
python3 "$ROOT_DIR/tests/plugin/integration/headless_protocol_compliance.py"

echo ""
echo "== Plugin V5 integration (calibre-debug) =="
V5_LIBRARY_PATH="${CALIMOB_TEST_LIBRARY_PATH:-$DEFAULT_PLUGIN_LIB_PATH}"
if [[ ! -f "$V5_LIBRARY_PATH/metadata.db" ]]; then
  echo "ERROR: Calibre test library not found at $V5_LIBRARY_PATH"
  echo "Set CALIMOB_TEST_LIBRARY_PATH or move the library to tests/plugin/fixtures/CalibreTestLocal"
  exit 1
fi

CALIMOB_TEST_LIBRARY_PATH="$V5_LIBRARY_PATH" "$CALIBRE_DEBUG" -e "$ROOT_DIR/tests/plugin/v5/test_sync_v5_integration.py" --all
CALIMOB_TEST_LIBRARY_PATH="$V5_LIBRARY_PATH" "$CALIBRE_DEBUG" -e "$ROOT_DIR/tests/plugin/v5/test_sync_v5_advanced.py" --all
