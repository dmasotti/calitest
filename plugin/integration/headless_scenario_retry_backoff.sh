#!/usr/bin/env bash
# Retry/backoff scenario using local HTTP server + RestApiClient
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

CALIBRE_DEBUG=${CALIBRE_DEBUG:-/Applications/calibre.app/Contents/MacOS/calibre-debug}
CALIBRE_CUSTOMIZE=${CALIBRE_CUSTOMIZE:-/Applications/calibre.app/Contents/MacOS/calibre-customize}

if [[ ! -f "$CALIBRE_DEBUG" || ! -f "$CALIBRE_CUSTOMIZE" ]]; then
  echo "SKIP: calibre-debug/customize not found" >&2
  exit 0
fi

TMP_CFG=$(mktemp -d /tmp/calimob_retry_cfg_XXXXXX)
mkdir -p "$TMP_CFG/plugins"

export CALIBRE_CONFIG_DIRECTORY="$TMP_CFG"
$CALIBRE_CUSTOMIZE -b "$ROOT_DIR/sync_calimob" >/dev/null 2>&1 || {
  echo "FAIL: calibre-customize install failed" >&2
  exit 1
}

OUT=$("$CALIBRE_DEBUG" -e "$ROOT_DIR/tests/plugin/integration/retry_backoff_probe.py" 2>&1 || true)

if ! echo "$OUT" | rg -q "PASS: retry/backoff scenario"; then
  echo "FAIL: retry/backoff scenario" >&2
  echo "$OUT" >&2
  exit 1
fi

echo "PASS: retry/backoff scenario"
