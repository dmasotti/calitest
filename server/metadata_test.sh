#!/usr/bin/env bash
# tests/server/metadata_test.sh
# Test per la sincronizzazione dei metadati Calibre-like

set -euo pipefail

# Load env if exists
if [[ -f "$(dirname "$0")/.env" ]]; then
    source "$(dirname "$0")/.env"
fi

# Configuration
DISCOVERY_URL=${DISCOVERY_URL:-http://127.0.0.1:8000}
TEST_USER_EMAIL=${TEST_USER_EMAIL:-}
TEST_USER_PASSWORD=${TEST_USER_PASSWORD:-}
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TESTS_TMP_DIR="$SCRIPT_DIR/tmp"
mkdir -p "$TESTS_TMP_DIR" # Ensure the directory exists
TMPDIR=$(mktemp -d "$TESTS_TMP_DIR/metadata_test_XXXXXX")
INVALID_JSON_LOG_DIR="$TESTS_TMP_DIR/invalid_json_logs"
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
echo "  Metadata Comprehensive Test Suite"
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

# Helper functions
# Checks if a string is valid JSON. If not, logs it and exits the script with an error.
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

parse_json() {
    local json_string="$1"
    local context="${2:-api_response}"

    # Use jq to test if it's valid JSON
    if echo "$json_string" | jq -e . > /dev/null 2>&1; then
        echo "$json_string" | jq '.'
    else
        local log_file
        log_file=$(log_invalid_json_response "$context" "$json_string")
        echo -e "${RED}ERROR: Invalid JSON received from API.${NC}" >&2
        echo "Raw API Response (Invalid JSON) logged to $log_file" >&2
        exit 1
    fi
}

# Helper for authenticated requests
api_get() {
    curl -s -H "Authorization: Bearer $TOKEN" "$API_URL$1"
}

api_post() {
    local endpoint="$1"
    local payload="$2"
    local payload_file="$TMPDIR/payload_$(date +%s%N).json" # Crea un file temporaneo univoco

    echo "$payload" | tr -d '\n' > "$payload_file" # <-- MODIFICATO

    echo "DEBUG: API POST to $API_URL$endpoint using payload from file $payload_file" >&2
    echo "DEBUG: Payload content (no newlines):" >&2 # Etichetta aggiornata
    cat "$payload_file" >&2

    curl -s -X POST -H "Authorization: Bearer $TOKEN" \
        -H "Content-Type: application/json" \
        "$API_URL$endpoint" --data-binary "@$payload_file" # Passa il file

    rm "$payload_file" # Pulisci il file temporaneo
}

# Step 1: Discovery
log_test "Discovering API URL"
API_URL_RAW=$(curl -s "${DISCOVERY_URL}/api/discovery")
API_URL=$(parse_json "$API_URL_RAW" "discovery" | jq -r '.api_url // empty' 2>/dev/null || true)
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

TOKEN_PARSED=$(parse_json "$LOGIN_RESPONSE" "login")
TOKEN=$(echo "$TOKEN_PARSED" | jq -r '.token')
if [[ -z "$TOKEN" || "$TOKEN" == "null" ]]; then
    log_fail "Login failed"
    echo "$LOGIN_RESPONSE"
    exit 1
fi
log_pass "Login successful"

# Step 3: Get or create library
log_test "Getting or creating test library"
EXISTING_LIBRARIES=$(api_get "/libraries")
EXISTING_LIBRARIES_PARSED=$(parse_json "$EXISTING_LIBRARIES" "libraries")
FIRST_LIB_ID=$(echo "$EXISTING_LIBRARIES_PARSED" | jq -r '.[0].id // empty')

if [[ -n "$FIRST_LIB_ID" && "$FIRST_LIB_ID" != "null" ]]; then
    LIBRARY_ID="$FIRST_LIB_ID"
    CALIBRE_LIB_UUID=$(echo "$EXISTING_LIBRARIES_PARSED" | jq -r '.[0].calibre_library_uuid // empty')
    log_pass "Using existing library ID: $LIBRARY_ID with UUID: $CALIBRE_LIB_UUID"
else
    # Crea una nuova libreria di test se non ne esistono
    log_test "Creating test library"
    LIB_NAME="metadata_test_lib_$(date +%s)"
    CALIBRE_LIB_UUID=$(uuidgen)
    CREATE_LIB_PAYLOAD=$(cat <<EOF
{
      "name": "$LIB_NAME",
      "type": "calibre",
      "calibre_library_uuid": "$CALIBRE_LIB_UUID"
    }
EOF
    )
    CREATE_LIB_RESPONSE=$(api_post "/libraries" "$CREATE_LIB_PAYLOAD")
    CREATE_LIB_RESPONSE_PARSED=$(parse_json "$CREATE_LIB_RESPONSE" "create_library")
LIBRARY_ID=$(echo "$CREATE_LIB_RESPONSE_PARSED" | jq -r '.id')
    if [[ -z "$LIBRARY_ID" || "$LIBRARY_ID" == "null" ]]; then
        log_fail "Library creation failed"
        echo "$CREATE_LIB_RESPONSE"
        exit 1
    fi
    log_pass "Test library created with ID: $LIBRARY_ID"
fi

# Step 4: Create book with all metadata
log_test "Creating book with all metadata"
BOOK_ID=$((RANDOM % 10000 + 5000))
BOOK_UUID=$(uuidgen | tr '[:upper:]' '[:lower:]')

PUSH_PAYLOAD=$(cat <<EOF
{
    "library_id": $LIBRARY_ID,
    "calibre_library_uuid": "$CALIBRE_LIB_UUID",
    "changes": [{
        "op": "create",
        "item": {
            "id": $BOOK_ID,
            "uuid": "$BOOK_UUID",
            "title": "Metadata Test Book",
            "sort": "Metadata Test Book, The",
            "authors": [{"name": "Test Author", "sort": "Author, Test", "link": "http://example.com/test-author"}],
            "series": {"name": "Test Series", "index": 1.0},
            "identifiers": [
                {"type": "google", "value": "xyz123"},
                {"type": "amazon", "value": "B0123456"}
            ],
            "publisher": "Test Publisher",
            "tags": [{"name": "Metadata"}, {"name": "Testing"}],
            "languages": ["ita", "eng"],
            "rating": 8,
            "last_modified": $(date +%s)
        },
        "idempotency_key": "metadata-test-create-$(date +%s)"
    }]
}
EOF
)
PUSH_RESPONSE_RAW=$(api_post "/sync" "$PUSH_PAYLOAD")
echo "DEBUG: Raw PUSH_RESPONSE_RAW:" >&2
echo "$PUSH_RESPONSE_RAW" >&2
PUSH_RESPONSE=$(parse_json "$PUSH_RESPONSE_RAW" "push_book")
PUSH_STATUS=$(echo "$PUSH_RESPONSE" | jq -r '.results[0].status')
if [[ "$PUSH_STATUS" != "applied" ]]; then
    log_fail "Book creation failed (status: $PUSH_STATUS)"
    echo "$PUSH_RESPONSE" # Already parsed by parse_json
    exit 1
fi
log_pass "Book with all metadata created successfully"

# Step 5: Verify all metadata
log_test "Verifying all metadata fields"
BOOK_DETAIL_RAW=$(api_get "/user-books")
echo "DEBUG: Raw BOOK_DETAIL_RAW response from /user-books:" >&2
echo "$BOOK_DETAIL_RAW" >&2
BOOK_DETAIL=$(parse_json "$BOOK_DETAIL_RAW" "user_books")

CREATED_BOOK=$(echo "$BOOK_DETAIL" | jq -r --arg uuid "$BOOK_UUID" '(.data // .)[] | select(.uuid == $uuid)')
echo "DEBUG: CREATED_BOOK extracted:" >&2
echo "$CREATED_BOOK" >&2

# Authors
AUTHOR_SORT=$(echo "$CREATED_BOOK" | jq -r '.authors[0].sort')
AUTHOR_LINK=$(echo "$CREATED_BOOK" | jq -r '.authors[0].link')
if [[ "$AUTHOR_SORT" == "Author, Test" && "$AUTHOR_LINK" == "http://example.com/test-author" ]]; then log_pass "Author (sort, link) OK"; else log_fail "Author (sort, link) FAILED"; fi

# Series
SERIES_NAME=$(echo "$CREATED_BOOK" | jq -r '.series[0].name')
SERIES_INDEX=$(echo "$CREATED_BOOK" | jq -r '.series[0].pivot.series_index')
if [[ "$SERIES_NAME" == "Test Series" && "$SERIES_INDEX" == "1.0" ]]; then log_pass "Series (name, index) OK"; else log_fail "Series (name, index) FAILED"; fi

# Identifiers
IDENTIFIERS_COUNT=$(echo "$CREATED_BOOK" | jq -r '.identifiers | length')
if [[ "$IDENTIFIERS_COUNT" -eq 2 ]]; then log_pass "Identifiers count OK"; else log_fail "Identifiers count FAILED"; fi

# Publisher
PUBLISHER=$(echo "$CREATED_BOOK" | jq -r '.publisher')
if [[ "$PUBLISHER" == "Test Publisher" ]]; then log_pass "Publisher OK"; else log_fail "Publisher FAILED"; fi

# Languages
LANG_COUNT=$(echo "$CREATED_BOOK" | jq -r '.languages | length')
if [[ "$LANG_COUNT" -eq 2 ]]; then log_pass "Languages count OK"; else log_fail "Languages count FAILED"; fi

# Rating
RATING=$(echo "$CREATED_BOOK" | jq -r '.rating')
if [[ "$RATING" == "4" ]]; then log_pass "Rating OK"; else log_fail "Rating FAILED (got $RATING)"; fi # Rating is 0-5 in server, so 8 becomes 4

# Cleanup
log_test "Cleaning up"
# Delete book
api_post "/sync" "{\"library_id\":$LIBRARY_ID,\"calibre_library_uuid\":\"$CALIBRE_LIB_UUID\",\"changes\":[{\"op\":\"delete\",\"item\":{\"id\":$BOOK_ID,\"uuid\":\"$BOOK_UUID\"}}]}" > /dev/null
# Delete library
curl -s -X DELETE -H "Authorization: Bearer $TOKEN" "$API_URL/libraries/$LIBRARY_ID" > /dev/null
log_pass "Cleanup complete"

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
