#!/usr/bin/env bash
# tests/server/sync_protocol_contract_test.sh
# End-to-end protocol contract tests based on docs (Two-Way Sync).
# Usage:
#   DISCOVERY_URL=https://example.com TEST_USER_EMAIL=user@example.com TEST_USER_PASSWORD=secret \
#   CLEANUP_EMAIL=superadmin@example.com CLEANUP_PASSWORD=secret \
#   ./tests/server/sync_protocol_contract_test.sh

set -euo pipefail

if [[ -f "$(dirname "$0")/.env" ]]; then
  source "$(dirname "$0")/.env"
fi

DISCOVERY_URL=${DISCOVERY_URL:-http://127.0.0.1:8000}
TEST_USER_EMAIL=${TEST_USER_EMAIL:-}
TEST_USER_PASSWORD=${TEST_USER_PASSWORD:-}
CLEANUP_EMAIL=${CLEANUP_EMAIL:-}
CLEANUP_PASSWORD=${CLEANUP_PASSWORD:-}
TMPDIR=$(mktemp -d)

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

log() { echo "[TEST] $1"; }
pass() { echo "✓ $1"; }
fail() { echo "✗ $1"; exit 1; }

request() {
  local method="$1"
  local path="$2"
  local data="${3:-}"
  local out="$TMPDIR/resp.json"
  local code
  if [[ "$method" == "GET" ]]; then
    code=$(curl -s -o "$out" -w "%{http_code}" -H "$AUTH_HEADER" "$API_URL$path")
  else
    code=$(curl -s -o "$out" -w "%{http_code}" -H "$AUTH_HEADER" -H "Content-Type: application/json" -X "$method" "$API_URL$path" -d "$data")
  fi
  RESPONSE_BODY=$(cat "$out")
  RESPONSE_CODE="$code"
}

# Cleanup via tools SQL (requires superadmin). Uses CLEANUP_* if provided, else TEST_USER.
cleanup_created_book() {
  if [[ -z "${CREATED_BOOK_ID:-}" || -z "${LIBRARY_ID:-}" ]]; then
    return 0
  fi

  local cleanup_email="${CLEANUP_EMAIL:-$TEST_USER_EMAIL}"
  local cleanup_password="${CLEANUP_PASSWORD:-$TEST_USER_PASSWORD}"
  if [[ -z "$cleanup_email" || -z "$cleanup_password" ]]; then
    echo "Cleanup skipped: missing CLEANUP credentials"
    return 0
  fi

  local cleanup_login
  cleanup_login=$(curl -s -X POST "$API_URL/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$cleanup_email\",\"password\":\"$cleanup_password\"}")
  local cleanup_token
  cleanup_token=$(echo "$cleanup_login" | jq -r '.token // empty')
  if [[ -z "$cleanup_token" ]]; then
    echo "Cleanup login failed (skipped): $cleanup_login"
    return 0
  fi

  local cleanup_header="Authorization: Bearer $cleanup_token"
  local delete_sql
  delete_sql=$(cat <<EOF
DELETE FROM sync_conflicts WHERE library_id=${LIBRARY_ID} AND calibre_book_id=${CREATED_BOOK_ID};
DELETE FROM books WHERE library_id=${LIBRARY_ID} AND id=${CREATED_BOOK_ID};
EOF
)

  local resp
  resp=$(curl -s -X POST "$API_URL/tools/sql" \
    -H "$cleanup_header" \
    -H "Content-Type: application/json" \
    -d "{\"q\":\"$delete_sql\"}")

  local status
  status=$(echo "$resp" | jq -r '.status // empty')
  if [[ "$status" != "ok" ]]; then
    echo "Cleanup failed (skipped): $resp"
    return 0
  fi

  echo "Cleanup OK (book ${CREATED_BOOK_ID})"
  return 0
}

trap 'cleanup_created_book; rm -rf "$TMPDIR"' EXIT

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
pass "Login OK"

# Use first existing library for tests (avoid creating new libraries)
request "GET" "/libraries"
if [[ "$RESPONSE_CODE" != "200" ]]; then
  fail "Failed to list libraries ($RESPONSE_CODE): $RESPONSE_BODY"
fi
LIBRARY_ID=$(echo "$RESPONSE_BODY" | jq -r '.[] | select(.calibre_library_uuid != null and .calibre_library_uuid != "") | .id' | head -n 1)
CALIBRE_LIBRARY_UUID=$(echo "$RESPONSE_BODY" | jq -r '.[] | select(.calibre_library_uuid != null and .calibre_library_uuid != "") | .calibre_library_uuid' | head -n 1)
if [[ -z "$LIBRARY_ID" || -z "$CALIBRE_LIBRARY_UUID" ]]; then
  fail "No library with calibre_library_uuid found for tests"
fi
pass "Using library id=$LIBRARY_ID"

# Validation: missing calibre_library_uuid
log "GET /sync missing calibre_library_uuid should 422"
request "GET" "/sync?library_id=$LIBRARY_ID&limit=1"
if [[ "$RESPONSE_CODE" != "422" ]]; then
  fail "Expected 422, got $RESPONSE_CODE: $RESPONSE_BODY"
fi
pass "Missing calibre_library_uuid rejected"

# Validation: calibre_library_uuid mismatch
log "GET /sync with wrong calibre_library_uuid should 403"
request "GET" "/sync?library_id=$LIBRARY_ID&calibre_library_uuid=wrong-$CALIBRE_LIBRARY_UUID&limit=1"
if [[ "$RESPONSE_CODE" != "403" ]]; then
  fail "Expected 403, got $RESPONSE_CODE: $RESPONSE_BODY"
fi
pass "calibre_library_uuid mismatch rejected"

# Inventory on full sync
log "GET /sync include_inventory returns inventory payload"
request "GET" "/sync?library_id=$LIBRARY_ID&calibre_library_uuid=$CALIBRE_LIBRARY_UUID&include_inventory=true&limit=1"
if [[ "$RESPONSE_CODE" != "200" ]]; then
  fail "GET /sync failed ($RESPONSE_CODE): $RESPONSE_BODY"
fi
echo "$RESPONSE_BODY" | jq -e '.inventory | has("version") and has("min") and has("max") and has("active") and has("missing")' >/dev/null \
  && pass "Inventory present (full)" \
  || fail "Inventory missing in response: $RESPONSE_BODY"

# Create book
NOW=$(date +%s)
BOOK_ID=$((900000 + (RANDOM % 10000)))
BOOK_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
CREATE_PAYLOAD=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CALIBRE_LIBRARY_UUID",
  "changes": [{
    "op": "create",
    "item": {
      "id": $BOOK_ID,
      "uuid": "$BOOK_UUID",
      "title": "Contract Book $NOW",
      "authors": [{"name":"Tester","role":"author"}],
      "timestamps": {
        "created_at": $NOW
      },
      "last_modified": $NOW
    },
    "idempotency_key": "contract-create-$NOW"
  }]
}
EOF
)

log "POST /sync create"
request "POST" "/sync" "$CREATE_PAYLOAD"
CREATE_STATUS=$(echo "$RESPONSE_BODY" | jq -r '.results[0].status // empty')
if [[ "$RESPONSE_CODE" != "200" || ( "$CREATE_STATUS" != "applied" && "$CREATE_STATUS" != "merged" ) ]]; then
  fail "Create failed ($RESPONSE_CODE): $RESPONSE_BODY"
fi
SERVER_VERSION=$(echo "$RESPONSE_BODY" | jq -r '.results[0].server_item.version // empty')
NEW_CURSOR=$(echo "$RESPONSE_BODY" | jq -r '.new_cursor // empty')
if [[ -z "$SERVER_VERSION" || -z "$NEW_CURSOR" ]]; then
  fail "Missing server_version/cursor: $RESPONSE_BODY"
fi
pass "Create applied (version=$SERVER_VERSION)"
CREATED_BOOK_ID=$BOOK_ID

# Inventory hint on incremental pull (cursor not empty)
log "GET /sync include_inventory_hint on delta"
request "GET" "/sync?library_id=$LIBRARY_ID&calibre_library_uuid=$CALIBRE_LIBRARY_UUID&cursor=$NEW_CURSOR&include_inventory_hint=true&limit=1"
if [[ "$RESPONSE_CODE" != "200" ]]; then
  fail "GET /sync delta failed ($RESPONSE_CODE): $RESPONSE_BODY"
fi
echo "$RESPONSE_BODY" | jq -e '.inventory_hint | has("version") and has("active") and has("missing")' >/dev/null \
  && pass "Inventory hint present (delta)" \
  || fail "Inventory hint missing: $RESPONSE_BODY"

# Idempotency: re-send same create payload
log "Idempotency: reuse key with same payload"
request "POST" "/sync" "$CREATE_PAYLOAD"
REUSE_STATUS=$(echo "$RESPONSE_BODY" | jq -r '.results[0].status // empty')
if [[ "$RESPONSE_CODE" != "200" || -z "$REUSE_STATUS" || "$REUSE_STATUS" == "error" ]]; then
  fail "Idempotency reuse failed ($RESPONSE_CODE): $RESPONSE_BODY"
fi
pass "Idempotency reuse OK (status=$REUSE_STATUS)"

# Idempotency: reuse key with different payload should error
log "Idempotency: reuse key with different payload"
BAD_PAYLOAD=$(echo "$CREATE_PAYLOAD" | jq '.changes[0].item.title = "Different Title"')
request "POST" "/sync" "$BAD_PAYLOAD"
BAD_STATUS=$(echo "$RESPONSE_BODY" | jq -r '.results[0].status // empty')
BAD_ERROR=$(echo "$RESPONSE_BODY" | jq -r '.results[0].error // empty')
if [[ "$BAD_STATUS" != "error" ]]; then
  fail "Expected idempotency error, got $BAD_STATUS: $RESPONSE_BODY"
fi
echo "$BAD_ERROR" | grep -qi "Idempotency key reused" \
  && pass "Idempotency mismatch rejected" \
  || fail "Unexpected error message: $RESPONSE_BODY"

# Conflict: client version older than server
log "Conflict when client_version < server_version"
OLDER_VERSION=$((SERVER_VERSION - 1))
if [[ "$OLDER_VERSION" -lt 0 ]]; then
  OLDER_VERSION=0
fi
CONFLICT_PAYLOAD=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CALIBRE_LIBRARY_UUID",
  "changes": [{
    "op": "update",
    "item": {
      "id": $BOOK_ID,
      "uuid": "$BOOK_UUID",
      "version": $OLDER_VERSION,
      "title": "Client Older Update $NOW",
      "timestamps": {
        "last_modified": $(date -u +%s)
      }
    },
    "idempotency_key": "contract-conflict-$NOW"
  }]
}
EOF
)
request "POST" "/sync" "$CONFLICT_PAYLOAD"
CONFLICT_STATUS=$(echo "$RESPONSE_BODY" | jq -r '.results[0].status // empty')
if [[ "$CONFLICT_STATUS" != "conflict" ]]; then
  fail "Expected conflict, got $CONFLICT_STATUS: $RESPONSE_BODY"
fi
pass "Conflict detected"

# Delete and verify update is blocked (tombstone)
log "Delete book"
DELETE_PAYLOAD=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CALIBRE_LIBRARY_UUID",
  "changes": [{
    "op": "delete",
    "item": { "id": $BOOK_ID, "uuid": "$BOOK_UUID", "last_modified": $(date -u +%s) },
    "idempotency_key": "contract-delete-$NOW"
  }]
}
EOF
)
request "POST" "/sync" "$DELETE_PAYLOAD"
DELETE_STATUS=$(echo "$RESPONSE_BODY" | jq -r '.results[0].status // empty')
if [[ "$DELETE_STATUS" != "applied" && "$DELETE_STATUS" != "noop" ]]; then
  fail "Delete failed ($RESPONSE_CODE): $RESPONSE_BODY"
fi
pass "Delete applied"

log "Update on deleted book should conflict"
RESURRECT_PAYLOAD=$(cat <<EOF
{
  "library_id": $LIBRARY_ID,
  "calibre_library_uuid": "$CALIBRE_LIBRARY_UUID",
  "changes": [{
    "op": "update",
    "item": { "id": $BOOK_ID, "uuid": "$BOOK_UUID", "title": "Should Fail", "last_modified": $(date -u +%s) },
    "idempotency_key": "contract-update-deleted-$NOW"
  }]
}
EOF
)
request "POST" "/sync" "$RESURRECT_PAYLOAD"
RES_STATUS=$(echo "$RESPONSE_BODY" | jq -r '.results[0].status // empty')
RES_REASON=$(echo "$RESPONSE_BODY" | jq -r '.results[0].reason // empty')
if [[ "$RES_STATUS" != "conflict" || "$RES_REASON" != "deleted" ]]; then
  fail "Expected conflict deleted, got status=$RES_STATUS reason=$RES_REASON: $RESPONSE_BODY"
fi
pass "Delete tombstone prevents update"

echo "All sync protocol contract tests passed."
