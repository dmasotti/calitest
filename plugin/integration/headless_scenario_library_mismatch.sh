#!/usr/bin/env bash
# Headless mismatch scenario: wrong calibre_library_id should 403
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
CALIBRE_DEBUG="${CALIBRE_DEBUG:-/Applications/calibre.app/Contents/MacOS/calibre-debug}"
CALIBRE_CUSTOMIZE="${CALIBRE_CUSTOMIZE:-/Applications/calibre.app/Contents/MacOS/calibre-customize}"

REQUIRED=(CALIMOB_LIBRARY_PATH CALIMOB_LIBRARY_ID CALIMOB_SERVER_LIBRARY_ID CALIMOB_CONFIG_JSON)
for v in "${REQUIRED[@]}"; do
  if [[ -z "${!v-}" ]]; then
    echo "SKIP: $v not set; mismatch test not run" >&2
    exit 0
  fi
done

if [[ ! -x "$CALIBRE_DEBUG" || ! -x "$CALIBRE_CUSTOMIZE" ]]; then
  echo "SKIP: calibre-debug/customize not found" >&2
  exit 0
fi
if [[ ! -f "$CALIMOB_CONFIG_JSON" ]]; then
  echo "SKIP: CALIMOB_CONFIG_JSON missing ($CALIMOB_CONFIG_JSON)" >&2
  exit 0
fi

TMP_CFG=$(mktemp -d)
mkdir -p "$TMP_CFG/plugins"
cp "$CALIMOB_CONFIG_JSON" "$TMP_CFG/plugins/sync_calimob.json"
CALIBRE_CONFIG_DIRECTORY="$TMP_CFG" "$CALIBRE_CUSTOMIZE" -b "$ROOT/sync_calimob" >/dev/null 2>&1 || {
  echo "SKIP: failed to install plugin into temp config" >&2
  exit 0
}

WRONG_LIB_ID="00000000-0000-0000-0000-000000000000"
OUTPUT=$(mktemp)
set +e
CALIBRE_CONFIG_DIRECTORY="$TMP_CFG" \
  "$CALIBRE_DEBUG" -e "$ROOT/sync_calimob/cli.py" -- \
    --library-path "$CALIMOB_LIBRARY_PATH" \
    --library-id "$WRONG_LIB_ID" \
    --calimob-library-id "$CALIMOB_SERVER_LIBRARY_ID" \
    >"$OUTPUT" 2>&1
STATUS=$?
set -e

if [[ $STATUS -eq 0 ]]; then
  echo "FAIL: expected non-zero exit for library mismatch" >&2
  cat "$OUTPUT" >&2
  exit 1
fi

if ! grep -qi "Library ID mismatch" "$OUTPUT"; then
  echo "FAIL: mismatch error not found in output" >&2
  sed -n '1,120p' "$OUTPUT" >&2
  exit 1
fi

echo "PASS: library mismatch scenario"
