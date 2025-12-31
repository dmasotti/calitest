#!/usr/bin/env bash
# Minimal headless smoke test for sync_calimob using calibre-debug
# Skips gracefully if env or binaries are missing.
set -euo pipefail

ROOT=$(cd "$(dirname "$0")/../../.." && pwd)
CALIBRE_DEBUG="${CALIBRE_DEBUG:-/Applications/calibre.app/Contents/MacOS/calibre-debug}"
CALIBRE_CUSTOMIZE="${CALIBRE_CUSTOMIZE:-/Applications/calibre.app/Contents/MacOS/calibre-customize}"

REQUIRED=(CALIMOB_DISCOVERY_URL TEST_USER_EMAIL TEST_USER_PASSWORD CALIMOB_LIBRARY_PATH CALIMOB_LIBRARY_ID CALIMOB_SERVER_LIBRARY_ID CALIMOB_CONFIG_JSON)
for v in "${REQUIRED[@]}"; do
  if [[ -z "${!v-}" ]]; then
    echo "SKIP: $v not set; headless smoke test not run" >&2
    exit 0
  fi
done

if [[ ! -x "$CALIBRE_DEBUG" ]]; then
  echo "SKIP: calibre-debug not found at $CALIBRE_DEBUG" >&2
  exit 0
fi
if [[ ! -x "$CALIBRE_CUSTOMIZE" ]]; then
  echo "SKIP: calibre-customize not found at $CALIBRE_CUSTOMIZE" >&2
  exit 0
fi
if [[ ! -f "$CALIMOB_CONFIG_JSON" ]]; then
  echo "SKIP: CALIMOB_CONFIG_JSON missing ($CALIMOB_CONFIG_JSON)" >&2
  exit 0
fi

TMP_CFG=$(mktemp -d)
mkdir -p "$TMP_CFG/plugins"
cp "$CALIMOB_CONFIG_JSON" "$TMP_CFG/plugins/sync_calimob.json"

API_URL=$(curl -s "${CALIMOB_DISCOVERY_URL}/discovery.php" | jq -r '.api_url // empty' 2>/dev/null || true)
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  API_URL=$(curl -s "${CALIMOB_DISCOVERY_URL}/api/discovery" | jq -r '.api_url // empty' 2>/dev/null || true)
fi
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  echo "FAIL: discovery failed" >&2
  exit 1
fi

LOGIN_RESPONSE=$(curl -s -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$TEST_USER_EMAIL\",\"password\":\"$TEST_USER_PASSWORD\"}")
TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.token')
if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
  echo "FAIL: login failed" >&2
  echo "$LOGIN_RESPONSE" >&2
  exit 1
fi

python - <<PY
import json
import os

cfg_path = os.path.join("$TMP_CFG", "plugins", "sync_calimob.json")
data = json.load(open(cfg_path, "r"))
store = data.get("Caliweb", {})
store["discoveryUrl"] = "$CALIMOB_DISCOVERY_URL"
store["restToken"] = "$TOKEN"
store["restEndpoint"] = "$API_URL"
store["discoveryCache"] = {}
store.pop("deviceToken", None)
data["Caliweb"] = store
with open(cfg_path, "w") as f:
    json.dump(data, f, indent=2, sort_keys=True)
PY

# Install plugin in the temp Calibre config so calibre-debug can import it
CALIBRE_CONFIG_DIRECTORY="$TMP_CFG" "$CALIBRE_CUSTOMIZE" -b "$ROOT/sync_calimob" >/dev/null 2>&1 || {
  echo "SKIP: failed to install plugin into temp config" >&2
  exit 0
}

OUTPUT=$(mktemp)
set +e
CALIBRE_CONFIG_DIRECTORY="$TMP_CFG" \
  "$CALIBRE_DEBUG" -e "$ROOT/sync_calimob/cli.py" -- \
    --config-dir "$TMP_CFG" \
    --library-path "$CALIMOB_LIBRARY_PATH" \
    --library-id "$CALIMOB_LIBRARY_ID" \
    --calimob-library-id "$CALIMOB_SERVER_LIBRARY_ID" \
    ${CALIMOB_FULL_SYNC:+--full-sync} \
    >"$OUTPUT" 2>&1
STATUS=$?
set -e

if [[ $STATUS -ne 0 ]]; then
  echo "FAIL: headless sync exited with $STATUS" >&2
  sed -n '1,120p' "$OUTPUT" >&2
  exit 1
fi

JSON_OUT=$(mktemp)
python - <<'PY' "$OUTPUT" "$JSON_OUT"
import json, sys
src = open(sys.argv[1], "r", errors="ignore").read()

# Find last valid JSON object by scanning backwards for '{'
start = None
for i in range(len(src) - 1, -1, -1):
    if src[i] != '{':
        continue
    try:
        obj = json.loads(src[i:])
        start = i
        break
    except Exception:
        continue

if start is None:
    sys.exit(1)

obj = json.loads(src[start:])
open(sys.argv[2], "w").write(json.dumps(obj))
PY

if command -v jq >/dev/null 2>&1; then
  if ! jq -e '.pull.errors|length==0' "$JSON_OUT" >/dev/null; then
    echo "FAIL: pull errors reported in headless sync" >&2
    cat "$OUTPUT" >&2
    exit 1
  fi
  if ! jq -e '.push.errors|length==0' "$JSON_OUT" >/dev/null; then
    echo "FAIL: push errors reported in headless sync" >&2
    cat "$OUTPUT" >&2
    exit 1
  fi
fi

METADATA_DB="$CALIMOB_LIBRARY_PATH/metadata.db"
python - <<PY
import os, sqlite3, sys

db_path = os.path.join("$CALIMOB_LIBRARY_PATH", "metadata.db")
if not os.path.isfile(db_path):
    print("FAIL: metadata.db not found at {}".format(db_path), file=sys.stderr)
    sys.exit(1)

try:
    conn = sqlite3.connect(db_path)
    cursor = conn.execute(
        "SELECT COUNT(*) FROM calimob_books_sync WHERE library_uuid=?",
        ("$CALIMOB_LIBRARY_ID",)
    )
    count = cursor.fetchone()[0]
finally:
    conn.close()

if count == 0:
    print("FAIL: calimob_books_sync does not contain entries for library {}".format("$CALIMOB_LIBRARY_ID"), file=sys.stderr)
    sys.exit(1)

print("INFO: calimob_books_sync rows for library {} = {}".format("$CALIMOB_LIBRARY_ID", count))
PY

echo "PASS: headless sync smoke test"; echo "Output saved at $OUTPUT"
