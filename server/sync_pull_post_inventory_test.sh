#!/usr/bin/env bash
# tests/server/sync_pull_post_inventory_test.sh
# End-to-end tests for POST /api/sync/pull with client_inventory filtering.
# Usage:
#   DISCOVERY_URL=https://example.com TEST_USER_EMAIL=user@example.com TEST_USER_PASSWORD=secret ./tests/server/sync_pull_post_inventory_test.sh

set -euo pipefail

if [[ -f "$(dirname "$0")/.env" ]]; then
  source "$(dirname "$0")/.env"
fi

DISCOVERY_URL=${DISCOVERY_URL:-http://127.0.0.1:8000}
TEST_USER_EMAIL=${TEST_USER_EMAIL:-}
TEST_USER_PASSWORD=${TEST_USER_PASSWORD:-}

if ! command -v curl >/dev/null 2>&1; then
  echo "curl required"
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq required"
  exit 1
fi

if [[ -z "$TEST_USER_EMAIL" || -z "$TEST_USER_PASSWORD" ]]; then
  echo "ERROR: Set TEST_USER_EMAIL and TEST_USER_PASSWORD"
  exit 2
fi

# Resolve API URL via discovery
DISCOVERY_ENDPOINT="$DISCOVERY_URL/discovery.php"
API_URL=$(curl -s "$DISCOVERY_ENDPOINT" | jq -r '.api_url // empty' 2>/dev/null || true)
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  API_URL=$(curl -s "$DISCOVERY_URL/api/discovery" | jq -r '.api_url // empty' 2>/dev/null || true)
fi
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  API_URL="$DISCOVERY_URL/api"
fi

# Login
LOGIN_RESPONSE=$(curl -s -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$TEST_USER_EMAIL\",\"password\":\"$TEST_USER_PASSWORD\"}")

TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.token // empty')
if [[ -z "$TOKEN" ]]; then
  echo "Login failed: $LOGIN_RESPONSE"
  exit 3
fi

AUTH_HEADER="Authorization: Bearer $TOKEN"

api_get() {
  curl -s -H "$AUTH_HEADER" "$API_URL$1"
}

api_post() {
  curl -s -X POST -H "$AUTH_HEADER" -H "Content-Type: application/json" "$API_URL$1" -d "$2"
}

echo "API URL: $API_URL"

# Pick first library with calibre_library_uuid
LIBRARIES=$(api_get "/libraries")
LIBRARY_ID=$(echo "$LIBRARIES" | jq -r '.[0].id // empty')
CALIBRE_LIBRARY_ID=$(echo "$LIBRARIES" | jq -r '.[0].calibre_library_uuid // empty')

if [[ -z "$LIBRARY_ID" || -z "$CALIBRE_LIBRARY_ID" ]]; then
  echo "No library found with calibre_library_uuid; cannot run tests"
  exit 4
fi

log() { echo "[TEST] $1"; }
pass() { echo "✓ $1"; }
fail() { echo "✗ $1"; exit 1; }

NOW=$(date +%s)
BOOK_ID=$((900000 + (RANDOM % 10000)))

log "Create test book $BOOK_ID"
CREATE_PAYLOAD=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
  "changes": [{
    "op": "create",
    "item": {
      "id": $BOOK_ID,
      "title": "Inventory Filter Test $NOW",
      "authors": [{"name":"Tester","role":"author"}],
      "timestamps": {
        "created_at": "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)",
        "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"
      }
    },
    "idempotency_key": "inv-create-$NOW"
  }]
}
EOF
)

CREATE_RESP=$(api_post "/sync" "$CREATE_PAYLOAD")
CREATE_STATUS=$(echo "$CREATE_RESP" | jq -r '.results[0].status // empty')
if [[ "$CREATE_STATUS" != "applied" && "$CREATE_STATUS" != "merged" ]]; then
  fail "Create failed: $CREATE_RESP"
fi
pass "Create applied"

log "Get cursor before delete"
CURSOR_RESP=$(api_post "/sync/pull" "{\"library_id\":$LIBRARY_ID,\"calibre_library_uuid\":\"$CALIBRE_LIBRARY_ID\",\"limit\":1}")
CURSOR_BEFORE=$(echo "$CURSOR_RESP" | jq -r '.new_cursor // empty')
if [[ -z "$CURSOR_BEFORE" || "$CURSOR_BEFORE" == "null" ]]; then
  fail "No cursor returned"
fi
pass "Cursor obtained"

log "Delete test book $BOOK_ID"
DELETE_PAYLOAD=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
  "changes": [{
    "op": "delete",
    "item": {"id": $BOOK_ID, "timestamps": {"updated_at": "$(date -u +%Y-%m-%dT%H:%M:%S+00:00)"}},
    "idempotency_key": "inv-delete-$NOW"
  }]
}
EOF
)
DELETE_RESP=$(api_post "/sync" "$DELETE_PAYLOAD")
DELETE_STATUS=$(echo "$DELETE_RESP" | jq -r '.results[0].status // empty')
if [[ "$DELETE_STATUS" != "applied" && "$DELETE_STATUS" != "merged" && "$DELETE_STATUS" != "noop" ]]; then
  fail "Delete failed: $DELETE_RESP"
fi
pass "Delete applied"

log "POST /sync/pull with client_inventory including deleted ID (should include delete)"
INV_INCLUDE=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
  "cursor": "$CURSOR_BEFORE",
  "limit": 200,
  "client_inventory": {
    "min": $BOOK_ID,
    "max": $BOOK_ID,
    "active": [$BOOK_ID],
    "missing": []
  }
}
EOF
)
PULL_INC=$(api_post "/sync/pull" "$INV_INCLUDE")
echo "$PULL_INC" | jq -e --arg id "$BOOK_ID" '.changes[]? | select(.op=="delete" and (.item.id|tostring)==$id)' >/dev/null \
  && pass "Delete present when client inventory includes ID" \
  || fail "Delete missing when inventory includes ID"

log "POST /sync/pull with client_inventory excluding deleted ID (should NOT include delete)"
INV_EXCLUDE=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
  "cursor": "$CURSOR_BEFORE",
  "limit": 200,
  "client_inventory": {
    "min": $BOOK_ID,
    "max": $BOOK_ID,
    "active": [],
    "missing": ["$BOOK_ID"]
  }
}
EOF
)
PULL_EXC=$(api_post "/sync/pull" "$INV_EXCLUDE")
if echo "$PULL_EXC" | jq -e --arg id "$BOOK_ID" '.changes[]? | select(.op=="delete" and (.item.id|tostring)==$id)' >/dev/null; then
  fail "Delete returned even though client inventory excludes ID"
else
  pass "Delete filtered out when inventory excludes ID"
fi

log "Idempotency: re-send delete with same idempotency_key"
REPEAT_RESP=$(api_post "/sync" "$DELETE_PAYLOAD")
REPEAT_STATUS=$(echo "$REPEAT_RESP" | jq -r '.results[0].status // empty')
if [[ "$REPEAT_STATUS" == "error" || -z "$REPEAT_STATUS" ]]; then
  fail "Idempotency failed: $REPEAT_RESP"
fi
pass "Idempotency OK (status=$REPEAT_STATUS)"

echo "All POST /sync/pull inventory tests passed."
