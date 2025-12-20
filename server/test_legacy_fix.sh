#!/usr/bin/env bash
set -e

API_URL="https://coral-shark-984693.hostingersite.com/api"
EMAIL="dmasotti+test1@gmail.com"
PASSWORD="firstsecret"

echo "=== Testing Legacy Book Creation Fix ==="
echo ""

# Login
echo "1. Logging in..."
LOGIN_RESP=$(curl -sS -L -X POST "$API_URL/auth/login" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
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
LIBS=$(curl -sS -L -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" "$API_URL/libraries")
LIB_ID=$(echo "$LIBS" | jq -r '.[0].id // empty')

if [ -z "$LIB_ID" ]; then
  echo "❌ No libraries found"
  exit 1
fi
echo "✅ Using library ID: $LIB_ID"
echo ""

# Test legacy book creation
echo "3. Creating book via legacy endpoint /api/sync/books..."
TIMESTAMP=$(date +%s)
BOOK_ID=$((RANDOM % 9000 + 1000))  # ID tra 1000-9999
LEGACY_PAYLOAD=$(cat <<PAYLOAD
{
  "device_uuid": "test-device-$TIMESTAMP",
  "library_id": $LIB_ID,
  "library_name": "test",
  "books": [
    {
      "local_book_id": "$BOOK_ID",
      "title": "Test Legacy Book $TIMESTAMP",
      "author": "Test Author"
    }
  ]
}
PAYLOAD
)

echo "Payload:"
echo "$LEGACY_PAYLOAD" | jq '.'
echo ""

LEGACY_RESP=$(curl -sS -L -X POST "$API_URL/sync/books" \
  -H "Content-Type: application/json" \
  -H "Accept: application/json" \
  -H "Authorization: Bearer $TOKEN" \
  -d "$LEGACY_PAYLOAD")

echo "Response:"
echo "$LEGACY_RESP" | jq '.'
echo ""

# Check for the specific error
if echo "$LEGACY_RESP" | jq -e '.results[0].error' >/dev/null 2>&1; then
  ERROR=$(echo "$LEGACY_RESP" | jq -r '.results[0].error')
  if [ "$ERROR" == "id is required in item" ]; then
    echo "❌ FAILED: 'id is required in item' error still present"
    echo "   The fix was not deployed correctly!"
    exit 1
  else
    echo "⚠️  Got error: $ERROR"
    echo "   (This might be expected depending on the situation)"
  fi
fi

# Check for success
STATUS=$(echo "$LEGACY_RESP" | jq -r '.results[0].status // empty')
if [ "$STATUS" == "created" ] || [ "$STATUS" == "ok" ]; then
  echo "✅ SUCCESS: Book created via legacy endpoint!"
  echo "   Fix is working correctly!"
  exit 0
elif [ "$STATUS" == "error" ]; then
  ERROR=$(echo "$LEGACY_RESP" | jq -r '.results[0].error')
  if [ "$ERROR" == "id is required in item" ]; then
    echo "❌ FAILED: Original bug still present"
    exit 1
  else
    echo "✅ Fix deployed (original 'id required' error is gone)"
    echo "   New error: $ERROR"
  fi
else
  echo "Status: $STATUS"
fi
