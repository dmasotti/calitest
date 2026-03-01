#!/usr/bin/env bash
# tests/server/sync_uuid_reconciliation_test.sh
# Focused tests for UUID-based reconciliation, collisions, and mappings.

set -euo pipefail

if [[ -f "$(dirname "$0")/.env" ]]; then
  source "$(dirname "$0")/.env"
fi

DISCOVERY_URL=${DISCOVERY_URL:-}
TEST_USER_EMAIL=${TEST_USER_EMAIL:-}
TEST_USER_PASSWORD=${TEST_USER_PASSWORD:-}

if [[ -z "$DISCOVERY_URL" || -z "$TEST_USER_EMAIL" || -z "$TEST_USER_PASSWORD" ]]; then
  echo "ERROR: Required env not set (DISCOVERY_URL, TEST_USER_EMAIL, TEST_USER_PASSWORD)"
  exit 1
fi

if ! command -v curl >/dev/null 2>&1; then
  echo "curl required"
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq required"
  exit 1
fi
if ! command -v uuidgen >/dev/null 2>&1; then
  echo "uuidgen required"
  exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVALID_JSON_LOG_DIR="$SCRIPT_DIR/tmp/invalid_json_logs"
mkdir -p "$INVALID_JSON_LOG_DIR"

log() { echo "[TEST] $1"; }
pass() { echo "✓ $1"; }
fail() { echo "✗ $1"; exit 1; }

sanitize_label() {
  printf '%s' "$1" | tr ' /' '_' | tr -cd '[:alnum:]_-'
}

log_invalid_json_response() {
  local context="$1"
  local payload="$2"
  local safe_context
  safe_context="$(sanitize_label "$context")"
  local log_file="$INVALID_JSON_LOG_DIR/${safe_context}_invalid_json_$(date +%s%N).log"
  {
    echo "Context: $context"
    echo ""
    printf "%s\n" "$payload"
  } > "$log_file"
  echo "$log_file"
}

ensure_json_response() {
  local context="$1"
  local payload="$2"
  if ! echo "$payload" | jq -e . >/dev/null 2>&1; then
    local log_file
    log_file=$(log_invalid_json_response "$context" "$payload")
    fail "$context response invalid JSON (logged to $log_file)"
  fi
}

# Resolve API URL via discovery (prefer /api/discovery for local consistency)
DISCOVERY_RESPONSE=$(curl -s "$DISCOVERY_URL/api/discovery")
ensure_json_response "discovery_response" "$DISCOVERY_RESPONSE"
API_URL=$(echo "$DISCOVERY_RESPONSE" | jq -r '.api_url // empty' 2>/dev/null || true)
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  DISCOVERY_ENDPOINT="$DISCOVERY_URL/discovery.php"
  DISCOVERY_RESPONSE=$(curl -s "$DISCOVERY_ENDPOINT")
  ensure_json_response "discovery_fallback" "$DISCOVERY_RESPONSE"
  API_URL=$(echo "$DISCOVERY_RESPONSE" | jq -r '.api_url // empty' 2>/dev/null || true)
fi
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  API_URL="${DISCOVERY_URL%/}/api"
fi
if [[ "$API_URL" != ${DISCOVERY_URL%/}/* ]]; then
  API_URL="${DISCOVERY_URL%/}/api"
fi

log "API URL: $API_URL"

# Login
LOGIN_RESPONSE=$(curl -s -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$TEST_USER_EMAIL\",\"password\":\"$TEST_USER_PASSWORD\"}")

ensure_json_response "login_response" "$LOGIN_RESPONSE"

TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.token // empty')
if [[ -z "$TOKEN" ]]; then
  fail "Login failed: $LOGIN_RESPONSE"
fi
AUTH_HEADER="Authorization: Bearer $TOKEN"

api_get() {
  local resp
  resp=$(curl -s -H "$AUTH_HEADER" "$API_URL$1")
  ensure_json_response "GET $1" "$resp"
  echo "$resp"
}

api_post() {
  local resp
  resp=$(curl -s -X POST -H "$AUTH_HEADER" -H "Content-Type: application/json" "$API_URL$1" -d "$2")
  ensure_json_response "POST $1" "$resp"
  echo "$resp"
}

# Pick library with calibre_library_uuid
LIBRARIES=$(api_get "/libraries")
LIBRARY_ID=$(echo "$LIBRARIES" | jq -r 'map(select(.calibre_library_uuid != null and .calibre_library_uuid != "")) | .[0].id // empty')
CAL_LIB_UUID=$(echo "$LIBRARIES" | jq -r 'map(select(.calibre_library_uuid != null and .calibre_library_uuid != "")) | .[0].calibre_library_uuid // empty')
if [[ -z "$LIBRARY_ID" || -z "$CAL_LIB_UUID" ]]; then
  fail "No library with calibre_library_uuid found"
fi

log "Using library_id=$LIBRARY_ID calibre_library_uuid=$CAL_LIB_UUID"

TIMESTAMP=$(date +%s)
BOOK_LOCAL_ID_1=$(( RANDOM % 10000 + 1000 ))
BOOK_LOCAL_ID_2=$(( RANDOM % 10000 + 1000 ))
BOOK_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')

AUTHOR_ID=$(( RANDOM % 100000 + 90000 ))
AUTHOR_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
AUTHOR_NAME="Author UUID Test $TIMESTAMP"

TAG_ID=$(( RANDOM % 100000 + 90000 ))
TAG_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
TAG_NAME="Tag UUID Test $TIMESTAMP"

SERIES_ID=$(( RANDOM % 100000 + 90000 ))
SERIES_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
SERIES_NAME="Series UUID Test $TIMESTAMP"

log "Create book with uuid (local id is client-side only)"
CREATE_PAYLOAD=$(cat <<EOF
{
  "calibre_library_uuid": "$CAL_LIB_UUID",
  "device_uuid": "uuid-test-device-$TIMESTAMP",
  "changes": [{
    "op": "create",
    "idempotency_key": "uuid-create-$TIMESTAMP",
    "item": {
      "id": $BOOK_LOCAL_ID_1,
      "uuid": "$BOOK_UUID",
      "title": "UUID Reconcile Test $TIMESTAMP",
      "authors": [{
        "id": $AUTHOR_ID,
        "uuid": "$AUTHOR_UUID",
        "name": "$AUTHOR_NAME",
        "role": "author"
      }],
      "tags": [{
        "id": $TAG_ID,
        "uuid": "$TAG_UUID",
        "name": "$TAG_NAME"
      }],
      "series": {
        "id": $SERIES_ID,
        "uuid": "$SERIES_UUID",
        "name": "$SERIES_NAME",
        "series_index": 1
      },
      "last_modified": $TIMESTAMP
    }
  }]
}
EOF
)

CREATE_RESPONSE=$(api_post "/sync" "$CREATE_PAYLOAD")
CREATE_STATUS=$(echo "$CREATE_RESPONSE" | jq -r '.results[0].status // empty')
if [[ "$CREATE_STATUS" != "applied" && "$CREATE_STATUS" != "merged" ]]; then
  fail "Create failed: $CREATE_RESPONSE"
fi
pass "Create applied ($CREATE_STATUS)"

log "Reconcile via uuid (local id may change)"
UPDATE_PAYLOAD=$(cat <<EOF
{
  "calibre_library_uuid": "$CAL_LIB_UUID",
  "device_uuid": "uuid-test-device-$TIMESTAMP",
  "changes": [{
    "op": "update",
    "idempotency_key": "uuid-update-$TIMESTAMP",
    "item": {
      "id": $BOOK_LOCAL_ID_2,
      "uuid": "$BOOK_UUID",
      "title": "UUID Reconcile Test Updated $TIMESTAMP",
      "series": {
        "id": $SERIES_ID,
        "uuid": "$SERIES_UUID",
        "name": "$SERIES_NAME",
        "series_index": 1
      },
      "last_modified": $((TIMESTAMP + 10))
    }
  }]
}
EOF
)

UPDATE_RESPONSE=$(api_post "/sync" "$UPDATE_PAYLOAD")
UPDATE_STATUS=$(echo "$UPDATE_RESPONSE" | jq -r '.results[0].status // empty')
SERVER_ITEM_UUID=$(echo "$UPDATE_RESPONSE" | jq -r '.results[0].server_item.uuid // empty')
SERVER_ITEM_TITLE=$(echo "$UPDATE_RESPONSE" | jq -r '.results[0].server_item.title // empty')
if [[ "$UPDATE_STATUS" != "applied" && "$UPDATE_STATUS" != "merged" ]]; then
  fail "Update failed: $UPDATE_RESPONSE"
fi
if [[ "$SERVER_ITEM_UUID" != "$BOOK_UUID" ]]; then
  fail "Reconcile failed: expected server_item.uuid=$BOOK_UUID got $SERVER_ITEM_UUID"
fi
if [[ "$SERVER_ITEM_TITLE" != "UUID Reconcile Test Updated $TIMESTAMP" ]]; then
  fail "Reconcile failed: title not updated (got: $SERVER_ITEM_TITLE)"
fi
pass "Reconcile OK (uuid authoritative)"

log "Verify server echoes UUID (metadata echo is optional)"
if [[ -z "$SERVER_ITEM_UUID" ]]; then
  fail "Server did not return uuid in response: $UPDATE_RESPONSE"
fi
pass "UUID returned in server_item"

log "Delete idempotent for missing record"
MISSING_ID=$(( RANDOM % 100000 + 90000 ))
MISSING_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
DELETE_MISSING_PAYLOAD=$(cat <<EOF
{
  "calibre_library_uuid": "$CAL_LIB_UUID",
  "device_uuid": "uuid-test-device-$TIMESTAMP",
  "changes": [{
    "op": "delete",
    "idempotency_key": "uuid-delete-missing-$TIMESTAMP",
    "item": {
      "id": $MISSING_ID,
      "uuid": "$MISSING_UUID",
      "last_modified": $((TIMESTAMP + 30))
    }
  }]
}
EOF
)

DELETE_MISSING_RESPONSE=$(api_post "/sync" "$DELETE_MISSING_PAYLOAD")
DELETE_MISSING_STATUS=$(echo "$DELETE_MISSING_RESPONSE" | jq -r '.results[0].status // empty')
DELETE_MISSING_REASON=$(echo "$DELETE_MISSING_RESPONSE" | jq -r '.results[0].reason // empty')
if [[ "$DELETE_MISSING_STATUS" != "noop" || "$DELETE_MISSING_REASON" != "not_found" ]]; then
  fail "Delete idempotent failed: $DELETE_MISSING_RESPONSE"
fi
pass "Delete idempotent OK"

log "Cleanup: delete reconciled book"
CLEANUP_PAYLOAD=$(cat <<EOF
{
  "calibre_library_uuid": "$CAL_LIB_UUID",
  "device_uuid": "uuid-test-device-$TIMESTAMP",
  "changes": [{
    "op": "delete",
    "idempotency_key": "uuid-delete-cleanup-$TIMESTAMP",
    "item": {
      "id": $BOOK_LOCAL_ID_2,
      "uuid": "$BOOK_UUID",
      "last_modified": $((TIMESTAMP + 40))
    }
  }]
}
EOF
)
api_post "/sync" "$CLEANUP_PAYLOAD" >/dev/null 2>&1 || true

pass "UUID reconciliation tests completed"
