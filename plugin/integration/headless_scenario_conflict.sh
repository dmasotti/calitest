#!/usr/bin/env bash
# Headless conflict scenario using REST API
set -euo pipefail

# Load env if exists
if [[ -f "$(dirname "$0")/../../server/.env" ]]; then
  # shellcheck disable=SC1091
  source "$(dirname "$0")/../../server/.env"
fi

DISCOVERY_URL=${DISCOVERY_URL:-}
TEST_USER_EMAIL=${TEST_USER_EMAIL:-}
TEST_USER_PASSWORD=${TEST_USER_PASSWORD:-}
CALIMOB_LIBRARY_ID=${CALIMOB_LIBRARY_ID:-}
CALIBRE_LIBRARY_ID=${CALIBRE_LIBRARY_ID:-}

if [[ -z "$DISCOVERY_URL" || -z "$TEST_USER_EMAIL" || -z "$TEST_USER_PASSWORD" ]]; then
  echo "SKIP: set DISCOVERY_URL, TEST_USER_EMAIL, TEST_USER_PASSWORD" >&2
  exit 0
fi

API_URL=$(curl -s "${DISCOVERY_URL}/discovery.php" | jq -r '.api_url // empty' 2>/dev/null || true)
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  API_URL=$(curl -s "${DISCOVERY_URL}/api/discovery" | jq -r '.api_url // empty' 2>/dev/null || true)
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

# Pick library ids if not provided
if [[ -z "$CALIMOB_LIBRARY_ID" || -z "$CALIBRE_LIBRARY_ID" ]]; then
  LIBS=$(curl -s -H "Authorization: Bearer $TOKEN" "$API_URL/libraries")
  CALIMOB_LIBRARY_ID=$(echo "$LIBS" | jq -r '.[0].id')
  CALIBRE_LIBRARY_ID=$(echo "$LIBS" | jq -r '.[0].calibre_library_uuid')
fi

if [[ -z "$CALIMOB_LIBRARY_ID" || -z "$CALIBRE_LIBRARY_ID" || "$CALIMOB_LIBRARY_ID" == "null" ]]; then
  echo "SKIP: no library found for conflict test" >&2
  exit 0
fi

BOOK_ID=$((RANDOM + 900000))
BOOK_UUID=$(python - <<'PY'
import uuid
print(str(uuid.uuid4()))
PY
)
NOW_TS=$(date -u +%s)

CREATE_PAYLOAD=$(cat <<JSON
{
  "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
  "changes": [
    {
      "op": "create",
      "idempotency_key": "conflict-create-$BOOK_ID",
      "item": {
        "id": $BOOK_ID,
        "uuid": "$BOOK_UUID",
        "title": "Conflict Test A",
        "authors": [{"name": "Tester"}],
        "last_modified": $NOW_TS
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

SERVER_VERSION=$(echo "$CREATE_RES" | jq -r '.results[0].server_item.version')
if [[ -z "$SERVER_VERSION" || "$SERVER_VERSION" == "null" ]]; then
  echo "FAIL: create did not return server version" >&2
  echo "$CREATE_RES" >&2
  exit 1
fi

# Send update with older version to force conflict
OLDER_VERSION=$((SERVER_VERSION - 1))
UPDATE_PAYLOAD=$(cat <<JSON
{
  "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
  "changes": [
    {
      "op": "update",
      "idempotency_key": "conflict-update-$BOOK_ID",
      "item": {
        "id": $BOOK_ID,
        "uuid": "$BOOK_UUID",
        "title": "Conflict Test B",
        "version": $OLDER_VERSION,
        "last_modified": $NOW_TS
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

STATUS=$(echo "$UPDATE_RES" | jq -r '.results[0].status')
if [[ "$STATUS" != "conflict" ]]; then
  echo "FAIL: expected conflict, got $STATUS" >&2
  echo "$UPDATE_RES" >&2
  exit 1
fi

echo "PASS: conflict scenario"
