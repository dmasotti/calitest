#!/usr/bin/env bash
# Tests for sync flow (server and client reconciliation)
# Usage: set env DISCOVERY_URL, TEST_USER_EMAIL, TEST_USER_PASSWORD then run
# Requires: curl, jq

set -euo pipefail

DISCOVERY_URL=${DISCOVERY_URL:-http://localhost}
TEST_EMAIL=${TEST_USER_EMAIL:-}
TEST_PASSWORD=${TEST_USER_PASSWORD:-}

if ! command -v curl >/dev/null 2>&1; then
  echo "curl required"
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "jq required"
  exit 1
fi

# HTTP wrapper: log all requests and responses (including errors) to run_sync_http.log
LOGFILE="run_sync_http.log"
rm -f "$LOGFILE"

curl() {
  # Wrapper around system curl that saves response body and HTTP status to log file.
  # Usage: curl [args...]
  local tmp out code
  tmp=$(mktemp)
  # Run curl silently but capture stderr; write body to tmp and append a status token to stdout
  out=$(command curl -sS "$@" -w "__HTTP_STATUS__:%{http_code}" -o "$tmp" 2>&1) || true
  # Extract HTTP status code from out (last token)
  code="0"
  if [[ "$out" =~ __HTTP_STATUS__:([0-9]{3})$ ]]; then
    code="${BASH_REMATCH[1]}"
  else
    # fallback: try reading last line of tmp if write-out failed
    code="$(tail -n1 "$tmp" | tr -d '\r' || echo 0)"
  fi
  # Append stderr (out without the status token) and body and status to logfile
  # Remove status token from out for logging
  local out_clean
  out_clean="${out%__HTTP_STATUS__:*}"
  # Safer logging: avoid printf interpreting strings that may start with dashes
  echo '--- CURL STDERR ---' >>"$LOGFILE"
  printf '%s\n' "$out_clean" >>"$LOGFILE"
  echo '--- CURL BODY ---' >>"$LOGFILE"
  cat "$tmp" >>"$LOGFILE"
  echo "" >>"$LOGFILE"
  printf '__HTTP_STATUS__:%s\n' "$code" >>"$LOGFILE"

  # Print body to stdout for script consumption
  cat "$tmp"
  # Only print HTTP_STATUS to stdout if stdout is a terminal (avoid breaking pipes to jq)
  if [ -t 1 ]; then
    echo "HTTP_STATUS:$code"
  fi
  rm -f "$tmp"

  # Return non-zero if HTTP status >= 400 to respect set -e behavior
  if [ "$code" -ge 400 ]; then
    return 22
  fi
  return 0
}

# Helper for curl with auth
api_curl() {
  curl -sS -H "Accept: application/json" -H "$AUTH_HEADER" "$@"
}

echo "Discovery URL: $DISCOVERY_URL"
# Resolve discovery endpoint
if [[ "$DISCOVERY_URL" =~ /api/ ]]; then
  DISCOVERY_ENDPOINT="$DISCOVERY_URL"
else
  DISCOVERY_ENDPOINT="$DISCOVERY_URL/api/discovery"
fi

echo "Querying discovery: $DISCOVERY_ENDPOINT"
API_URL=$(curl -sS "$DISCOVERY_ENDPOINT" | jq -r '.api_url // empty') || true
if [ -z "$API_URL" ]; then
  # fallback: try constructing from discovery host
  API_URL="$DISCOVERY_URL/api"
fi

echo "API URL: $API_URL"

if [ -z "$TEST_EMAIL" ] || [ -z "$TEST_PASSWORD" ]; then
  echo "Please set TEST_USER_EMAIL and TEST_USER_PASSWORD env vars"
  exit 2
fi

# Login to get token
echo "Logging in as $TEST_EMAIL"
LOGIN_RESP=$(curl -sS -X POST "$API_URL/auth/login" -H "Content-Type: application/json" -d \
  "{ \"email\": \"$TEST_EMAIL\", \"password\": \"$TEST_PASSWORD\" }")
TOKEN=$(echo "$LOGIN_RESP" | jq -r '.token // empty')
if [ -z "$TOKEN" ]; then
  echo "Login failed or token not returned: $LOGIN_RESP"
  exit 3
fi
AUTH_HEADER="Authorization: Bearer $TOKEN"

echo "Token acquired"

# Helper for curl with auth
api_curl() {
  curl -s -f -H "Accept: application/json" -H "$AUTH_HEADER" "$@"
}

# 1) List libraries
echo "Listing libraries"
LIBS_JSON=$(api_curl "$API_URL/libraries")
echo "$LIBS_JSON" | jq '.'

# 2) Create a test library (unique name)
LIB_NAME="test_sync_$(date +%s)"
CALIBRE_LIB_UUID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$(date +%s)-$RANDOM")
CREATE_LIB_RESP=$(curl -sS -X POST "$API_URL/libraries" -H "Content-Type: application/json" -H "$AUTH_HEADER" -d \
  "{ \"name\": \"$LIB_NAME\", \"description\": \"sync test\", \"type\": \"calibre\", \"calibre_library_id\": \"$CALIBRE_LIB_UUID\" }")
LIB_ID=$(echo "$CREATE_LIB_RESP" | jq -r '.id // empty')
if [ -z "$LIB_ID" ]; then
  echo "Failed creating library: $CREATE_LIB_RESP"
  exit 4
fi

echo "Created library id=$LIB_ID calibre_uuid=$CALIBRE_LIB_UUID"

# 3) Add book via legacy endpoint POST /api/sync/books
echo "Creating legacy book via /api/sync/books"
LEGACY_LOCAL_ID=$((RANDOM % 9000 + 1000))  # ID tra 1000-9999
LEGACY_BOOK_TITLE="Legacy Book $(date +%s)"
LEGACY_PAYLOAD=$(jq -n --arg lib "$LIB_ID" --arg local_id "$LEGACY_LOCAL_ID" --arg title "$LEGACY_BOOK_TITLE" '{ device_uuid: "test-device", library_id: ($lib|tonumber), library_name: "test", books: [{ local_book_id: $local_id, title: $title }] }')
LEGACY_RESP=$(curl -sS -X POST "$API_URL/sync/books" -H "Content-Type: application/json" -H "$AUTH_HEADER" -d "$LEGACY_PAYLOAD")
echo "$LEGACY_RESP" | jq '.'

# 4) Add book via two-way sync (simulate client create)
CLIENT_BOOK_ID=100000
CLIENT_TITLE="Sync Created Book $(date +%s)"
CLIENT_CHANGE_KEY="c_$(date +%s)"
CHANGE_PAYLOAD=$(jq -n --arg id "$CLIENT_BOOK_ID" --arg title "$CLIENT_TITLE" --arg client_key "calibre:$CALIBRE_LIB_UUID:$CLIENT_BOOK_ID" --argjson ts "$(date -u +%Y-%m-%dT%H:%M:%SZ | sed 's/.*/"&"/')" '{ client_cursor: null, library_id: ($env.LIB_ID|tonumber), calibre_library_id: $env.CALIBRE_LIB_UUID, changes: [ { op: "create", idempotency_key: ($env.CLIENT_CHANGE_KEY), item: { id: ($env.CLIENT_BOOK_ID|tonumber), title: $env.CLIENT_TITLE, client_ids: { ($env.CLIENT_KEY): ($env.CLIENT_BOOK_ID|tostring) }, timestamps: { updated_at: (now | tostring) } } } ] }' 2>/dev/null)
# fallback simpler payload if jq complex interpolation fails
CHANGE_PAYLOAD=$(cat <<JSON
{
  "client_cursor": null,
  "library_id": $LIB_ID,
  "calibre_library_id": "$CALIBRE_LIB_UUID",
  "changes": [
    {
      "op": "create",
      "idempotency_key": "$CLIENT_CHANGE_KEY",
      "item": {
        "id": $CLIENT_BOOK_ID,
        "title": "$CLIENT_TITLE",
        "client_ids": { "calibre:$CALIBRE_LIB_UUID:$CLIENT_BOOK_ID": "$CLIENT_BOOK_ID" },
        "timestamps": { "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)" }
      }
    }
  ]
}
JSON
)

echo "Push sync create payload: $CHANGE_PAYLOAD"
SYNC_CREATE_RESP=$(curl -sS -X POST "$API_URL/sync" -H "Content-Type: application/json" -H "$AUTH_HEADER" -d "$CHANGE_PAYLOAD")
echo "$SYNC_CREATE_RESP" | jq '.'

# 5) Verify both books exist via GET /api/user-books
echo "Listing user-books for library"
USER_BOOKS=$(api_curl "$API_URL/user-books?library_id=$LIB_ID")
echo "$USER_BOOKS" | jq '.'

if echo "$USER_BOOKS" | jq -e ".[] | select(.title==\"$CLIENT_TITLE\")" >/dev/null; then
  echo "Client-created book found"
else
  echo "Client-created book NOT found"
  exit 5
fi

# 6) Delete book via sync (simulate client deletion)
echo "Deleting client-created book via sync (op=delete)"
DELETE_PAYLOAD=$(cat <<JSON
{
  "client_cursor": null,
  "library_id": $LIB_ID,
  "calibre_library_id": "$CALIBRE_LIB_UUID",
  "changes": [
    {
      "op": "delete",
      "idempotency_key": "del_$(date +%s)",
      "item": {
        "id": $CLIENT_BOOK_ID,
        "timestamps": { "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)" }
      }
    }
  ]
}
JSON
)

DELETE_RESP=$(curl -sS -X POST "$API_URL/sync" -H "Content-Type: application/json" -H "$AUTH_HEADER" -d "$DELETE_PAYLOAD")
echo "$DELETE_RESP" | jq '.'

# 7) Verify deletion by requesting item (items/{id} returns withTrashed)
echo "Verify tombstone exists via GET /api/items/$CLIENT_BOOK_ID"
ITEM_RESP=$(api_curl "$API_URL/items/$CLIENT_BOOK_ID?library_id=$LIB_ID&calibre_library_id=$CALIBRE_LIB_UUID")
echo "$ITEM_RESP" | jq '.'

# 8) Conflict simulation
# Create a new book for conflict test
CONFLICT_BOOK_ID=200000
CONFLICT_TITLE="Conflict Book $(date +%s)"
CONFLICT_CREATE_PAYLOAD=$(cat <<JSON
{
  "client_cursor": null,
  "library_id": $LIB_ID,
  "calibre_library_id": "$CALIBRE_LIB_UUID",
  "changes": [
    {
      "op": "create",
      "idempotency_key": "conf_create_$(date +%s)",
      "item": {
        "id": $CONFLICT_BOOK_ID,
        "title": "$CONFLICT_TITLE",
        "timestamps": { "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)" }
      }
    }
  ]
}
JSON
)

echo "Creating conflict book"
api_curl -X POST "$API_URL/sync" -H "Content-Type: application/json" -d "$CONFLICT_CREATE_PAYLOAD" | jq '.'

# Update server-side (simulate another client) with newer timestamp
NEWER_TITLE="Conflict Book Server-Updated"
SERVER_UPDATE_PAYLOAD=$(cat <<JSON
{
  "client_cursor": null,
  "library_id": $LIB_ID,
  "calibre_library_id": "$CALIBRE_LIB_UUID",
  "changes": [
    {
      "op": "update",
      "idempotency_key": "server_update_$(date +%s)",
      "item": {
        "id": $CONFLICT_BOOK_ID,
        "title": "$NEWER_TITLE",
        "timestamps": { "updated_at": "$(date -u -d '+1 minute' +%Y-%m-%dT%H:%M:%SZ)" }
      }
    }
  ]
}
JSON
)

echo "Applying server-side newer update"
api_curl -X POST "$API_URL/sync" -H "Content-Type: application/json" -d "$SERVER_UPDATE_PAYLOAD" | jq '.'

# Now client sends an update with older timestamp -> expect conflict
CLIENT_OLDER_UPDATE_PAYLOAD=$(cat <<JSON
{
  "client_cursor": null,
  "library_id": $LIB_ID,
  "calibre_library_id": "$CALIBRE_LIB_UUID",
  "changes": [
    {
      "op": "update",
      "idempotency_key": "client_old_update_$(date +%s)",
      "item": {
        "id": $CONFLICT_BOOK_ID,
        "title": "Client-Older-Title",
        "timestamps": { "updated_at": "$(date -u -d '-1 minute' +%Y-%m-%dT%H:%M:%SZ)" },
        "version": 1
      }
    }
  ]
}
JSON
)

echo "Sending client older update to trigger conflict"
CONFLICT_RESP=$(api_curl -X POST "$API_URL/sync" -H "Content-Type: application/json" -d "$CLIENT_OLDER_UPDATE_PAYLOAD")
echo "$CONFLICT_RESP" | jq '.'

# Inspect results for conflict
if echo "$CONFLICT_RESP" | jq -e '.results[] | select(.status=="conflict")' >/dev/null; then
  echo "Conflict detected as expected"
else
  echo "Expected conflict but none found"
  exit 6
fi

# 9) Multi-user / UUID isolation tests (optional)
if [ -n "${TEST_USER_EMAIL_2:-}" ] && [ -n "${TEST_USER_PASSWORD_2:-}" ]; then
  echo "Running multi-user isolation tests with second user $TEST_USER_EMAIL_2"
  # Login second user
  LOGIN2_RESP=$(curl -s -f -X POST "$API_URL/auth/login" -H "Content-Type: application/json" -d \
    "{ \"email\": \"$TEST_USER_EMAIL_2\", \"password\": \"$TEST_USER_PASSWORD_2\" }")
  TOKEN2=$(echo "$LOGIN2_RESP" | jq -r '.token // empty') || true
  if [ -z "$TOKEN2" ]; then
    echo "Second user login failed: $LOGIN2_RESP";
  else
    AUTH2_HEADER="Authorization: Bearer $TOKEN2"
    # Create second library for user2
    LIB_NAME2="test_sync_user2_$(date +%s)"
    CALIBRE_LIB_UUID2=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$(date +%s)-$RANDOM")
    CREATE_LIB2_RESP=$(curl -s -f -X POST "$API_URL/libraries" -H "Content-Type: application/json" -H "$AUTH2_HEADER" -d \
      "{ \"name\": \"$LIB_NAME2\", \"description\": \"sync test user2\", \"type\": \"calibre\", \"calibre_library_id\": \"$CALIBRE_LIB_UUID2\" }")
    LIB2_ID=$(echo "$CREATE_LIB2_RESP" | jq -r '.id // empty') || true
    echo "Created library for user2 id=$LIB2_ID calibre_uuid=$CALIBRE_LIB_UUID2"

    # Use a shared UUID to verify isolation
    SHARED_UUID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "shared-$(date +%s)-$RANDOM")

    # Create a book under user1 with SHARED_UUID
    BOOK1_ID=300001
    PAYLOAD1=$(cat <<JSON
{
  "client_cursor": null,
  "library_id": $LIB_ID,
  "calibre_library_id": "$CALIBRE_LIB_UUID",
  "changes": [
    {
      "op": "create",
      "idempotency_key": "shared_create_1_$(date +%s)",
      "item": {
        "id": $BOOK1_ID,
        "uuid": "$SHARED_UUID",
        "title": "Shared UUID Book User1",
        "timestamps": { "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)" }
      }
    }
  ]
}
JSON
)
    echo "Creating shared-uuid book for user1"
    api_curl -X POST "$API_URL/sync" -H "Content-Type: application/json" -d "$PAYLOAD1" | jq '.'

    # Create a book under user2 with same SHARED_UUID
    BOOK2_ID=400002
    PAYLOAD2=$(cat <<JSON
{
  "client_cursor": null,
  "library_id": $LIB2_ID,
  "calibre_library_id": "$CALIBRE_LIB_UUID2",
  "changes": [
    {
      "op": "create",
      "idempotency_key": "shared_create_2_$(date +%s)",
      "item": {
        "id": $BOOK2_ID,
        "uuid": "$SHARED_UUID",
        "title": "Shared UUID Book User2",
        "timestamps": { "updated_at": "$(date -u +%Y-%m-%dT%H:%M:%SZ)" }
      }
    }
  ]
}
JSON
)
    echo "Creating shared-uuid book for user2"
    curl -s -f -X POST "$API_URL/sync" -H "Content-Type: application/json" -H "$AUTH2_HEADER" -d "$PAYLOAD2" | jq '.'

    # Verify both exist and are distinct
    UB1=$(api_curl "$API_URL/user-books?library_id=$LIB_ID" | jq -c ".[] | select(.uuid==\"$SHARED_UUID\")" || true)
    UB2=$(curl -s -f -H "Accept: application/json" -H "$AUTH2_HEADER" "$API_URL/user-books?library_id=$LIB2_ID" | jq -c ".[] | select(.uuid==\"$SHARED_UUID\")" || true)

    echo "User1 book with shared uuid: $UB1"
    echo "User2 book with shared uuid: $UB2"

    if [ -z "$UB1" ] || [ -z "$UB2" ]; then
      echo "Isolation test failed: one of the user libraries does not contain the shared-uuid book"
      exit 7
    fi

    ID1=$(echo "$UB1" | jq -r '.id')
    ID2=$(echo "$UB2" | jq -r '.id')
    if [ "$ID1" = "$ID2" ]; then
      echo "Isolation test failed: same server id across users"
      exit 8
    fi

    echo "Isolation test passed: same uuid can exist separately per user/library"

    # Cleanup user2 library
    echo "Deleting test library for user2"
    curl -s -f -X DELETE "$API_URL/library/$LIB2_ID" -H "$AUTH2_HEADER" || true
  fi
else
  echo "Second user credentials not provided; skipping multi-user isolation tests"
fi

# 10) Cleanup: delete created library via web endpoint
echo "Deleting test library"
DEL_LIB_RESP=$(curl -s -f -X DELETE "$API_URL/library/$LIB_ID" -H "$AUTH_HEADER") || true
echo "Library delete response: $DEL_LIB_RESP"

# Done
echo "All tests completed successfully"
exit 0
