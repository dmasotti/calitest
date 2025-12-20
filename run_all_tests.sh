#!/usr/bin/env bash
# tests/run_all_tests.sh
# Master test runner - executes all test suites
# Usage:
#   DISCOVERY_URL=https://example.com TEST_USER_EMAIL=user@example.com TEST_USER_PASSWORD=secret ./tests/run_all_tests.sh

set -euo pipefail

# Colors
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m'

# Load env if exists
ENV_FILE="$(dirname "$0")/server/.env"
if [[ -f "$ENV_FILE" ]]; then
    source "$ENV_FILE"
fi

# Configuration
DISCOVERY_URL=${DISCOVERY_URL:-}
TEST_USER_EMAIL=${TEST_USER_EMAIL:-}
TEST_USER_PASSWORD=${TEST_USER_PASSWORD:-}

if [[ -z "$DISCOVERY_URL" || -z "$TEST_USER_EMAIL" || -z "$TEST_USER_PASSWORD" ]]; then
    echo -e "${RED}ERROR: Required environment variables not set${NC}"
    echo "Please set:"
    echo "  DISCOVERY_URL"
    echo "  TEST_USER_EMAIL"
    echo "  TEST_USER_PASSWORD"
    echo ""
    echo "Or create tests/server/.env with these variables"
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
FAILED_SUITES=()

echo -e "${CYAN}"
echo "╔════════════════════════════════════════╗"
echo "║   CaliWeb Comprehensive Test Suite    ║"
echo "╚════════════════════════════════════════╝"
echo -e "${NC}"
echo "Discovery URL: $DISCOVERY_URL"
echo "Test User: $TEST_USER_EMAIL"
echo ""

run_test_suite() {
    local suite_name="$1"
    local test_script="$2"
    
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo -e "${BLUE}Running: $suite_name${NC}"
    echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
    echo ""
    
    if [[ ! -f "$test_script" ]]; then
        echo -e "${RED}✗ Test script not found: $test_script${NC}"
        FAILED_SUITES+=("$suite_name")
        return 1
    fi
    
    if bash "$test_script"; then
        echo ""
        echo -e "${GREEN}✓ $suite_name PASSED${NC}"
        return 0
    else
        echo ""
        echo -e "${RED}✗ $suite_name FAILED${NC}"
        FAILED_SUITES+=("$suite_name")
        return 1
    fi
}

# Export variables for child scripts
export DISCOVERY_URL
export TEST_USER_EMAIL
export TEST_USER_PASSWORD
export HOST="$DISCOVERY_URL"
export USER="$TEST_USER_EMAIL"
export PASS="$TEST_USER_PASSWORD"

# Run test suites
echo -e "${YELLOW}Starting test execution...${NC}"
echo ""

# 1. OPDS Comprehensive Tests
run_test_suite "OPDS Comprehensive" "$SCRIPT_DIR/opds/opds_comprehensive_test.sh" || true

echo ""

# 2. Sync API Comprehensive Tests
run_test_suite "Sync API Comprehensive" "$SCRIPT_DIR/server/sync_comprehensive_test.sh" || true

echo ""

# 3. Legacy Book Creation Test
run_test_suite "Legacy Book Creation" "$SCRIPT_DIR/server/test_legacy_book.sh" || true

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}           Test Execution Summary         ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

TOTAL_SUITES=3
PASSED_SUITES=$((TOTAL_SUITES - ${#FAILED_SUITES[@]}))

echo "Total test suites: $TOTAL_SUITES"
echo -e "${GREEN}Passed: $PASSED_SUITES${NC}"

if [[ ${#FAILED_SUITES[@]} -gt 0 ]]; then
    echo -e "${RED}Failed: ${#FAILED_SUITES[@]}${NC}"
    echo ""
    echo -e "${RED}Failed suites:${NC}"
    for suite in "${FAILED_SUITES[@]}"; do
        echo -e "  ${RED}✗${NC} $suite"
    done
    echo ""
    echo -e "${RED}Some test suites failed. Check output above for details.${NC}"
    exit 1
else
    echo ""
    echo -e "${GREEN}╔════════════════════════════════════════╗${NC}"
    echo -e "${GREEN}║   All Test Suites Passed! ✓            ║${NC}"
    echo -e "${GREEN}╚════════════════════════════════════════╝${NC}"
    exit 0
fi
