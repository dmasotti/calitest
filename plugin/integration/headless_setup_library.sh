#!/usr/bin/env bash
# Headless helper: create or reuse a test library (optionally seed data)
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
CALIBRE_LIBRARY_ID=${CALIBRE_LIBRARY_ID:-}
CALIMOB_LIBRARY_NAME=${CALIMOB_LIBRARY_NAME:-}
SEED_BOOKS=${SEED_BOOKS:-}
SEED_BOOKS_COUNT=${SEED_BOOKS_COUNT:-}

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

if [[ -z "$CALIBRE_LIBRARY_ID" ]]; then
  CALIBRE_LIBRARY_ID=$(python - <<'PY'
import uuid
print(str(uuid.uuid4()))
PY
)
fi

LIBS=$(curl -s -H "Authorization: Bearer $TOKEN" "$API_URL/libraries")
EXISTING_ID=$(echo "$LIBS" | jq -r --arg id "$CALIBRE_LIBRARY_ID" '.[] | select(.calibre_library_uuid==$id) | .id' | head -n1)

if [[ -n "$EXISTING_ID" && "$EXISTING_ID" != "null" ]]; then
  CALIMOB_LIBRARY_ID="$EXISTING_ID"
else
  if [[ -z "$CALIMOB_LIBRARY_NAME" ]]; then
    CALIMOB_LIBRARY_NAME="Headless Test Library $(date -u +%Y%m%d%H%M%S)"
  fi
  CREATE_PAYLOAD=$(cat <<JSON
{
  "name": "$CALIMOB_LIBRARY_NAME",
  "type": "calibre",
  "calibre_library_uuid": "$CALIBRE_LIBRARY_ID"
}
JSON
)
  CREATE_RES=$(curl -s -X POST "$API_URL/libraries" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$CREATE_PAYLOAD")
  CALIMOB_LIBRARY_ID=$(echo "$CREATE_RES" | jq -r '.id')
  if [[ -z "$CALIMOB_LIBRARY_ID" || "$CALIMOB_LIBRARY_ID" == "null" ]]; then
    echo "FAIL: library create failed" >&2
    echo "$CREATE_RES" >&2
    exit 1
  fi
fi

if [[ -n "${SEED_BOOKS:-}" || -n "${SEED_BOOKS_COUNT:-}" ]]; then
  COUNT=${SEED_BOOKS_COUNT:-3}
  CHANGES=$(python - <<PY
import json
import time
import uuid
from datetime import datetime, timezone

count = int("$COUNT")
base = int(time.time()) % 1000000
now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
changes = []
    for i in range(count):
        bid = base + i + 100000
        changes.append({
            "op": "create",
            "idempotency_key": f"seed-{bid}",
            "item": {
                "id": bid,
                "uuid": str(uuid.uuid4()),
                "title": f"Seed Book {i+1}",
                "authors": [{"name": "Seeder"}],
            "tags": ["seed"],
            "last_modified": int(time.time())
        }
    })
print(json.dumps(changes))
PY
)
  SEED_PAYLOAD=$(cat <<JSON
{
  "library_id": $CALIMOB_LIBRARY_ID,
  "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
  "changes": $CHANGES
}
JSON
)
  SEED_RES=$(curl -s -X POST "$API_URL/sync" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Content-Type: application/json" \
    -d "$SEED_PAYLOAD")
  if ! echo "$SEED_RES" | jq -e '.results' >/dev/null 2>&1; then
    echo "FAIL: seed sync failed" >&2
    echo "$SEED_RES" >&2
    exit 1
  fi
fi

echo "CALIMOB_LIBRARY_ID=$CALIMOB_LIBRARY_ID"
echo "CALIMOB_SERVER_LIBRARY_ID=$CALIMOB_LIBRARY_ID"
echo "CALIBRE_LIBRARY_ID=$CALIBRE_LIBRARY_ID"
