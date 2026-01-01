#!/usr/bin/env bash
# Test for book resurrection issue

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

LOGFILE="resurrection_test.log"
rm -f "$LOGFILE"

curl_wrapper() {
  local url="${1}"
  shift || true # Shift even if there are no more args
  local args=("$@")
  local tmp_headers=$(mktemp)
  local tmp_body=$(mktemp)
  local http_code

  local curl_cmd_opts=(-sS -D "$tmp_headers" -o "$tmp_body")
  if [ "${#args[@]}" -gt 0 ]; then
    curl_cmd_opts+=("${args[@]}")
  fi

  # Run curl, writing headers to tmp_headers and body to tmp_body
  if ! command curl "${curl_cmd_opts[@]}" "$url"; then
    echo "curl command failed for $url" >&2
    rm -f "$tmp_headers" "$tmp_body"
    return 1
  fi

  # Extract HTTP status code from headers
  http_code=$(grep -i '^HTTP/' "$tmp_headers" | tail -n 1 | awk '{print $2}')
  if [ -z "$http_code" ]; then
    echo "Failed to get HTTP status code for $url" >&2
    rm -f "$tmp_headers" "$tmp_body"
    return 1
  fi
  
  # Print body to stdout
  cat "$tmp_body"

  # Store HTTP status code in a globally accessible variable or return it in a structured way
  # For now, we'll assume the caller can get the HTTP status from the command's exit code,
  # or we'll pass it explicitly. For simplicity, we'll just exit on >=400 status.
  if [ "$http_code" -ge 400 ]; then
    echo "HTTP Error: $http_code for $url" >&2
    rm -f "$tmp_headers" "$tmp_body"
    return 1
  fi
  rm -f "$tmp_headers" "$tmp_body"
  return 0
}

# Wrapper for API calls using the new curl_wrapper
api_curl() {
  local url="${1}"; shift
  local resp_body
  if ! resp_body=$(curl_wrapper "$url" -H "Accept: application/json" -H "$AUTH_HEADER" "$@"); then
    echo "API curl failed for $url" >&2
    return 1
  fi
  echo "$resp_body"
  return 0
}

# Wrapper for general curl calls (e.g., discovery, login)
general_curl() {
  local url="${1}"; shift
  local resp_body
  if ! resp_body=$(curl_wrapper "$url" "$@"); then
    echo "General curl failed for $url" >&2
    return 1
  fi
  echo "$resp_body"
  return 0
}

echo "Discovery URL: $DISCOVERY_URL"
DISCOVERY_ENDPOINT="$DISCOVERY_URL/discovery.php"

echo "Querying discovery: $DISCOVERY_ENDPOINT"
RAW_DISCOVERY_RESP=$(general_curl "$DISCOVERY_ENDPOINT")
API_URL=$(echo "$RAW_DISCOVERY_RESP" | jq -r '.api_url // empty' 2>/dev/null || true)
if [ -z "$API_URL" ] || [ "$API_URL" = "null" ]; then
  RAW_DISCOVERY_RESP=$(general_curl "$DISCOVERY_URL/api/discovery")
  API_URL=$(echo "$RAW_DISCOVERY_RESP" | jq -r '.api_url // empty' 2>/dev/null || true)
fi
if [ -z "$API_URL" ] || [ "$API_URL" = "null" ]; then
  # fallback: try constructing from discovery host
  API_URL="$DISCOVERY_URL/api"
fi

echo "API URL: $API_URL"

if [ -z "$TEST_EMAIL" ] || [ -z "$TEST_PASSWORD" ]; then
  echo "Please set TEST_USER_EMAIL and TEST_USER_PASSWORD env vars"
  exit 2
fi

echo "Logging in as $TEST_EMAIL"
LOGIN_RESP=$(general_curl "$API_URL/auth/login" -X POST -H "Content-Type: application/json" -d "{ \"email\": \"$TEST_EMAIL\", \"password\": \"$TEST_PASSWORD\" }")
TOKEN=$(echo "$LOGIN_RESP" | jq -r '.token // empty')
if [ -z "$TOKEN" ]; then
  echo "Login failed or token not returned: $LOGIN_RESP"
  exit 3
fi
AUTH_HEADER="Authorization: Bearer $TOKEN"

echo "Token acquired"

# 1) List libraries
echo "Listing libraries"
LIBS_JSON=$(api_curl "$API_URL/libraries")
echo "$LIBS_JSON" | jq '.'

echo "Token acquired"

echo "Creating a test library"
LIB_NAME="resurrection_test_$(date +%s)"
CALIBRE_LIB_UUID=$(uuidgen 2>/dev/null || cat /proc/sys/kernel/random/uuid 2>/dev/null || echo "$(date +%s)-$RANDOM")
CREATE_LIB_RESP=$(general_curl "$API_URL/libraries" -X POST -H "Content-Type: application/json" -H "$AUTH_HEADER" -d "{ \"name\": \"$LIB_NAME\", \"description\": \"resurrection test\", \"type\": \"calibre\", \"calibre_library_uuid\": \"$CALIBRE_LIB_UUID\" }")
LIB_ID=$(echo "$CREATE_LIB_RESP" | jq -r '.id // empty')
if [ -z "$LIB_ID" ]; then
  echo "Failed creating library: $CREATE_LIB_RESP"
  exit 4
fi

echo "Created library id=$LIB_ID calibre_uuid=$CALIBRE_LIB_UUID"

# Test steps will be added here

# 1. Create a book
CLIENT_BOOK_ID=300000
CLIENT_TITLE="Resurrection Test Book $(date +%s)"
CLIENT_CREATE_KEY="create_$(date +%s)"
CREATE_PAYLOAD=$(cat <<JSON
{
  "client_cursor": null,
  "library_id": $LIB_ID,
  "calibre_library_uuid": "$CALIBRE_LIB_UUID",
  "changes": [
    {
      "op": "create",
      "idempotency_key": "$CLIENT_CREATE_KEY",
      "item": {
        "id": $CLIENT_BOOK_ID,
        "title": "$CLIENT_TITLE",
        "client_ids": { "calibre:$CALIBRE_LIB_UUID:$CLIENT_BOOK_ID": "$CLIENT_BOOK_ID" },
        "last_modified": $(date -u +%s)
      }
    }
  ]
}
JSON
)

echo "Creating a book with ID $CLIENT_BOOK_ID"
CREATE_RESP=$(curl -sS -X POST "$API_URL/sync" -H "Content-Type: application/json" -H "$AUTH_HEADER" -d "$CREATE_PAYLOAD")
echo "$CREATE_RESP" | jq '.'
INITIAL_CURSOR=$(echo "$CREATE_RESP" | jq -r '.new_cursor')
echo "Initial cursor: $INITIAL_CURSOR"

# 2. Delete the book
CLIENT_DELETE_KEY="delete_$(date +%s)"
DELETE_PAYLOAD=$(cat <<JSON
{
  "client_cursor": "$INITIAL_CURSOR",
  "library_id": $LIB_ID,
  "calibre_library_uuid": "$CALIBRE_LIB_UUID",
  "changes": [
    {
      "op": "delete",
      "idempotency_key": "$CLIENT_DELETE_KEY",
      "item": {
        "id": $CLIENT_BOOK_ID,
        "last_modified": $(date -u +%s)
      }
    }
  ]
}
JSON
)

echo "Deleting the book with ID $CLIENT_BOOK_ID"
DELETE_RESP=$(curl -sS -X POST "$API_URL/sync" -H "Content-Type: application/json" -H "$AUTH_HEADER" -d "$DELETE_PAYLOAD")
echo "$DELETE_RESP" | jq '.'
DELETE_CURSOR=$(echo "$DELETE_RESP" | jq -r '.new_cursor')
echo "Cursor after delete: $DELETE_CURSOR"


# 3. Perform a pull sync to check for resurrection
echo "Performing pull sync with cursor after delete to check for resurrection"
PULL_RESP=$(api_curl "$API_URL/sync?calibre_library_uuid=$CALIBRE_LIB_UUID&cursor=$DELETE_CURSOR")
echo "$PULL_RESP" | jq '.'

# 4. Assert: Check if the pull response contains an op for the deleted book
RESURRECTED_OP=$(echo "$PULL_RESP" | jq -r ".changes[] | select(.item.id == \"$CLIENT_BOOK_ID\") | .op")

if [ -n "$RESURRECTED_OP" ]; then
  echo "❌ FAILED: Book with ID $CLIENT_BOOK_ID was resurrected with op: $RESURRECTED_OP"
  exit 1
else
  echo "✅ PASSED: Book with ID $CLIENT_BOOK_ID was not resurrected."
fi


echo "Cleaning up test library"
# Attempt to delete the library. Allow failure as the test is primarily about resurrection, not cleanup.
# The server error indicates DELETE is not allowed, so we will try to list and delete if possible, or just ignore.
# For now, we just ignore the error.
general_curl "$API_URL/library/$LIB_ID" -X DELETE -H "$AUTH_HEADER" || true

echo "Test finished"
