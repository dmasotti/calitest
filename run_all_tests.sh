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

# Optional: load html/.env for local dev defaults (no override if already set)
ROOT_ENV_FILE="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)/html/.env"
if [[ -f "$ROOT_ENV_FILE" ]]; then
    set -a
    # shellcheck disable=SC1090
    source "$ROOT_ENV_FILE"
    set +a
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

ensure_test_users() {
    local html_dir="$SCRIPT_DIR/../html"
    if [[ ! -x "$html_dir/artisan" ]]; then
        echo -e "${YELLOW}⚠ Skipping user prep: artisan not found${NC}"
        return 0
    fi

    if [[ -z "${TEST_USER_EMAIL:-}" || -z "${TEST_USER_PASSWORD:-}" ]]; then
        echo -e "${YELLOW}⚠ Skipping user prep: TEST_USER_EMAIL/TEST_USER_PASSWORD not set${NC}"
        return 0
    fi

    pushd "$html_dir" >/dev/null
    local info_out
    info_out="$(php artisan user:info "$TEST_USER_EMAIL" 2>&1 || true)"
    if echo "$info_out" | rg -q "Utente non trovato|User not found"; then
        echo -e "${YELLOW}Creating test user: $TEST_USER_EMAIL${NC}"
        php artisan user:create "$TEST_USER_EMAIL" --password="$TEST_USER_PASSWORD" >/dev/null
    elif ! echo "$info_out" | rg -q "User found|Utente trovato"; then
        echo -e "${YELLOW}Creating test user: $TEST_USER_EMAIL${NC}"
        php artisan user:create "$TEST_USER_EMAIL" --password="$TEST_USER_PASSWORD" >/dev/null
    fi

    popd >/dev/null

    # Always generate a fresh app password for OPDS via API (uses the same DB as the web server)
    if [[ -n "${DISCOVERY_URL:-}" ]]; then
        local api_base="${DISCOVERY_URL%/}/api"
        local login_resp token pass_resp
        login_resp="$(curl -s -X POST "$api_base/auth/login" \
            -H "Content-Type: application/json" \
            -H "Accept: application/json" \
            -d "{\"email\":\"$TEST_USER_EMAIL\",\"password\":\"$TEST_USER_PASSWORD\"}")"
        token="$(python -c 'import json,sys; data=json.loads(sys.stdin.read()); print(data.get("token",""))' <<<"$login_resp" 2>/dev/null || true)"

        if [[ -z "$token" ]]; then
            register_resp="$(curl -s -X POST "$api_base/auth/register" \
                -H "Content-Type: application/json" \
                -H "Accept: application/json" \
                -d "{\"name\":\"test\",\"email\":\"$TEST_USER_EMAIL\",\"password\":\"$TEST_USER_PASSWORD\",\"password_confirmation\":\"$TEST_USER_PASSWORD\"}")"
            token="$(python -c 'import json,sys; data=json.loads(sys.stdin.read()); print(data.get("token",""))' <<<"$register_resp" 2>/dev/null || true)"
        fi

        if [[ -z "$token" ]]; then
            # Fallback: register a unique test user to ensure credentials match.
            local ts new_email
            ts="$(date +%s)"
            if [[ "$TEST_USER_EMAIL" == *"@"* ]]; then
                new_email="${TEST_USER_EMAIL%@*}+${ts}@${TEST_USER_EMAIL#*@}"
            else
                new_email="${TEST_USER_EMAIL}+${ts}"
            fi
            register_resp="$(curl -s -X POST "$api_base/auth/register" \
                -H "Content-Type: application/json" \
                -H "Accept: application/json" \
                -d "{\"name\":\"test\",\"email\":\"$new_email\",\"password\":\"$TEST_USER_PASSWORD\",\"password_confirmation\":\"$TEST_USER_PASSWORD\"}")"
            token="$(python -c 'import json,sys; data=json.loads(sys.stdin.read()); print(data.get("token",""))' <<<"$register_resp" 2>/dev/null || true)"
            if [[ -n "$token" ]]; then
                TEST_USER_EMAIL="$new_email"
                export TEST_USER_EMAIL
                export USER="$TEST_USER_EMAIL"
                echo -e "${YELLOW}Registered fallback test user: $TEST_USER_EMAIL${NC}"
                if [[ -f "$ENV_FILE" ]]; then
                    if rg -q '^TEST_USER_EMAIL=' "$ENV_FILE"; then
                        perl -0pi -e "s/^TEST_USER_EMAIL=.*/TEST_USER_EMAIL=\\\"$TEST_USER_EMAIL\\\"/m" "$ENV_FILE"
                    else
                        echo "TEST_USER_EMAIL=\"$TEST_USER_EMAIL\"" >> "$ENV_FILE"
                    fi
                fi
            fi
        fi

        if [[ -n "$token" ]]; then
            pass_resp="$(curl -s -X POST "$api_base/app-passwords" \
                -H "Authorization: Bearer $token" \
                -H "Content-Type: application/json" \
                -H "Accept: application/json" \
                -d '{"name":"tests-opds"}')"
            APP_PASS="$(python -c 'import json,sys; data=json.loads(sys.stdin.read()); print(data.get("password",""))' <<<"$pass_resp" 2>/dev/null || true)"
        fi

        if [[ -n "${APP_PASS:-}" ]]; then
            export APP_PASS
            export OPDS_PASS="$APP_PASS"
            echo -e "${YELLOW}Generated app password for OPDS tests${NC}"
            if [[ -f "$ENV_FILE" ]]; then
                if rg -q '^APP_PASS=' "$ENV_FILE"; then
                    perl -0pi -e "s/^APP_PASS=.*/APP_PASS=\"$APP_PASS\"/m" "$ENV_FILE"
                else
                    echo "APP_PASS=\"$APP_PASS\"" >> "$ENV_FILE"
                fi
            fi
        else
            echo -e "${YELLOW}⚠ Unable to generate app password via API (OPDS may fail)${NC}"
        fi
    fi
}

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
    
    # Pass env vars to child script
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
export APP_PASS="${APP_PASS:-}"

ensure_test_users

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

# 4. UUID Reconciliation Tests
run_test_suite "UUID Reconciliation" "$SCRIPT_DIR/server/sync_uuid_reconciliation_test.sh" || true

echo ""

# 5. Metadata Comprehensive Tests
run_test_suite "Metadata Comprehensive" "$SCRIPT_DIR/server/metadata_test.sh" || true

echo ""

# 6. PHPUnit Server Suite (protocol + unit/integration)
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${BLUE}Running: PHPUnit Server Suite${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""
if [[ -x "$SCRIPT_DIR/../html/vendor/bin/phpunit" ]]; then
    if ( set -a; source "$ROOT_ENV_FILE"; set +a; "$SCRIPT_DIR/../html/vendor/bin/phpunit" -c "$SCRIPT_DIR/../phpunit.xml" --testsuite=Server ); then
        echo ""
        echo -e "${GREEN}✓ PHPUnit Server Suite PASSED${NC}"
    else
        echo ""
        echo -e "${RED}✗ PHPUnit Server Suite FAILED${NC}"
        FAILED_SUITES+=("PHPUnit Server Suite")
    fi
else
    echo -e "${YELLOW}⚠ PHPUnit not found (skipped)${NC}"
    FAILED_SUITES+=("PHPUnit Server Suite")
fi

echo ""
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo -e "${CYAN}           Test Execution Summary         ${NC}"
echo -e "${CYAN}━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━${NC}"
echo ""

TOTAL_SUITES=6
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
