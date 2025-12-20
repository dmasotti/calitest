#!/usr/bin/env bash
# tests/opds/opds_comprehensive_test.sh
# Comprehensive OPDS test suite covering all endpoints
# Usage:
#   HOST=https://example.com USER=user@example.com PASS=secret ./tests/opds/opds_comprehensive_test.sh

set -euo pipefail

# Configuration
HOST=${HOST:-http://127.0.0.1:8000}
USER=${USER:-}
PASS=${PASS:-}
APP_PASS=${APP_PASS:-}
TMPDIR=$(mktemp -d)
VERBOSE=${VERBOSE:-0}

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# Counters
TOTAL_TESTS=0
PASSED_TESTS=0
FAILED_TESTS=0

# Cleanup on exit
trap "rm -rf $TMPDIR" EXIT

if [[ -z "$USER" || -z "$PASS" ]]; then
  echo -e "${RED}ERROR: please set USER and PASS environment variables${NC}"
  exit 2
fi

CRED="$USER:$PASS"
if [[ -n "$APP_PASS" ]]; then
  CRED="$USER:$APP_PASS"
  echo -e "${YELLOW}Note: testing with app-password${NC}"
fi

echo "=========================================="
echo "  OPDS Comprehensive Test Suite"
echo "=========================================="
echo "Host: $HOST"
echo "User: $USER"
echo ""

# Test helper functions
test_endpoint() {
    local test_name="$1"
    local endpoint="$2"
    local expected_code="${3:-200}"
    local accept_header="${4:-application/atom+xml}"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    local output_file="$TMPDIR/test_${TOTAL_TESTS}.xml"
    local status_file="$TMPDIR/test_${TOTAL_TESTS}.status"
    
    if [[ $VERBOSE -eq 1 ]]; then
        echo -n "Testing: $test_name ... "
    fi
    
    HTTP_CODE=$(curl -s -u "$CRED" -H "Accept: $accept_header" \
        "$HOST$endpoint" -o "$output_file" -w "%{http_code}")
    
    if [[ "$HTTP_CODE" == "$expected_code" ]]; then
        PASSED_TESTS=$((PASSED_TESTS + 1))
        echo -e "${GREEN}✓${NC} $test_name (HTTP $HTTP_CODE)"
        return 0
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo -e "${RED}✗${NC} $test_name (Expected $expected_code, got $HTTP_CODE)"
        if [[ $VERBOSE -eq 1 ]]; then
            echo "Response body:"
            head -20 "$output_file"
        fi
        return 1
    fi
}

test_xml_contains() {
    local test_name="$1"
    local file="$2"
    local pattern="$3"
    
    TOTAL_TESTS=$((TOTAL_TESTS + 1))
    
    if grep -q "$pattern" "$file" 2>/dev/null; then
        PASSED_TESTS=$((PASSED_TESTS + 1))
        echo -e "${GREEN}✓${NC} $test_name"
        return 0
    else
        FAILED_TESTS=$((FAILED_TESTS + 1))
        echo -e "${RED}✗${NC} $test_name (Pattern not found: $pattern)"
        return 1
    fi
}

echo "=== Basic OPDS Endpoints ==="

# Test 1: Root feed
test_endpoint "Root navigation feed" "/opds" 200

# Test 2: All books
test_endpoint "All books listing" "/opds/all?page=1" 200

# Test 3: Search
test_endpoint "Search endpoint" "/opds/search?q=test" 200

# Test 4: Recent additions
test_endpoint "Recent additions" "/opds/recent?page=1" 200

echo ""
echo "=== Navigation Feeds ==="

# Test 5: Authors list
test_endpoint "Authors navigation" "/opds/authors" 200

# Test 6: Series list
test_endpoint "Series navigation" "/opds/series" 200

# Test 7: Tags list
test_endpoint "Tags navigation" "/opds/tags" 200

echo ""
echo "=== Content Validation ==="

# Validate root feed structure
ROOT_FILE="$TMPDIR/test_1.xml"
test_xml_contains "Root has feed element" "$ROOT_FILE" "<feed"
test_xml_contains "Root has title" "$ROOT_FILE" "<title>"
test_xml_contains "Root has entries" "$ROOT_FILE" "<entry>"
test_xml_contains "Root has search link" "$ROOT_FILE" "search"

# Validate all books feed
ALL_FILE="$TMPDIR/test_2.xml"
test_xml_contains "All books has feed element" "$ALL_FILE" "<feed"
test_xml_contains "All books has pagination" "$ALL_FILE" "rel=\"next\""

# Validate search results
SEARCH_FILE="$TMPDIR/test_3.xml"
test_xml_contains "Search has OpenSearch namespace" "$SEARCH_FILE" "opensearch:"

echo ""
echo "=== Authentication & Security ==="

# Test 8: Unauthenticated access (should fail)
TOTAL_TESTS=$((TOTAL_TESTS + 1))
HTTP_CODE=$(curl -s "$HOST/opds/all" -o /dev/null -w "%{http_code}")
if [[ "$HTTP_CODE" == "401" ]]; then
    PASSED_TESTS=$((PASSED_TESTS + 1))
    echo -e "${GREEN}✓${NC} Unauthenticated access rejected (HTTP 401)"
else
    FAILED_TESTS=$((FAILED_TESTS + 1))
    echo -e "${RED}✗${NC} Unauthenticated access should return 401, got $HTTP_CODE"
fi

# Test 9: Wrong credentials (should fail)
TOTAL_TESTS=$((TOTAL_TESTS + 1))
HTTP_CODE=$(curl -s -u "wrong:credentials" "$HOST/opds/all" -o /dev/null -w "%{http_code}")
if [[ "$HTTP_CODE" == "401" ]]; then
    PASSED_TESTS=$((PASSED_TESTS + 1))
    echo -e "${GREEN}✓${NC} Wrong credentials rejected (HTTP 401)"
else
    FAILED_TESTS=$((FAILED_TESTS + 1))
    echo -e "${RED}✗${NC} Wrong credentials should return 401, got $HTTP_CODE"
fi

echo ""
echo "=== Pagination ==="

# Test 10: Page 1
test_endpoint "All books page 1" "/opds/all?page=1" 200

# Test 11: Page 2
test_endpoint "All books page 2" "/opds/all?page=2" 200

echo ""
echo "=== Search Functionality ==="

# Test 12: Search with query
test_endpoint "Search with query" "/opds/search?q=Foundation" 200

# Test 13: Empty search
test_endpoint "Empty search query" "/opds/search?q=" 200

# Test 14: Search pagination
test_endpoint "Search with pagination" "/opds/search?q=book&page=1" 200

echo ""
echo "=== OPDS Metadata ==="

# Check if all books feed has proper OPDS elements
ALL_FILE="$TMPDIR/test_10.xml"
if [[ -f "$ALL_FILE" ]]; then
    test_xml_contains "Books have IDs" "$ALL_FILE" "<id>urn:caliweb:book:"
    test_xml_contains "Books have titles" "$ALL_FILE" "<title>"
    test_xml_contains "Books have authors" "$ALL_FILE" "<author>"
    test_xml_contains "Books have download links" "$ALL_FILE" "acquisition/open-access"
    test_xml_contains "Books have cover links" "$ALL_FILE" "opds-spec.org/image"
fi

echo ""
echo "=========================================="
echo "  Test Summary"
echo "=========================================="
echo "Total tests: $TOTAL_TESTS"
echo -e "${GREEN}Passed: $PASSED_TESTS${NC}"
if [[ $FAILED_TESTS -gt 0 ]]; then
    echo -e "${RED}Failed: $FAILED_TESTS${NC}"
    echo ""
    echo "Some tests failed. Check output above for details."
    exit 1
else
    echo -e "${GREEN}All tests passed! ✓${NC}"
    exit 0
fi
