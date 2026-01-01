#!/usr/bin/env bash
# Headless cover_missing scenario using REST + tools/sql
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# Load env if exists
if [[ -f "$SCRIPT_DIR/../../server/.env" ]]; then
  # shellcheck disable=SC1091
  source "$SCRIPT_DIR/../../server/.env"
fi

DISCOVERY_URL=${DISCOVERY_URL:-}
TEST_USER_EMAIL=${TEST_USER_EMAIL:-}
TEST_USER_PASSWORD=${TEST_USER_PASSWORD:-}
CALIMOB_LIBRARY_ID=${CALIMOB_LIBRARY_ID:-}
CALIBRE_LIBRARY_ID=${CALIBRE_LIBRARY_ID:-}
CALIMOB_SUPERADMIN_TOKEN=${CALIMOB_SUPERADMIN_TOKEN:-}
CALIMOB_COVER_IMAGE=${CALIMOB_COVER_IMAGE:-}

if [[ -z "$DISCOVERY_URL" || -z "$TEST_USER_EMAIL" || -z "$TEST_USER_PASSWORD" ]]; then
  echo "SKIP: set DISCOVERY_URL, TEST_USER_EMAIL, TEST_USER_PASSWORD" >&2
  exit 0
fi
if [[ -z "$CALIMOB_SUPERADMIN_TOKEN" ]]; then
  echo "SKIP: set CALIMOB_SUPERADMIN_TOKEN for tools/sql" >&2
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
  echo "SKIP: no library found for cover_missing test" >&2
  exit 0
fi

TMP_COVER=""
if [[ -z "$CALIMOB_COVER_IMAGE" || ! -f "$CALIMOB_COVER_IMAGE" ]]; then
  TMP_COVER=$(mktemp /tmp/calimob-cover-XXXXXX.png)
  python - <<PY
import base64
data = base64.b64decode(
    "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mP8"
    "/w8AAnsB9oWZlV0AAAAASUVORK5CYII="
)
with open("$TMP_COVER", "wb") as f:
    f.write(data)
PY
  CALIMOB_COVER_IMAGE="$TMP_COVER"
fi

BOOK_ID=$((RANDOM + 930000))
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
      "idempotency_key": "cover-missing-$BOOK_ID",
      "item": {
        "id": $BOOK_ID,
        "uuid": "$BOOK_UUID",
        "title": "Cover Missing Test",
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
if ! echo "$CREATE_RES" | jq -e '.results' >/dev/null 2>&1; then
  echo "FAIL: create sync failed" >&2
  echo "$CREATE_RES" >&2
  exit 1
fi

USER_ID=$(curl -s -X POST "$API_URL/tools/sql" \
  -H "Authorization: Bearer $CALIMOB_SUPERADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"q\":\"SELECT id FROM users WHERE email='$TEST_USER_EMAIL' LIMIT 1\"}" \
  | jq -r '.rows[0].id')

if [[ -z "$USER_ID" || "$USER_ID" == "null" ]]; then
  echo "FAIL: could not resolve user_id via tools/sql" >&2
  exit 1
fi

UPDATE_RES=$(curl -s -X POST "$API_URL/tools/sql" \
  -H "Authorization: Bearer $CALIMOB_SUPERADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"q\":\"UPDATE books SET cover_missing=1, updated_at=NOW() WHERE user_id=$USER_ID AND library_id=$CALIMOB_LIBRARY_ID AND calibre_book_id=$BOOK_ID\"}")

if ! echo "$UPDATE_RES" | jq -e '.affected' >/dev/null 2>&1; then
  echo "FAIL: cover_missing update failed" >&2
  echo "$UPDATE_RES" >&2
  exit 1
fi

PULL_RES=$(curl -s -H "Authorization: Bearer $TOKEN" \
  "$API_URL/sync?calibre_library_uuid=$CALIBRE_LIBRARY_ID&limit=50")

if ! echo "$PULL_RES" | jq -e --arg id "$BOOK_ID" \
  '.changes[]? | select((.item.id|tostring)==$id) | .cover_missing == true' >/dev/null 2>&1; then
  echo "FAIL: cover_missing change not found in pull" >&2
  echo "$PULL_RES" >&2
  exit 1
fi

UPLOAD_RES=$(curl -s -X PUT "$API_URL/items/uuid/$BOOK_UUID/cover?calibre_library_uuid=$CALIBRE_LIBRARY_ID" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: image/png" \
  --data-binary "@$CALIMOB_COVER_IMAGE")

COVER_HASH=$(echo "$UPLOAD_RES" | jq -r '.cover_hash')
if [[ -z "$COVER_HASH" || "$COVER_HASH" == "null" ]]; then
  echo "FAIL: cover upload did not return hash" >&2
  echo "$UPLOAD_RES" >&2
  exit 1
fi

CHECK_RES=$(curl -s -X POST "$API_URL/tools/sql" \
  -H "Authorization: Bearer $CALIMOB_SUPERADMIN_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"q\":\"SELECT cover_missing FROM books WHERE user_id=$USER_ID AND library_id=$CALIMOB_LIBRARY_ID AND calibre_book_id=$BOOK_ID\"}")

if ! echo "$CHECK_RES" | jq -e '.rows[0].cover_missing == 0' >/dev/null 2>&1; then
  echo "FAIL: cover_missing not cleared after upload" >&2
  echo "$CHECK_RES" >&2
  exit 1
fi

if [[ -n "$TMP_COVER" && -f "$TMP_COVER" ]]; then
  rm -f "$TMP_COVER"
fi

echo "PASS: cover_missing scenario"
