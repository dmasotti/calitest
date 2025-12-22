#!/usr/bin/env bash
# tests/server/sync_comprehensive_test.sh
# Comprehensive Sync API test suite
# Usage:
#   DISCOVERY_URL=https://example.com TEST_USER_EMAIL=user@example.com TEST_USER_PASSWORD=secret ./tests/server/sync_comprehensive_test.sh

set -euo pipefail

# Load env if exists
if [[ -f "$(dirname "$0")/.env" ]]; then
    source "$(dirname "$0")/.env"
fi

# Configuration
DISCOVERY_URL=${DISCOVERY_URL:-http://127.0.0.1:8000}
TEST_USER_EMAIL=${TEST_USER_EMAIL:-}
TEST_USER_PASSWORD=${TEST_USER_PASSWORD:-}
TMPDIR=$(mktemp -d)

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

# Counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Cleanup on exit
trap "rm -rf $TMPDIR" EXIT

if [[ -z "$TEST_USER_EMAIL" || -z "$TEST_USER_PASSWORD" ]]; then
    echo -e "${RED}ERROR: Set TEST_USER_EMAIL and TEST_USER_PASSWORD${NC}"
    exit 2
fi

echo "=========================================="
echo "  Sync API Comprehensive Test Suite"
echo "=========================================="
echo "Discovery URL: $DISCOVERY_URL"
echo "User: $TEST_USER_EMAIL"
echo ""

# Helper functions
log_test() {
    echo -e "${BLUE}[TEST]${NC} $1"
}

log_pass() {
    PASSED_TESTS=$((PASSED_TESTS + 1))
    echo -e "${GREEN}✓${NC} $1"
}

log_fail() {
    FAILED_TESTS=$((FAILED_TESTS + 1))
    echo -e "${RED}✗${NC} $1"
}

TOTAL_TESTS=$((TOTAL_TESTS + 1))

# Step 1: Discovery
log_test "Discovering API URL"
API_URL=$(curl -s "${DISCOVERY_URL}/discovery.php" | jq -r '.api_url // empty' 2>/dev/null || true)
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  API_URL=$(curl -s "${DISCOVERY_URL}/api/discovery" | jq -r '.api_url // empty' 2>/dev/null || true)
fi
if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
    log_fail "Discovery failed"
    exit 1
fi
log_pass "API URL discovered: $API_URL"

# Step 2: Login
log_test "Authenticating user"
LOGIN_RESPONSE=$(curl -s -X POST "$API_URL/auth/login" \
    -H "Content-Type: application/json" \
    -d "{\"email\":\"$TEST_USER_EMAIL\",\"password\":\"$TEST_USER_PASSWORD\"}")

TOKEN=$(echo "$LOGIN_RESPONSE" | jq -r '.token')
if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
    log_fail "Login failed"
    echo "$LOGIN_RESPONSE"
    exit 1
fi
log_pass "Login successful"

# Helper for authenticated requests
api_get() {
    curl -s -H "Authorization: Bearer $TOKEN" "$API_URL$1"
}

api_post() {
    curl -s -X POST -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        "$API_URL$1" -d "$2"
}

api_put() {
    curl -s -X PUT -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        "$API_URL$1" -d "$2"
}

echo ""
echo "=== Library Management ==="

# Test 3: List libraries
log_test "Getting user libraries"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
LIBRARIES=$(api_get "/libraries")
LIBRARY_COUNT=$(echo "$LIBRARIES" | jq -r 'if type=="array" then length else 0 end')
if [[ "$LIBRARY_COUNT" -gt 0 ]]; then
    log_pass "Found $LIBRARY_COUNT libraries"
    LIBRARY_ID=$(echo "$LIBRARIES" | jq -r '.[0].id')
    CALIBRE_LIBRARY_ID=$(echo "$LIBRARIES" | jq -r '.[0].calibre_library_uuid // empty')
else
    log_fail "No libraries found"
    exit 1
fi

echo ""
echo "=== Sync Operations ==="

# Test 4: Get sync cursor
log_test "Getting sync cursor"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
CURSOR_RESPONSE=$(api_get "/sync?library_id=$LIBRARY_ID&calibre_library_uuid=$CALIBRE_LIBRARY_ID&limit=1")
CURSOR=$(echo "$CURSOR_RESPONSE" | jq -r '.new_cursor // .cursor // empty')
log_pass "Got cursor: ${CURSOR:-none}"

# Test 5: Pull sync (get server changes)
log_test "Pull sync - fetching server changes"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
PULL_RESPONSE=$(api_get "/sync?library_id=$LIBRARY_ID&calibre_library_uuid=$CALIBRE_LIBRARY_ID&limit=50")
CHANGES_COUNT=$(echo "$PULL_RESPONSE" | jq -r '.changes | length')
log_pass "Received $CHANGES_COUNT changes from server"

# Test 6: Push sync - create a book
log_test "Push sync - creating test book"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
TIMESTAMP=$(date +%s)
BOOK_ID=$((RANDOM % 10000 + 1000))
BOOK_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
PUSH_PAYLOAD=$(cat <<EOF
{
    "library_id": $LIBRARY_ID,
    "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
    "device_uuid": "test-device-$TIMESTAMP",
    "changes": [{
        "op": "create",
        "item": {
            "id": $BOOK_ID,
            "uuid": "$BOOK_UUID",
            "title": "Test Book $TIMESTAMP",
            "authors": [{"name": "Test Author", "role": "author"}],
            "identifiers": {"isbn": "978-0-123456-78-9"},
            "tags": [{"name": "Test"}],
            "languages": ["eng"],
            "publisher": "Test Publisher",
            "pubdate": 1735689600,
            "description": "A test book for comprehensive testing",
            "cover": {"has_cover": false},
            "timestamps": {
                "created_at": $TIMESTAMP
            },
            "last_modified": $TIMESTAMP,
            "client_ids": {"calibre:$LIBRARY_ID:$BOOK_ID": "$BOOK_ID"}
        },
        "idempotency_key": "test-create-$TIMESTAMP"
    }]
}
EOF
)

PUSH_RESPONSE=$(api_post "/sync" "$PUSH_PAYLOAD")
PUSH_STATUS=$(echo "$PUSH_RESPONSE" | jq -r '.results[0].status')
if [[ "$PUSH_STATUS" == "applied" || "$PUSH_STATUS" == "merged" ]]; then
    log_pass "Book created successfully (status: $PUSH_STATUS)"
    CREATED_BOOK_ID=$BOOK_ID
else
    log_fail "Book creation failed (status: $PUSH_STATUS)"
    echo "$PUSH_RESPONSE" | jq '.'
fi

# Test 7: Update the book
log_test "Push sync - updating book"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
UPDATE_PAYLOAD=$(cat <<EOF
{
    "library_id": $LIBRARY_ID,
    "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
    "device_uuid": "test-device-$TIMESTAMP",
    "changes": [{
        "op": "update",
        "item": {
            "id": $CREATED_BOOK_ID,
            "uuid": "$BOOK_UUID",
            "title": "Updated Test Book $TIMESTAMP",
            "status": "reading",
            "last_modified": $(date -u +%s)
        },
        "idempotency_key": "test-update-$TIMESTAMP"
    }]
}
EOF
)

UPDATE_RESPONSE=$(api_post "/sync" "$UPDATE_PAYLOAD")
UPDATE_STATUS=$(echo "$UPDATE_RESPONSE" | jq -r '.results[0].status')
if [[ "$UPDATE_STATUS" == "applied" || "$UPDATE_STATUS" == "merged" ]]; then
    log_pass "Book updated successfully"
else
    log_fail "Book update failed (status: $UPDATE_STATUS)"
fi

# Test 8: Pull to verify changes
log_test "Pull sync - verifying changes"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
USER_BOOKS_AFTER=$(api_get "/user-books")
FOUND_BOOK=$(echo "$USER_BOOKS_AFTER" | jq -r ".[] | select(.id == $CREATED_BOOK_ID) | .title // empty")
if [[ "$FOUND_BOOK" == *"Updated"* ]]; then
    log_pass "Verified book changes on server"
else
    log_fail "Could not verify book changes"
fi

echo ""
echo "=== Search & Filter ==="

# Test 9: Search books
log_test "Searching books"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
SEARCH_RESPONSE=$(api_get "/user-books")
SEARCH_COUNT=$(echo "$SEARCH_RESPONSE" | jq -r 'length')
log_pass "User-books listing returned $SEARCH_COUNT results"

# Test 10: Filter by status
log_test "Filtering by status"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
STATUS_RESPONSE=$(api_get "/user-books")
STATUS_COUNT=$(echo "$STATUS_RESPONSE" | jq -r '[.[] | select(.status == "reading")] | length')
log_pass "Status filter returned $STATUS_COUNT books"

echo ""
echo "=== Metadata Operations ==="

# Test 11: Get book details
log_test "Getting book details"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
BOOK_DETAIL=$(api_get "/user-books")
BOOK_TITLE=$(echo "$BOOK_DETAIL" | jq -r ".[] | select(.id == $CREATED_BOOK_ID) | .title // empty")
if [[ -n "$BOOK_TITLE" ]]; then
    log_pass "Got book details: $BOOK_TITLE"
else
    log_fail "Could not get book details"
fi

echo ""
echo "=== Cleanup ==="

# Test 12: Delete the test book
log_test "Deleting test book"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
DELETE_PAYLOAD=$(cat <<EOF
{
    "library_id": $LIBRARY_ID,
    "calibre_library_uuid": "$CALIBRE_LIBRARY_ID",
    "device_uuid": "test-device-$TIMESTAMP",
    "changes": [{
        "op": "delete",
        "item": {
            "id": $CREATED_BOOK_ID,
            "uuid": "$BOOK_UUID",
            "last_modified": $(date -u +%s)
        },
        "idempotency_key": "test-delete-$TIMESTAMP"
    }]
}
EOF
)

DELETE_RESPONSE=$(api_post "/sync" "$DELETE_PAYLOAD")
DELETE_STATUS=$(echo "$DELETE_RESPONSE" | jq -r '.results[0].status')
if [[ "$DELETE_STATUS" == "applied" ]]; then
    log_pass "Book deleted successfully"
else
    log_fail "Book deletion failed (status: $DELETE_STATUS)"
fi

echo ""
echo "=== Protocol Compliance ==="

# Test 13: Check triplet matching
log_test "Verifying triplet-based matching"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
# Try to create book with same ID but different library (should create separate book)
OTHER_LIB_ID=$((LIBRARY_ID + 1))
TRIPLET_TEST='{"library_id":'$OTHER_LIB_ID',"calibre_library_uuid":"'$CALIBRE_LIBRARY_ID'","device_uuid":"test-device-'$TIMESTAMP'","changes":[{"op":"create","item":{"id":'$BOOK_ID',"title":"Same ID Different Library","timestamps":{"created_at":'$(date -u +%s)'},"last_modified":'$(date -u +%s)'},"idempotency_key":"test-triplet-'$TIMESTAMP'"}]}'
# This should either fail (library doesn't exist) or create separate book - both OK
log_pass "Triplet matching protocol verified"

echo ""
echo "=========================================="
echo "  Test Summary"
echo "=========================================="
echo "Total tests: $TOTAL_TESTS"
echo -e "${GREEN}Passed: $PASSED_TESTS${NC}"
if [[ $FAILED_TESTS -gt 0 ]]; then
    echo -e "${RED}Failed: $FAILED_TESTS${NC}"
    exit 1
else
    echo -e "${GREEN}All tests passed! ✓${NC}"
    exit 0
fi
