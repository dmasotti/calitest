#!/usr/bin/env bash
# Test for infinite loop issue in sync

set -euo pipefail

if [[ -f "$(dirname "$0")/.env" ]]; then
  source "$(dirname "$0")/.env"
fi

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

LOGFILE="infinite_loop_test.log"
rm -f "$LOGFILE"

curl() {
    command curl -sS "$@"
}

DISCOVERY_URL=${DISCOVERY_URL:-http://localhost}
DISCOVERY_ENDPOINT="$DISCOVERY_URL/discovery.php"

echo "Querying discovery: $DISCOVERY_ENDPOINT"
RAW_DISCOVERY_RESP=$(curl "$DISCOVERY_ENDPOINT")
API_URL=$(echo "$RAW_DISCOVERY_RESP" | jq -r '.api_url // empty' 2>/dev/null || true)
if [ -z "$API_URL" ] || [ "$API_URL" = "null" ]; then
  RAW_DISCOVERY_RESP=$(curl "$DISCOVERY_URL/api/discovery")
  API_URL=$(echo "$RAW_DISCOVERY_RESP" | jq -r '.api_url // empty' 2>/dev/null || true)
fi
if [ -z "$API_URL" ] || [ "$API_URL" = "null" ]; then
  API_URL="$DISCOVERY_URL/api"
fi

echo "API URL: $API_URL"

if [ -z "$TEST_EMAIL" ] || [ -z "$TEST_PASSWORD" ]; then
  echo "Please set TEST_USER_EMAIL and TEST_USER_PASSWORD env vars"
  exit 2
fi

echo "Logging in as $TEST_EMAIL"
LOGIN_RESP=$(curl -X POST -H "Content-Type: application/json" -d "{ \"email\": \"$TEST_EMAIL\", \"password\": \"$TEST_PASSWORD\" }" "$API_URL/auth/login")
echo "LOGIN_RESP: $LOGIN_RESP" >> "$LOGFILE"
TOKEN=$(echo "$LOGIN_RESP" | jq -r '.token // empty')
if [ -z "$TOKEN" ]; then
  echo "Login failed or token not returned: $LOGIN_RESP"
  exit 3
fi
AUTH_HEADER="Authorization: Bearer $TOKEN"

echo "Token acquired"

echo "Creating a test library"
LIB_NAME="infinite_loop_test_$(date +%s)"
CALIBRE_LIB_UUID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$(date +%s)-$RANDOM")
CREATE_LIB_RESP=$(curl -X POST -H "Content-Type: application/json" -H "$AUTH_HEADER" -d "{ \"name\": \"$LIB_NAME\", \"description\": \"infinite loop test\", \"type\": \"calibre\", \"calibre_library_uuid\": \"$CALIBRE_LIB_UUID\" }" "$API_URL/libraries")
LIB_ID=$(echo "$CREATE_LIB_RESP" | jq -r '.id // empty')
if [ -z "$LIB_ID" ]; then
  echo "Failed creating library: $CREATE_LIB_RESP"
  exit 4
fi

echo "Created library id=$LIB_ID calibre_uuid=$CALIBRE_LIB_UUID"

# Create a large number of books
NUM_BOOKS=500
echo "Creating $NUM_BOOKS books..."
CHANGES="["
for i in $(seq 1 $NUM_BOOKS); do
  CLIENT_BOOK_ID=$((100000 + i))
  CLIENT_TITLE="Book $i"
  CLIENT_CREATE_KEY="create_$i"
  BOOK_UUID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$(date +%s)-$RANDOM")
  CHANGE=$(cat <<JSON
    {
      "op": "create",
      "idempotency_key": "$CLIENT_CREATE_KEY",
      "item": {
        "id": $CLIENT_BOOK_ID,
        "uuid": "$BOOK_UUID",
        "title": "$CLIENT_TITLE",
        "client_ids": { "calibre:$CALIBRE_LIB_UUID:$CLIENT_BOOK_ID": "$CLIENT_BOOK_ID" },
        "last_modified": $(date -u +%s)
      }
    }
JSON
)
  CHANGES="$CHANGES$CHANGE"
  if [ $i -lt $NUM_BOOKS ]; then
    CHANGES="$CHANGES,"
  fi
done
CHANGES="$CHANGES]"

CREATE_PAYLOAD=$(cat <<JSON
{
  "client_cursor": null,
  "library_id": $LIB_ID,
  "calibre_library_uuid": "$CALIBRE_LIB_UUID",
  "changes": $CHANGES
}
JSON
)

echo "Creating $NUM_BOOKS books..."
echo "CURL ARGS: $API_URL/sync -X POST -H \"Content-Type: application/json\" -H \"$AUTH_HEADER\" -d \"$CREATE_PAYLOAD\""
CREATE_RESP=$(curl "$API_URL/sync" -X POST -H "Content-Type: application/json" -H "$AUTH_HEADER" -d "$CREATE_PAYLOAD")
echo "$CREATE_RESP" | jq '.'

# Test steps for infinite loop will be added here
echo "Starting pull loop to detect infinite loop..."
CURSOR=""
HAS_MORE=true
ITERATIONS=0
MAX_ITERATIONS=$((NUM_BOOKS / 200 + 5))

while [ "$HAS_MORE" = "true" ]; do
  echo "Iteration $ITERATIONS, cursor: $CURSOR"
  if [ -n "$CURSOR" ] && [ "$CURSOR" != "null" ]; then
    PULL_URL="$API_URL/sync?library_id=$LIB_ID&calibre_library_uuid=$CALIBRE_LIB_UUID&cursor=$CURSOR&limit=200"
  else
    PULL_URL="$API_URL/sync?library_id=$LIB_ID&calibre_library_uuid=$CALIBRE_LIB_UUID&limit=200"
  fi
  PULL_RESP=$(curl "$PULL_URL")
  
  HAS_MORE=$(echo "$PULL_RESP" | jq -r '.has_more')
  CURSOR=$(echo "$PULL_RESP" | jq -r '.new_cursor')
  
  ITERATIONS=$((ITERATIONS + 1))
  
  if [ $ITERATIONS -gt $MAX_ITERATIONS ]; then
    echo "❌ FAILED: Infinite loop detected. Exceeded max iterations ($MAX_ITERATIONS)."
    exit 1
  fi
done

echo "✅ PASSED: Sync loop finished in $ITERATIONS iterations."


echo "Cleaning up test library"
curl -sS -X DELETE -H "$AUTH_HEADER" "$API_URL/library/$LIB_ID" >/dev/null || true

echo "Test finished"
