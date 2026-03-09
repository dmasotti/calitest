#!/usr/bin/env bash
# Wrapper E2E for Laravel <-> Docker boundary with mock/fake indexing enabled.
#
# It forces fake mode for indexing calls while keeping real HTTP integration path:
# Laravel API -> Docker services (rag/rag-comics/converter) -> callbacks/status.
#
# Usage:
#   CALIMOB_E2E_BASE_URL="https://coral-shark-984693.hostingersite.com" \
#   CALIMOB_E2E_TOKEN="<token>" \
#   ./tests/server/docker_services_boundary_e2e_mock.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BASE_SCRIPT="$SCRIPT_DIR/docker_services_boundary_e2e.sh"
BASE_URL="${CALIMOB_E2E_BASE_URL:-https://coral-shark-984693.hostingersite.com}"
TOKEN="${CALIMOB_E2E_TOKEN:-}"
API_BASE="${BASE_URL%/}/api"
TMPDIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

if [[ ! -x "$BASE_SCRIPT" ]]; then
  echo "ERROR: base script not executable: $BASE_SCRIPT"
  exit 1
fi

echo "[E2E-MOCK] Running boundary E2E with fake indexing enabled"
echo "[E2E-MOCK] base_url=$BASE_URL"

CALIMOB_E2E_FAKE_INDEXING="true" \
CALIMOB_E2E_COMICS_INDEXING="${CALIMOB_E2E_COMICS_INDEXING:-true}" \
CALIMOB_E2E_STRICT_INDEXING="${CALIMOB_E2E_STRICT_INDEXING:-false}" \
"$BASE_SCRIPT"

if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq is required for structured log checks"
  exit 1
fi
if [[ -z "$TOKEN" ]]; then
  echo "ERROR: CALIMOB_E2E_TOKEN is required for structured log checks"
  exit 1
fi

fetch_service_logs() {
  local service="$1"
  local out="$TMPDIR/${service}.json"
  local code
  code=$(curl -sS -o "$out" -w "%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/json" \
    "$API_BASE/superadmin/docker/logs/$service?tail=400")
  if [[ "$code" != "200" ]]; then
    echo "ERROR: logs API failed for $service (status=$code)"
    cat "$out" 2>/dev/null || true
    return 1
  fi
  jq -r '.logs[]? | if type=="object" then (.message // "") elif type=="string" then . else "" end' "$out"
}

assert_structured_log_fields() {
  local service="$1"
  local logs
  logs="$(fetch_service_logs "$service")"
  if [[ -z "$logs" ]]; then
    echo "ERROR: empty logs for $service"
    return 1
  fi
  local line
  line="$(printf "%s\n" "$logs" | grep -E '"event":[[:space:]]*"http_request"' | tail -n 1 || true)"
  if [[ -z "$line" ]]; then
    echo "ERROR: no structured http_request log found for $service"
    return 1
  fi
  for field in event phase service request_id user_id library_uuid book_uuid method path; do
    if ! printf "%s\n" "$line" | grep -q "\"$field\""; then
      echo "ERROR: structured log missing field '$field' for $service"
      echo "LINE: $line"
      return 1
    fi
  done
  echo "[E2E-MOCK] structured logging OK for $service"
}

echo "[E2E-MOCK] Checking structured request logs via superadmin docker logs API..."
assert_structured_log_fields "calimob-rag"
assert_structured_log_fields "calimob-converter"

echo "[E2E-MOCK] Completed successfully"
