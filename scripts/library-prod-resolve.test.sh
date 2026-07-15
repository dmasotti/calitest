#!/usr/bin/env bash
# Shell tests for scripts/lib/library-prod-resolve.sh
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"
LIB="$PROJECT_ROOT/scripts/lib/library-prod-resolve.sh"

# shellcheck source=/dev/null
source "$LIB"

MOCK_EMAIL="dmasotti@gmail.com"
MOCK_CALIBRE="782613eb-e228-4f08-8747-d502386ca95f"
MOCK_LIBRARY_ID="17"

psql_prod() {
    local sql="$1"
    case "$sql" in
        *"COUNT"*"lower(u.email) = lower('multi@example.com')"*)
            echo "2"
            ;;
        *"COUNT"*"lower(u.email) = lower('${MOCK_EMAIL}')"*)
            echo "1"
            ;;
        *"COUNT"*"lower(u.email)"*)
            echo "0"
            ;;
        *"lower(u.email) = lower('${MOCK_EMAIL}') AND l.calibre_library_id = '${MOCK_CALIBRE}'"*)
            echo "$MOCK_LIBRARY_ID"
            ;;
        *"calibre_library_id = '${MOCK_CALIBRE}'"*)
            echo "$MOCK_LIBRARY_ID"
            ;;
        *"lower(u.email) = lower('multi@example.com')"*)
            printf '%s\n' "3|Lib A|uuid-a" "4|Lib B|uuid-b"
            ;;
        *"lower(u.email) = lower('${MOCK_EMAIL}')"*)
            echo "$MOCK_LIBRARY_ID"
            ;;
        *)
            echo ""
            ;;
    esac
}

psql_local() {
    if [[ "${1:-}" == "-tAc" ]]; then
        local sql="$2"
        case "$sql" in
            *"dmasotti@gmail.com"*) echo "99" ;;
            *) echo "" ;;
        esac
        return 0
    fi
    return 1
}

fail() {
    echo "FAIL: $1" >&2
    exit 1
}

assert_eq() {
    local expected="$1"
    local actual="$2"
    local label="$3"
    if [[ "$expected" != "$actual" ]]; then
        fail "${label}: expected '${expected}', got '${actual}'"
    fi
}

assert_eq "$MOCK_LIBRARY_ID" "$(resolve_prod_library_id "" "$MOCK_CALIBRE" "")" "calibre uuid only"
assert_eq "$MOCK_LIBRARY_ID" "$(resolve_prod_library_id "" "$MOCK_CALIBRE" "$MOCK_EMAIL")" "email + calibre uuid"
assert_eq "$MOCK_LIBRARY_ID" "$(resolve_prod_library_id "" "" "$MOCK_EMAIL")" "email only single library"
assert_eq "$MOCK_LIBRARY_ID" "$(resolve_prod_library_id "$MOCK_LIBRARY_ID" "" "")" "explicit library id"
assert_eq "99" "$(resolve_local_user_id_by_email "$MOCK_EMAIL")" "local user by email"

if resolve_prod_library_id "" "" "missing@example.com" >/dev/null 2>&1; then
    fail "missing email should fail"
fi

if resolve_prod_library_id "" "00000000-0000-0000-0000-000000000000" "" >/dev/null 2>&1; then
    fail "missing calibre uuid should fail"
fi

if resolve_prod_library_id "" "" "multi@example.com" >/dev/null 2>&1; then
    fail "ambiguous email should fail"
fi

echo "OK library-prod-resolve.test.sh"
