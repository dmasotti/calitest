#!/usr/bin/env bash
# Quick test for legacy book creation endpoint

set -e

API_URL="https://coral-shark-984693.hostingersite.com/api"
EMAIL="dmasotti+test1@gmail.com"
PASSWORD="firstsecret"

echo "=== Testing Legacy Book Creation Fix ==="
echo ""

# Login
echo "1. Logging in..."
LOGIN_RESP=$(curl -sS -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -d "{\"email\":\"$EMAIL\",\"password\":\"$PASSWORD\"}")

TOKEN=$(echo "$LOGIN_RESP" | jq -r '.token // empty')
if [ -z "$TOKEN" ]; then
  echo "❌ Login failed"
  echo "$LOGIN_RESP"
  exit 1
fi
echo "✅ Login successful"
echo ""

# Get existing libraries
echo "2. Getting libraries..."
LIBS=$(curl -sS -H "Authorization: Bearer $TOKEN" "$API_URL/libraries")
LIB_ID=$(echo "$LIBS" | jq -r '.[0].id // empty')
CALIBRE_LIBRARY_ID=$(echo "$LIBS" | jq -r '.[0].calibre_library_uuid // empty')

if [ -z "$LIB_ID" ]; then
  echo "❌ No libraries found"
  exit 1
fi
echo "✅ Using library ID: $LIB_ID"
echo ""

# Test legacy book creation
echo "3. Creating book via legacy endpoint /api/sync/books..."
TIMESTAMP=$(date +%s)
BOOK_ID=$((RANDOM % 9000 + 1000))
LEGACY_PAYLOAD=$(cat <<EOF
{
  "device_uuid": "test-device-$TIMESTAMP",
  "library_id": $LIB_ID,
  "library_name": "test",
  "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
  "books": [
    {
      "local_book_id": $BOOK_ID,
      "title": "Test Legacy Book $TIMESTAMP",
      "author": "Test Author"
    }
  ]
}
EOF
)

echo "Payload:"
echo "$LEGACY_PAYLOAD" | jq '.'
echo ""

LEGACY_RESP=$(curl -sS -X POST "$API_URL/sync/books" \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "$LEGACY_PAYLOAD")

echo "Response:"
echo "$LEGACY_RESP" | jq '.'
echo ""

# Check for errors
if echo "$LEGACY_RESP" | jq -e '.results[0].error' >/dev/null 2>&1; then
  ERROR=$(echo "$LEGACY_RESP" | jq -r '.results[0].error')
  if [ "$ERROR" == "id is required in item" ]; then
    echo "❌ FAILED: 'id is required in item' error still present"
    echo "   The fix was not deployed correctly!"
    exit 1
  else
    echo "⚠️  Got different error: $ERROR"
    exit 1
  fi
fi

# Check for success
STATUS=$(echo "$LEGACY_RESP" | jq -r '.results[0].status // empty')
if [ "$STATUS" == "created" ] || [ "$STATUS" == "ok" ] || [ "$STATUS" == "merged" ] || [ "$STATUS" == "applied" ]; then
  echo "✅ SUCCESS: Book created/applied via legacy endpoint (status: $STATUS)!"
  
  # Verify id field is set correctly
  BOOK_ID=$(echo "$LEGACY_RESP" | jq -r '.results[0].server_item.id // empty')
  if [ -n "$BOOK_ID" ] && [ "$BOOK_ID" != "null" ]; then
    echo "   ✅ Book ID set correctly: $BOOK_ID"
    echo "   Fix is working correctly!"
    exit 0
  else
    echo "   ❌ Book ID is missing or null!"
    exit 1
  fi
else
  echo "⚠️  Unexpected status: $STATUS"
  exit 1
fi
