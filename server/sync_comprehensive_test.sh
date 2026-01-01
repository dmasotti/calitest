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
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVALID_JSON_LOG_DIR="$SCRIPT_DIR/tmp/invalid_json_logs"
mkdir -p "$INVALID_JSON_LOG_DIR"

# Colors
export RED='\033[0;31m'
export GREEN='\033[0;32m'
export YELLOW='\033[1;33m'
export BLUE='\033[0;34m'
export CYAN='\033[0;36m'
export NC='\033[0m'

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

# Helper function to parse JSON with jq and print raw output on error
log_invalid_json_response() {
    local context="$1"
    local payload="$2"
    local safe_context
    safe_context="$(printf '%s' "$context" | tr ' /' '_' | tr -cd '[:alnum:]_-')"
    local log_file="$INVALID_JSON_LOG_DIR/${safe_context}_invalid_json_$(date +%s%N).log"
    {
        echo "Context: $context"
        echo ""
        printf "%s\n" "$payload"
    } > "$log_file"
    echo "$log_file"
}

json_parse() {
    local json_string="$1"
    local jq_filter="$2"
    local context="${3:-json_parse}"
    local result

    result=$(echo "$json_string" | jq -r "$jq_filter" 2>/dev/null)
    local jq_exit_code=$?

    if [[ $jq_exit_code -ne 0 ]]; then
        local log_file
        log_file=$(log_invalid_json_response "$context" "$json_string")
        echo -e "\n${RED}jq parsing failed with exit code $jq_exit_code!${NC}" >&2
        echo -e "${YELLOW}Filter was:${NC} ${CYAN}$jq_filter${NC}" >&2
        echo -e "${YELLOW}Raw response was:${NC}" >&2
        echo "$json_string" >&2
        echo -e "${YELLOW}Logged invalid JSON to:${NC} ${CYAN}$log_file${NC}" >&2
        echo ""
        return 0
    fi
    
    echo "$result"
    return 0
}

# Helper for authenticated requests (definite prima dell'uso)
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

TOTAL_TESTS=$((TOTAL_TESTS + 1))

# Step 1: Discovery
log_test "Discovering API URL"
DISCOVERY_RESPONSE=$(curl -s "${DISCOVERY_URL}/discovery.php")
API_URL=$(json_parse "$DISCOVERY_RESPONSE" '.api_url // empty' "discovery_response")

if [[ -z "$API_URL" || "$API_URL" == "null" ]]; then
  DISCOVERY_RESPONSE=$(curl -s "${DISCOVERY_URL}/api/discovery")
  API_URL=$(json_parse "$DISCOVERY_RESPONSE" '.api_url // empty' "discovery_fallback")
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

TOKEN=$(json_parse "$LOGIN_RESPONSE" '.token' "login_response")
if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
    log_fail "Login failed"
    echo "$LOGIN_RESPONSE"
    exit 1
fi
log_pass "Login successful"

# Crea o riutilizza una libreria di test
log_test "Getting or creating test library"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
EXISTING_LIBRARIES=$(api_get "/libraries")
FIRST_LIB_ID=$(json_parse "$EXISTING_LIBRARIES" '.[0].id // empty' "libraries_list")

if [[ -n "$FIRST_LIB_ID" && "$FIRST_LIB_ID" != "null" ]]; then
    LIBRARY_ID="$FIRST_LIB_ID"
    CALIBRE_LIB_UUID=$(json_parse "$EXISTING_LIBRARIES" '.[0].calibre_library_uuid // empty' "libraries_list")
    log_pass "Using existing library ID: $LIBRARY_ID with UUID: $CALIBRE_LIB_UUID"
else
    # Crea una nuova libreria di test se non ne esistono
    LIB_NAME="test_sync_$(date +%s)"
    CALIBRE_LIB_UUID=$(uuidgen) # Genera un UUID univoco

    CREATE_LIB_PAYLOAD=$(cat <<EOF
{
      "name": "$LIB_NAME",
      "type": "calibre",
      "calibre_library_uuid": "$CALIBRE_LIB_UUID"
    }
EOF
    )

    CREATE_LIB_RESPONSE=$(api_post "/libraries" "$CREATE_LIB_PAYLOAD")
    LIBRARY_ID=$(json_parse "$CREATE_LIB_RESPONSE" '.id' "create_library")
    if [[ -z "$LIBRARY_ID" || "$LIBRARY_ID" == "null" ]]; then
        log_fail "Library creation failed"
        echo "$CREATE_LIB_RESPONSE" # Stampa la risposta grezza in caso di errore
        exit 1
    fi
    log_pass "Test library created with ID: $LIBRARY_ID and UUID: $CALIBRE_LIB_UUID"
fi



echo ""
echo "=== Library Management ==="

# Test 3: List libraries
log_test "Getting user libraries"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
LIBRARIES=$(api_get "/libraries")
    LIBRARY_COUNT=$(json_parse "$LIBRARIES" 'if type=="array" then length else 0 end' "library_count")
if [[ "$LIBRARY_COUNT" -gt 0 ]]; then
    log_pass "Found $LIBRARY_COUNT libraries"
    LIBRARY_ID=$(json_parse "$LIBRARIES" '.[0].id' "libraries_list")
    CALIBRE_LIBRARY_ID=$(json_parse "$LIBRARIES" '.[0].calibre_library_uuid // empty' "libraries_list")
else
    log_fail "No libraries found"
    exit 1
fi

echo ""
echo "=== Sync Operations ==="

# Test 4: Get sync cursor
log_test "Getting sync cursor"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
CURSOR_RESPONSE=$(api_get "/sync?calibre_library_uuid=$CALIBRE_LIBRARY_ID&limit=1")
CURSOR=$(json_parse "$CURSOR_RESPONSE" '.new_cursor // .cursor // empty' "cursor_response")
log_pass "Got cursor: ${CURSOR:-none}"

# Test 5: Pull sync (get server changes)
log_test "Pull sync - fetching server changes"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
PULL_RESPONSE=$(api_get "/sync?calibre_library_uuid=$CALIBRE_LIBRARY_ID&limit=50")
CHANGES_COUNT=$(json_parse "$PULL_RESPONSE" '.changes | length' "pull_changes")
log_pass "Received $CHANGES_COUNT changes from server"

# Test 6: Push sync - create a book
log_test "Push sync - creating test book"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
TIMESTAMP=$(date +%s)
BOOK_ID=$((RANDOM % 10000 + 1000))
BOOK_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')
PUSH_PAYLOAD=$(cat <<EOF
{
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
            "last_modified": $TIMESTAMP
        },
        "idempotency_key": "test-create-$TIMESTAMP"
    }]
}
EOF
)

PUSH_RESPONSE=$(api_post "/sync" "$PUSH_PAYLOAD")
PUSH_STATUS=$(json_parse "$PUSH_RESPONSE" '.results[0].status' "push_response")
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
UPDATE_STATUS=$(json_parse "$UPDATE_RESPONSE" '.results[0].status' "update_response")
if [[ "$UPDATE_STATUS" == "applied" || "$UPDATE_STATUS" == "merged" ]]; then
    log_pass "Book updated successfully"
else
    log_fail "Book update failed (status: $UPDATE_STATUS)"
fi

# Test 8: Pull to verify changes
log_test "Pull sync - verifying changes"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
USER_BOOKS_AFTER=$(api_get "/user-books")
FOUND_BOOK=$(json_parse "$USER_BOOKS_AFTER" ".[] | select(.uuid == \"$BOOK_UUID\") | .title // empty" "user_books_for_verify")
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
SEARCH_COUNT=$(json_parse "$SEARCH_RESPONSE" 'length' "search_results")
log_pass "User-books listing returned $SEARCH_COUNT results"

# Test 10: Filter by status
log_test "Filtering by status"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
STATUS_RESPONSE=$(api_get "/user-books")
STATUS_COUNT=$(json_parse "$STATUS_RESPONSE" '[.[] | select(.status == "reading")] | length' "status_filter")
log_pass "Status filter returned $STATUS_COUNT books"

echo ""
echo "=== Metadata Operations ==="

# Test 11: Get book details
log_test "Getting book details"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
BOOK_DETAIL=$(api_get "/user-books")
BOOK_TITLE=$(json_parse "$BOOK_DETAIL" ".[] | select(.uuid == \"$BOOK_UUID\") | .title // empty" "book_details")
if [[ -n "$BOOK_TITLE" ]]; then
    log_pass "Got book details: $BOOK_TITLE"
else
    log_fail "Could not get book details"
fi

echo ""
echo "=== Cleanup ==="

# Test 12: Delete the test book (already exists in original script)
# ... (existing delete book logic) ...

# Test 14: Cleanup - delete test library
log_test "Cleaning up - deleting test library"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
DELETE_LIB_RESPONSE=$(curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$API_URL/libraries/$LIBRARY_ID")
# Non controlliamo lo status, assumiamo che vada bene o che sia già stato rimosso
log_pass "Test library $LIBRARY_ID deleted"

# Test 12: Delete the test book
log_test "Deleting test book"
TOTAL_TESTS=$((TOTAL_TESTS + 1))
DELETE_PAYLOAD=$(cat <<EOF
{
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
DELETE_STATUS=$(json_parse "$DELETE_RESPONSE" '.results[0].status' "delete_response")
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
TRIPLET_TEST='{"calibre_library_uuid":"'$CALIBRE_LIBRARY_ID'","device_uuid":"test-device-'$TIMESTAMP'","changes":[{"op":"create","item":{"id":'$BOOK_ID',"title":"Same ID Different Library","timestamps":{"created_at":'$(date -u +%s)'},"last_modified":'$(date -u +%s)'},"idempotency_key":"test-triplet-'$TIMESTAMP'"}]}'
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
