#!/usr/bin/env bash
# Headless cover upload scenario using REST API
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
CALIMOB_COVER_IMAGE=${CALIMOB_COVER_IMAGE:-}

if [[ -z "$DISCOVERY_URL" || -z "$TEST_USER_EMAIL" || -z "$TEST_USER_PASSWORD" ]]; then
  echo "SKIP: set DISCOVERY_URL, TEST_USER_EMAIL, TEST_USER_PASSWORD" >&2
  exit 0
fi
if [[ -z "$CALIMOB_COVER_IMAGE" || ! -f "$CALIMOB_COVER_IMAGE" ]]; then
  echo "SKIP: set CALIMOB_COVER_IMAGE to a local jpg/png" >&2
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
  echo "SKIP: no library found for cover test" >&2
  exit 0
fi

BOOK_ID=$((RANDOM + 910000))
BOOK_UUID=$(python - <<'PY'
import uuid
print(str(uuid.uuid4()))
PY
)
NOW_TS=$(date -u +%s)

CREATE_PAYLOAD=$(cat <<JSON
{
  "library_id": $CALIMOB_LIBRARY_ID,
  "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
  "changes": [
    {
      "op": "create",
      "idempotency_key": "cover-create-$BOOK_ID",
      "item": {
        "id": $BOOK_ID,
        "uuid": "$BOOK_UUID",
        "title": "Cover Test",
        "authors": [{"name": "Tester"}],
        "cover": {"has_cover": true},
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

# Upload cover
UPLOAD_RES=$(curl -s -X PUT "$API_URL/items/$BOOK_ID/cover?library_id=$CALIMOB_LIBRARY_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: image/jpeg" \
  --data-binary "@$CALIMOB_COVER_IMAGE")

COVER_HASH=$(echo "$UPLOAD_RES" | jq -r '.cover_hash')
if [[ -z "$COVER_HASH" || "$COVER_HASH" == "null" ]]; then
  echo "FAIL: cover upload did not return hash" >&2
  echo "$UPLOAD_RES" >&2
  exit 1
fi

# Fetch cover to ensure it exists
HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" \
  -H "Authorization: Bearer $TOKEN" "$API_URL/items/$BOOK_ID/cover")

if [[ "$HTTP_CODE" != "200" && "$HTTP_CODE" != "302" ]]; then
  echo "FAIL: cover fetch returned $HTTP_CODE" >&2
  exit 1
fi

echo "PASS: cover upload scenario"
