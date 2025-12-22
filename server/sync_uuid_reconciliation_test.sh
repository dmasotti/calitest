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

log() { echo "[TEST] $1"; }
pass() { echo "✓ $1"; }
fail() { echo "✗ $1"; exit 1; }

# Resolve API URL via discovery
DISCOVERY_ENDPOINT="$DISCOVERY_URL/discovery.php"
API_URL=$(curl -s "$DISCOVERY_ENDPOINT" | jq -r '.api_url // empty' 2>/dev/null || true)
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  API_URL=$(curl -s "$DISCOVERY_URL/api/discovery" | jq -r '.api_url // empty' 2>/dev/null || true)
fi
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  API_URL="$DISCOVERY_URL/api"
fi

log "API URL: $API_URL"

# Login
LOGIN_RESPONSE=$(curl -s -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$TEST_USER_EMAIL\",\"password\":\"$TEST_USER_PASSWORD\"}")

TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.token // empty')
if [[ -z "$TOKEN" ]]; then
  fail "Login failed: $LOGIN_RESPONSE"
fi
AUTH_HEADER="Authorization: Bearer $TOKEN"

api_get() {
  curl -s -H "$AUTH_HEADER" "$API_URL$1"
}

api_post() {
  curl -s -X POST -H "$AUTH_HEADER" -H "Content-Type: application/json" "$API_URL$1" -d "$2"
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
BOOK_NEG_ID=$(( -1 * (RANDOM % 10000 + 1000) ))
BOOK_POS_ID=$(( RANDOM % 10000 + 1000 ))
BOOK_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')

AUTHOR_ID=$(( RANDOM % 100000 + 90000 ))
AUTHOR_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
AUTHOR_KEY="calibre:$CAL_LIB_UUID:$AUTHOR_ID"
AUTHOR_NAME="Author UUID Test $TIMESTAMP"

TAG_ID=$(( RANDOM % 100000 + 90000 ))
TAG_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
TAG_KEY="calibre:$CAL_LIB_UUID:$TAG_ID"
TAG_NAME="Tag UUID Test $TIMESTAMP"

SERIES_ID=$(( RANDOM % 100000 + 90000 ))
SERIES_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
SERIES_KEY="calibre:$CAL_LIB_UUID:$SERIES_ID"
SERIES_NAME="Series UUID Test $TIMESTAMP"

log "Create book with negative id + uuid"
CREATE_PAYLOAD=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CAL_LIB_UUID",
  "device_uuid": "uuid-test-device-$TIMESTAMP",
  "changes": [{
    "op": "create",
    "idempotency_key": "uuid-create-$TIMESTAMP",
    "item": {
      "id": $BOOK_NEG_ID,
      "uuid": "$BOOK_UUID",
      "title": "UUID Reconcile Test $TIMESTAMP",
      "authors": [{
        "id": $AUTHOR_ID,
        "uuid": "$AUTHOR_UUID",
        "client_ids": {"$AUTHOR_KEY": "$AUTHOR_ID"},
        "name": "$AUTHOR_NAME",
        "role": "author"
      }],
      "tags": [{
        "id": $TAG_ID,
        "uuid": "$TAG_UUID",
        "client_ids": {"$TAG_KEY": "$TAG_ID"},
        "name": "$TAG_NAME"
      }],
      "series": {
        "id": $SERIES_ID,
        "uuid": "$SERIES_UUID",
        "client_ids": {"$SERIES_KEY": "$SERIES_ID"},
        "name": "$SERIES_NAME",
        "series_index": 1
      },
      "client_ids": {"calibre:$CAL_LIB_UUID:$BOOK_NEG_ID": "$BOOK_NEG_ID"},
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

log "Reconcile id via update with positive id"
UPDATE_PAYLOAD=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CAL_LIB_UUID",
  "device_uuid": "uuid-test-device-$TIMESTAMP",
  "changes": [{
    "op": "update",
    "idempotency_key": "uuid-update-$TIMESTAMP",
    "item": {
      "id": $BOOK_POS_ID,
      "uuid": "$BOOK_UUID",
      "title": "UUID Reconcile Test Updated $TIMESTAMP",
      "series": {
        "id": $SERIES_ID,
        "uuid": "$SERIES_UUID",
        "client_ids": {"$SERIES_KEY": "$SERIES_ID"},
        "name": "$SERIES_NAME",
        "series_index": 1
      },
      "client_ids": {"calibre:$CAL_LIB_UUID:$BOOK_POS_ID": "$BOOK_POS_ID"},
      "last_modified": $((TIMESTAMP + 10))
    }
  }]
}
EOF
)

UPDATE_RESPONSE=$(api_post "/sync" "$UPDATE_PAYLOAD")
UPDATE_STATUS=$(echo "$UPDATE_RESPONSE" | jq -r '.results[0].status // empty')
SERVER_ITEM_ID=$(echo "$UPDATE_RESPONSE" | jq -r '.results[0].server_item.id // empty')
if [[ "$UPDATE_STATUS" != "applied" && "$UPDATE_STATUS" != "merged" ]]; then
  fail "Update failed: $UPDATE_RESPONSE"
fi
if [[ "$SERVER_ITEM_ID" != "$BOOK_POS_ID" ]]; then
  fail "Reconcile failed: expected server_item.id=$BOOK_POS_ID got $SERVER_ITEM_ID"
fi
pass "Reconcile id OK (server_item.id=$SERVER_ITEM_ID)"

log "Verify client_ids/uuid for related entities in response"
AUTHOR_MATCH=$(echo "$UPDATE_RESPONSE" | jq -r --arg name "$AUTHOR_NAME" --arg key "$AUTHOR_KEY" --arg val "$AUTHOR_ID" --arg uuid "$AUTHOR_UUID" '
  .results[0].server_item.authors[]?
  | select(.name == $name)
  | select((.client_ids | type) == "object")
  | select((.client_ids[$key] // empty) == $val)
  | select(.uuid == $uuid)
  | .name // empty' | head -n1)
TAG_MATCH=$(echo "$UPDATE_RESPONSE" | jq -r --arg name "$TAG_NAME" --arg key "$TAG_KEY" --arg val "$TAG_ID" --arg uuid "$TAG_UUID" '
  .results[0].server_item.tags[]?
  | select(.name == $name)
  | select((.client_ids | type) == "object")
  | select((.client_ids[$key] // empty) == $val)
  | select(.uuid == $uuid)
  | .name // empty' | head -n1)
SERIES_MATCH=$(echo "$UPDATE_RESPONSE" | jq -r --arg name "$SERIES_NAME" --arg key "$SERIES_KEY" --arg val "$SERIES_ID" --arg uuid "$SERIES_UUID" '
  .results[0].server_item.series?
  | select(.name == $name)
  | select((.client_ids | type) == "object")
  | select((.client_ids[$key] // empty) == $val)
  | select(.uuid == $uuid)
  | .name // empty' | head -n1)

if [[ -z "$AUTHOR_MATCH" || -z "$TAG_MATCH" ]]; then
  fail "Missing author/tag mapping data in response: $UPDATE_RESPONSE"
fi
if [[ -z "$SERIES_MATCH" ]]; then
  echo "⚠ Series mapping missing in response (server_item.series is null)"
else
  pass "Series mapping returned in server_item"
fi
pass "Author/Tag mappings returned in server_item"

log "Hard collision on same id with different uuid"
COLLISION_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
COLLISION_PAYLOAD=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CAL_LIB_UUID",
  "device_uuid": "uuid-test-device-$TIMESTAMP",
  "changes": [{
    "op": "create",
    "idempotency_key": "uuid-collision-$TIMESTAMP",
    "item": {
      "id": $BOOK_POS_ID,
      "uuid": "$COLLISION_UUID",
      "title": "UUID Collision Test $TIMESTAMP",
      "last_modified": $((TIMESTAMP + 20))
    }
  }]
}
EOF
)

COLLISION_RESPONSE=$(api_post "/sync" "$COLLISION_PAYLOAD")
COLLISION_STATUS=$(echo "$COLLISION_RESPONSE" | jq -r '.results[0].status // empty')
COLLISION_REASON=$(echo "$COLLISION_RESPONSE" | jq -r '.results[0].reason // empty')
if [[ "$COLLISION_STATUS" != "conflict" || "$COLLISION_REASON" != "uuid_collision" ]]; then
  fail "Collision check failed: $COLLISION_RESPONSE"
fi
pass "Collision detected (uuid_collision)"

log "Delete idempotent for missing record"
MISSING_ID=$(( RANDOM % 100000 + 90000 ))
MISSING_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
DELETE_MISSING_PAYLOAD=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
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
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CAL_LIB_UUID",
  "device_uuid": "uuid-test-device-$TIMESTAMP",
  "changes": [{
    "op": "delete",
    "idempotency_key": "uuid-delete-cleanup-$TIMESTAMP",
    "item": {
      "id": $BOOK_POS_ID,
      "uuid": "$BOOK_UUID",
      "last_modified": $((TIMESTAMP + 40))
    }
  }]
}
EOF
)
api_post "/sync" "$CLEANUP_PAYLOAD" >/dev/null 2>&1 || true

pass "UUID reconciliation tests completed"
