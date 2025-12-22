#!/usr/bin/env bash
# Inventory reconciliation: local delete should be pushed using inventory prefetch
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../../.." && pwd)"

# Load env if exists
if [[ -f "$SCRIPT_DIR/../../server/.env" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/../../server/.env"
fi

CALIMOB_DISCOVERY_URL=${CALIMOB_DISCOVERY_URL:-${DISCOVERY_URL:-}}
TEST_USER_EMAIL=${TEST_USER_EMAIL:-}
TEST_USER_PASSWORD=${TEST_USER_PASSWORD:-}
CALIMOB_LIBRARY_PATH=${CALIMOB_LIBRARY_PATH:-}
CALIMOB_LIBRARY_ID=${CALIMOB_LIBRARY_ID:-} # Calibre library UUID (local)
CALIMOB_SERVER_LIBRARY_ID=${CALIMOB_SERVER_LIBRARY_ID:-} # Server library ID
CALIMOB_CONFIG_JSON=${CALIMOB_CONFIG_JSON:-}
CALIBRE_DEBUG=${CALIBRE_DEBUG:-/Applications/calibre.app/Contents/MacOS/calibre-debug}
CALIBRE_CUSTOMIZE=${CALIBRE_CUSTOMIZE:-/Applications/calibre.app/Contents/MacOS/calibre-customize}

if [[ -z "$CALIMOB_DISCOVERY_URL" || -z "$TEST_USER_EMAIL" || -z "$TEST_USER_PASSWORD" ]]; then
  echo "SKIP: set CALIMOB_DISCOVERY_URL/TEST_USER_EMAIL/TEST_USER_PASSWORD" >&2
  exit 0
fi
if [[ -z "$CALIMOB_LIBRARY_PATH" || -z "$CALIMOB_LIBRARY_ID" || -z "$CALIMOB_CONFIG_JSON" ]]; then
  echo "SKIP: set CALIMOB_LIBRARY_PATH, CALIMOB_LIBRARY_ID, CALIMOB_CONFIG_JSON" >&2
  exit 0
fi
if [[ ! -f "$CALIBRE_DEBUG" || ! -f "$CALIBRE_CUSTOMIZE" ]]; then
  echo "SKIP: calibre-debug/customize not found" >&2
  exit 0
fi
if ! command -v sqlite3 >/dev/null 2>&1; then
  echo "SKIP: sqlite3 not found (needed for local DB checks)" >&2
  exit 0
fi

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

if [[ -z "$CALIMOB_SERVER_LIBRARY_ID" ]]; then
  SETUP_OUT=$(CALIBRE_LIBRARY_ID="$CALIMOB_LIBRARY_ID" \
    CALIMOB_LIBRARY_NAME="Headless Inventory Suite $(date -u +%Y%m%d%H%M%S)" \
    "$SCRIPT_DIR/headless_setup_library.sh")
  CALIMOB_SERVER_LIBRARY_ID=$(echo "$SETUP_OUT" | rg -o "CALIMOB_LIBRARY_ID=.*" -m1 | cut -d= -f2)
fi

if [[ -z "$CALIMOB_SERVER_LIBRARY_ID" ]]; then
  echo "FAIL: could not resolve CALIMOB_SERVER_LIBRARY_ID" >&2
  exit 1
fi

TMP_CFG=$(mktemp -d /tmp/calimob_inventory_cfg_XXXXXX)
mkdir -p "$TMP_CFG/plugins"
cp "$CALIMOB_CONFIG_JSON" "$TMP_CFG/plugins/sync_calimob.json"

python - <<PY
import json
import os

cfg_path = os.path.join("$TMP_CFG", "plugins", "sync_calimob.json")
data = json.load(open(cfg_path, "r"))
lm = data.get("LibraryMappings", {})
lm["$CALIMOB_LIBRARY_ID"] = {
    "syncEnabled": True,
    "calibreLibraryId": "$CALIMOB_LIBRARY_ID",
    "calimobLibraryId": int("$CALIMOB_SERVER_LIBRARY_ID"),
    "calimobLibraryName": "Inventory Suite",
}
data["LibraryMappings"] = lm
store = data.get("Goodreads", {})
store["discoveryUrl"] = "$CALIMOB_DISCOVERY_URL"
store["restToken"] = "$TOKEN"
store.pop("deviceToken", None)
store.pop("restEndpoint", None)
store.pop("discoveryCache", None)
data["Goodreads"] = store
with open(cfg_path, "w") as f:
    json.dump(data, f, indent=2, sort_keys=True)
PY

export CALIBRE_CONFIG_DIRECTORY="$TMP_CFG"
$CALIBRE_CUSTOMIZE -b "$ROOT_DIR/sync_calimob" >/dev/null 2>&1 || {
  echo "FAIL: calibre-customize install failed" >&2
  exit 1
}

BOOK_ID=$((RANDOM + 960000))
TITLE_1="Inventory Seed $(date -u +%Y%m%d%H%M%S)-$BOOK_ID"
NOW_ISO=$(python - <<'PY'
import datetime
print(datetime.datetime.utcnow().replace(microsecond=0).isoformat()+"+00:00")
PY
)

CREATE_PAYLOAD=$(cat <<JSON
{
  "library_id": $CALIMOB_SERVER_LIBRARY_ID,
  "calibre_library_uuid": "$CALIMOB_LIBRARY_ID",
  "changes": [
    {
      "op": "create",
      "idempotency_key": "inventory-create-$BOOK_ID",
      "item": {
        "id": $BOOK_ID,
        "title": "$TITLE_1",
        "authors": [{"name": "InventorySuite"}],
        "timestamps": {"updated_at": "$NOW_ISO", "updated_at_unix": 0}
      }
    }
  ]
}
JSON
)

CREATE_RES=$(curl -s -X POST "$API_URL/sync" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$CREATE_PAYLOAD")
if ! echo "$CREATE_RES" | jq -e '.results' >/dev/null 2>&1; then
  echo "FAIL: create sync failed" >&2
  echo "$CREATE_RES" >&2
  exit 1
fi

# Pull into local library
RUN_OUT_1=$("$CALIBRE_DEBUG" -e "$ROOT_DIR/sync_calimob/cli.py" -- \
  --library-path "$CALIMOB_LIBRARY_PATH" \
  --library-id "$CALIMOB_LIBRARY_ID" \
  --calimob-library-id "$CALIMOB_SERVER_LIBRARY_ID" || true)

python - <<PY
import json
out = """$RUN_OUT_1"""
start = None
for i in range(len(out)-1, -1, -1):
    if out[i] != '{':
        continue
    try:
        obj = json.loads(out[i:])
        start = i
        break
    except Exception:
        continue
if start is None:
    raise SystemExit("FAIL: no JSON summary in initial pull")
obj = json.loads(out[start:])
if obj.get("pull", {}).get("errors"):
    raise SystemExit("FAIL: pull errors in initial pull")
if obj.get("push", {}).get("errors"):
    raise SystemExit("FAIL: push errors in initial pull")
print("OK: initial sync")
PY

# Delete locally (metadata.db)
sqlite3 "$CALIMOB_LIBRARY_PATH/metadata.db" "DELETE FROM books WHERE id=$BOOK_ID;"

# Full sync: push first (inventory prefetch) should send delete
RUN_OUT_2=$("$CALIBRE_DEBUG" -e "$ROOT_DIR/sync_calimob/cli.py" -- \
  --library-path "$CALIMOB_LIBRARY_PATH" \
  --library-id "$CALIMOB_LIBRARY_ID" \
  --calimob-library-id "$CALIMOB_SERVER_LIBRARY_ID" \
  --full-sync || true)

python - <<PY
import json
out = """$RUN_OUT_2"""
start = None
for i in range(len(out)-1, -1, -1):
    if out[i] != '{':
        continue
    try:
        obj = json.loads(out[i:])
        start = i
        break
    except Exception:
        continue
if start is None:
    raise SystemExit("FAIL: no JSON summary in reconciliation run")
obj = json.loads(out[start:])
push = obj.get("push", {}) or {}
if push.get("errors"):
    raise SystemExit("FAIL: push errors in reconciliation run")
if int(push.get("deleted", 0)) < 1:
    raise SystemExit("FAIL: expected at least 1 delete pushed")
print("PASS: inventory reconciliation scenario")
PY
