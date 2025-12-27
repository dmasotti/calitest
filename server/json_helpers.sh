#!/usr/bin/env bash
# Shared helpers for validating and logging JSON responses in server tests.

# The helper assumes bash (shebang).

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
INVALID_JSON_LOG_DIR="${INVALID_JSON_LOG_DIR:-$SCRIPT_DIR/tmp/invalid_json_logs}"
mkdir -p "$INVALID_JSON_LOG_DIR"

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

    if command -v jq >/dev/null 2>&1; then
        if echo "$json_string" | jq -e . >/dev/null 2>&1; then
            echo "$json_string" | jq '.'
            return 0
        fi
    else
        echo "jq binary missing; install jq to validate JSON responses." >&2
        exit 1
    fi

    local log_file
    log_file=$(log_invalid_json_response "$context" "$json_string")
    echo -e "ERROR: Invalid JSON received from API (context: $context)." >&2
    echo "Raw API Response logged to $log_file" >&2
    exit 1
}
