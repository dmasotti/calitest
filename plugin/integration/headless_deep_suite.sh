#!/usr/bin/env bash
# Deeper headless suite: server->client updates + local DB verification
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

if [[ ! -f "$CALIMOB_CONFIG_JSON" ]]; then
  echo "SKIP: CALIMOB_CONFIG_JSON missing: $CALIMOB_CONFIG_JSON" >&2
  exit 0
fi

API_URL=$(curl -s "$CALIMOB_DISCOVERY_URL/api/discovery" | jq -r '.api_url')
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
    CALIMOB_LIBRARY_NAME="Headless Deep Suite $(date -u +%Y%m%d%H%M%S)" \
    "$SCRIPT_DIR/headless_setup_library.sh")
  CALIMOB_SERVER_LIBRARY_ID=$(echo "$SETUP_OUT" | rg -o "CALIMOB_LIBRARY_ID=.*" -m1 | cut -d= -f2)
fi

if [[ -z "$CALIMOB_SERVER_LIBRARY_ID" ]]; then
  echo "FAIL: could not resolve CALIMOB_SERVER_LIBRARY_ID" >&2
  exit 1
fi

TMP_CFG=$(mktemp -d /tmp/calimob_deep_cfg_XXXXXX)
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
    "calimobLibraryName": "Deep Suite",
}
data["LibraryMappings"] = lm
data["discoveryUrl"] = "$CALIMOB_DISCOVERY_URL"
with open(cfg_path, "w") as f:
    json.dump(data, f, indent=2, sort_keys=True)
PY

export CALIBRE_CONFIG_DIRECTORY="$TMP_CFG"
$CALIBRE_CUSTOMIZE -b "$ROOT_DIR/sync_calimob" >/dev/null 2>&1 || {
  echo "FAIL: calibre-customize install failed" >&2
  exit 1
}

BOOK_ID=$((RANDOM + 940000))
TITLE_1="DeepSuite Pull $(date -u +%Y%m%d%H%M%S)-$BOOK_ID"
TITLE_2="DeepSuite Updated $(date -u +%Y%m%d%H%M%S)-$BOOK_ID"
NOW_ISO=$(python - <<'PY'
import datetime
print(datetime.datetime.utcnow().replace(microsecond=0).isoformat()+"+00:00")
PY
)

CREATE_PAYLOAD=$(cat <<JSON
{
  "library_id": $CALIMOB_SERVER_LIBRARY_ID,
  "calibre_library_id": "$CALIMOB_LIBRARY_ID",
  "changes": [
    {
      "op": "create",
      "idempotency_key": "deep-create-$BOOK_ID",
      "item": {
        "id": $BOOK_ID,
        "title": "$TITLE_1",
        "authors": [{"name": "DeepSuite"}],
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

RUN_OUT_1=$("$CALIBRE_DEBUG" -e "$ROOT_DIR/sync_calimob/cli.py" -- \
  --library-path "$CALIMOB_LIBRARY_PATH" \
  --library-id "$CALIMOB_LIBRARY_ID" \
  --calimob-library-id "$CALIMOB_SERVER_LIBRARY_ID" || true)

python - <<PY
import json
import sys
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
    raise SystemExit("FAIL: no JSON summary in first run")
obj = json.loads(out[start:])
if obj.get("pull", {}).get("errors"):
    raise SystemExit("FAIL: pull errors in first run")
if obj.get("push", {}).get("errors"):
    raise SystemExit("FAIL: push errors in first run")
print("OK: first sync")
PY

COUNT_1=$(sqlite3 "$CALIMOB_LIBRARY_PATH/metadata.db" "select count(*) from books where title = '$TITLE_1';")
if [[ "$COUNT_1" -lt 1 ]]; then
  echo "FAIL: title not found in local Calibre DB after pull" >&2
  exit 1
fi

UPDATE_PAYLOAD=$(cat <<JSON
{
  "library_id": $CALIMOB_SERVER_LIBRARY_ID,
  "calibre_library_id": "$CALIMOB_LIBRARY_ID",
  "changes": [
    {
      "op": "update",
      "idempotency_key": "deep-update-$BOOK_ID",
      "item": {
        "id": $BOOK_ID,
        "title": "$TITLE_2",
        "authors": [{"name": "DeepSuite"}],
        "timestamps": {"updated_at": "$NOW_ISO", "updated_at_unix": 0}
      }
    }
  ]
}
JSON
)

UPDATE_RES=$(curl -s -X POST "$API_URL/sync" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d "$UPDATE_PAYLOAD")
if ! echo "$UPDATE_RES" | jq -e '.results' >/dev/null 2>&1; then
  echo "FAIL: update sync failed" >&2
  echo "$UPDATE_RES" >&2
  exit 1
fi

RUN_OUT_2=$("$CALIBRE_DEBUG" -e "$ROOT_DIR/sync_calimob/cli.py" -- \
  --library-path "$CALIMOB_LIBRARY_PATH" \
  --library-id "$CALIMOB_LIBRARY_ID" \
  --calimob-library-id "$CALIMOB_SERVER_LIBRARY_ID" || true)

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
    raise SystemExit("FAIL: no JSON summary in second run")
obj = json.loads(out[start:])
if obj.get("pull", {}).get("errors"):
    raise SystemExit("FAIL: pull errors in second run")
if obj.get("push", {}).get("errors"):
    raise SystemExit("FAIL: push errors in second run")
print("OK: second sync")
PY

COUNT_2=$(sqlite3 "$CALIMOB_LIBRARY_PATH/metadata.db" "select count(*) from books where title = '$TITLE_2';")
COUNT_1_AFTER=$(sqlite3 "$CALIMOB_LIBRARY_PATH/metadata.db" "select count(*) from books where title = '$TITLE_1';")
if [[ "$COUNT_2" -lt 1 ]]; then
  echo "FAIL: updated title not found in local Calibre DB" >&2
  exit 1
fi
if [[ "$COUNT_1_AFTER" -gt 0 ]]; then
  echo "FAIL: old title still present after update pull" >&2
  exit 1
fi

CFG_PATH="$TMP_CFG/plugins/sync_calimob.json"
if ! python - <<PY
import json, sys
data = json.load(open("$CFG_PATH", "r"))
cache = data.get("discoveryCache", {})
endpoint = data.get("restEndpoint", "")
if not endpoint and not cache:
    sys.exit(1)
PY
then
  echo "FAIL: discovery cache/endpoint not written to config" >&2
  exit 1
fi

echo "PASS: deep headless suite"
