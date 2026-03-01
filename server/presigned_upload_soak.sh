#!/usr/bin/env bash
# Presigned upload soak test:
# runs TOTAL start->PUT->complete->verify flows with configurable concurrency.
#
# Usage:
#   CALIMOB_E2E_BASE_URL="https://..." \
#   CALIMOB_E2E_TOKEN="<token>" \
#   CALIMOB_E2E_CONFIRM="YES" \
#   CALIMOB_SOAK_TOTAL=30 \
#   CALIMOB_SOAK_CONCURRENCY=6 \
#   ./tests/server/presigned_upload_soak.sh

set -euo pipefail

BASE_URL="${CALIMOB_E2E_BASE_URL:-https://coral-shark-984693.hostingersite.com}"
TOKEN="${CALIMOB_E2E_TOKEN:-}"
API_BASE="${BASE_URL%/}/api"
CONFIRM="${CALIMOB_E2E_CONFIRM:-NO}"
LIBRARY_ID="${CALIMOB_E2E_LIBRARY_ID:-}"
BOOK_UUID="${CALIMOB_E2E_BOOK_UUID:-}"
FORMAT="${CALIMOB_E2E_FORMAT:-EPUB}"
CONTENT_TYPE="${CALIMOB_E2E_CONTENT_TYPE:-application/octet-stream}"
TOTAL="${CALIMOB_SOAK_TOTAL:-20}"
CONCURRENCY="${CALIMOB_SOAK_CONCURRENCY:-5}"

TMPDIR="$(mktemp -d)"
RESULTS_DIR="$TMPDIR/results"
mkdir -p "$RESULTS_DIR"

cleanup() {
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

fail() { echo "✗ $1"; exit 1; }
log() { echo "[PRESIGNED-SOAK] $1"; }
pass() { echo "✓ $1"; }

if ! command -v curl >/dev/null 2>&1; then fail "curl not found"; fi
if ! command -v jq >/dev/null 2>&1; then fail "jq not found"; fi
if ! command -v shasum >/dev/null 2>&1; then fail "shasum not found"; fi
if ! command -v xxd >/dev/null 2>&1; then fail "xxd not found"; fi
if ! command -v openssl >/dev/null 2>&1; then fail "openssl not found"; fi
if [[ -z "$TOKEN" ]]; then fail "set CALIMOB_E2E_TOKEN"; fi
if [[ "$CONFIRM" != "YES" ]]; then
  echo "This soak test uploads many files to real object storage and writes DB state."
  echo "Set CALIMOB_E2E_CONFIRM=YES to proceed."
  exit 2
fi
if ! [[ "$TOTAL" =~ ^[0-9]+$ ]] || ! [[ "$CONCURRENCY" =~ ^[0-9]+$ ]]; then
  fail "CALIMOB_SOAK_TOTAL and CALIMOB_SOAK_CONCURRENCY must be integers"
fi
if (( TOTAL < 1 || CONCURRENCY < 1 )); then
  fail "TOTAL and CONCURRENCY must be >= 1"
fi

AUTH_HEADER="Authorization: Bearer $TOKEN"
JSON_HEADER="Accept: application/json"

api_get() {
  local path="$1"
  local out="$TMPDIR/resp.json"
  local code
  set +e
  code=$(curl -sS --retry 2 --retry-all-errors --max-time 60 -o "$out" -w "%{http_code}" \
    -H "$AUTH_HEADER" -H "$JSON_HEADER" \
    "$API_BASE$path")
  local curl_exit=$?
  set -e
  if [[ $curl_exit -ne 0 ]]; then
    RESPONSE_CODE="000"
    RESPONSE_BODY="curl_error:$curl_exit"
    return 0
  fi
  RESPONSE_CODE="$code"
  RESPONSE_BODY="$(cat "$out")"
}

resolve_scope() {
  if [[ -z "$LIBRARY_ID" ]]; then
    api_get "/libraries"
    [[ "$RESPONSE_CODE" == "200" ]] || fail "Cannot list libraries status=$RESPONSE_CODE body=$RESPONSE_BODY"
    LIBRARY_ID="$(echo "$RESPONSE_BODY" | jq -r '.[0].id // empty')"
    [[ -n "$LIBRARY_ID" ]] || fail "No libraries available"
  fi

  if [[ -z "$BOOK_UUID" ]]; then
    api_get "/user-books?library_id=$LIBRARY_ID&limit=1"
    [[ "$RESPONSE_CODE" == "200" ]] || fail "Cannot list user-books status=$RESPONSE_CODE body=$RESPONSE_BODY"
    BOOK_UUID="$(echo "$RESPONSE_BODY" | jq -r '.data[0].uuid // empty')"
    [[ -n "$BOOK_UUID" ]] || fail "No user-books found in library_id=$LIBRARY_ID"
  fi
}

run_one() {
  local idx="$1"
  local workdir="$TMPDIR/job-$idx"
  mkdir -p "$workdir"

  local payload_file="$workdir/payload.bin"
  local payload_text="presigned-soak-$idx-$(date -u +%Y-%m-%dT%H:%M:%S)-$RANDOM"
  printf "%s" "$payload_text" > "$payload_file"
  local expected_size
  expected_size="$(wc -c < "$payload_file" | tr -d ' ')"
  local expected_sha256
  expected_sha256="$(shasum -a 256 "$payload_file" | awk '{print $1}')"
  local expected_b64
  expected_b64="$(printf "%s" "$expected_sha256" | xxd -r -p | openssl base64 -A)"

  local started_at=$SECONDS

  local start_payload
  start_payload="$(jq -nc \
    --arg library_id "$LIBRARY_ID" \
    --arg book_uuid "$BOOK_UUID" \
    --arg format "$FORMAT" \
    --arg expected_sha256 "$expected_sha256" \
    --argjson expected_size "$expected_size" \
    --arg content_type "$CONTENT_TYPE" \
    '{library_id: ($library_id|tonumber), book_uuid: $book_uuid, format: $format, expected_sha256: $expected_sha256, expected_size: $expected_size, content_type: $content_type}')"

  local start_resp="$workdir/start.json"
  local start_code
  set +e
  start_code=$(curl -sS --retry 2 --retry-all-errors --max-time 60 -o "$start_resp" -w "%{http_code}" \
    -H "$AUTH_HEADER" -H "$JSON_HEADER" -H "Content-Type: application/json" \
    -X POST "$API_BASE/sync/uploads/start" -d "$start_payload")
  local curl_exit=$?
  set -e
  if [[ $curl_exit -ne 0 || "$start_code" != "200" ]]; then
    echo "{\"idx\":$idx,\"ok\":false,\"step\":\"start\",\"code\":\"$start_code\",\"elapsed_s\":$((SECONDS-started_at))}" > "$RESULTS_DIR/$idx.json"
    return 0
  fi

  local session_id
  session_id="$(jq -r '.session_id // empty' "$start_resp")"
  local status
  status="$(jq -r '.status // empty' "$start_resp")"
  local temp_key
  temp_key="$(jq -r '.temp_object_key // empty' "$start_resp")"
  local upload_url
  upload_url="$(jq -r '.upload_url // empty' "$start_resp")"

  if [[ -z "$session_id" ]]; then
    echo "{\"idx\":$idx,\"ok\":false,\"step\":\"start_payload\",\"elapsed_s\":$((SECONDS-started_at))}" > "$RESULTS_DIR/$idx.json"
    return 0
  fi

  if [[ "$status" != "verified" ]]; then
    if [[ -z "$upload_url" || -z "$temp_key" ]]; then
      echo "{\"idx\":$idx,\"ok\":false,\"step\":\"start_missing_upload_data\",\"elapsed_s\":$((SECONDS-started_at))}" > "$RESULTS_DIR/$idx.json"
      return 0
    fi

    local put_code
    set +e
    put_code=$(curl -sS --max-time 120 -o "$workdir/put.out" -w "%{http_code}" \
      -X PUT "$upload_url" \
      -H "Content-Type: $CONTENT_TYPE" \
      -H "x-amz-checksum-sha256: $expected_b64" \
      -H "x-amz-sdk-checksum-algorithm: SHA256" \
      --data-binary "@$payload_file")
    set -e
    if [[ "$put_code" != "200" && "$put_code" != "201" && "$put_code" != "204" ]]; then
      echo "{\"idx\":$idx,\"ok\":false,\"step\":\"put\",\"code\":\"$put_code\",\"elapsed_s\":$((SECONDS-started_at))}" > "$RESULTS_DIR/$idx.json"
      return 0
    fi

    local complete_payload
    complete_payload="$(jq -nc --arg session_id "$session_id" --arg object_key "$temp_key" --argjson size "$expected_size" \
      '{session_id: $session_id, object_key: $object_key, size: $size}')"
    local complete_resp="$workdir/complete.json"
    local complete_code
    complete_code=$(curl -sS --retry 2 --retry-all-errors --max-time 60 -o "$complete_resp" -w "%{http_code}" \
      -H "$AUTH_HEADER" -H "$JSON_HEADER" -H "Content-Type: application/json" \
      -X POST "$API_BASE/sync/uploads/complete" -d "$complete_payload")
    if [[ "$complete_code" != "200" ]]; then
      echo "{\"idx\":$idx,\"ok\":false,\"step\":\"complete\",\"code\":\"$complete_code\",\"elapsed_s\":$((SECONDS-started_at))}" > "$RESULTS_DIR/$idx.json"
      return 0
    fi

    local verify_payload
    verify_payload="$(jq -nc --arg session_id "$session_id" '{session_id: $session_id}')"
    local verify_resp="$workdir/verify.json"
    local verify_code
    verify_code=$(curl -sS --retry 2 --retry-all-errors --max-time 120 -o "$verify_resp" -w "%{http_code}" \
      -H "$AUTH_HEADER" -H "$JSON_HEADER" -H "Content-Type: application/json" \
      -X POST "$API_BASE/sync/uploads/verify" -d "$verify_payload")
    if [[ "$verify_code" != "200" ]]; then
      echo "{\"idx\":$idx,\"ok\":false,\"step\":\"verify\",\"code\":\"$verify_code\",\"elapsed_s\":$((SECONDS-started_at))}" > "$RESULTS_DIR/$idx.json"
      return 0
    fi
  fi

  echo "{\"idx\":$idx,\"ok\":true,\"elapsed_s\":$((SECONDS-started_at))}" > "$RESULTS_DIR/$idx.json"
}

export -f run_one
export API_BASE AUTH_HEADER JSON_HEADER TMPDIR RESULTS_DIR LIBRARY_ID BOOK_UUID FORMAT CONTENT_TYPE

resolve_scope
log "library_id=$LIBRARY_ID book_uuid=$BOOK_UUID total=$TOTAL concurrency=$CONCURRENCY"

seq 1 "$TOTAL" | xargs -I{} -P "$CONCURRENCY" bash -lc 'run_one "$@"' _ {}

all_json="$(cat "$RESULTS_DIR"/*.json)"
successes="$(printf "%s\n" "$all_json" | jq -s '[.[] | select(.ok == true)] | length')"
failures="$(printf "%s\n" "$all_json" | jq -s '[.[] | select(.ok != true)] | length')"
avg_s="$(printf "%s\n" "$all_json" | jq -s '[.[].elapsed_s] | if length == 0 then 0 else (add / length) end')"
max_s="$(printf "%s\n" "$all_json" | jq -s '[.[].elapsed_s] | max // 0')"

echo "---- SOAK SUMMARY ----"
echo "base_url=$BASE_URL"
echo "provider_expected=${CALIMOB_E2E_EXPECT_PROVIDER:-n/a}"
echo "library_id=$LIBRARY_ID"
echo "book_uuid=$BOOK_UUID"
echo "total=$TOTAL"
echo "concurrency=$CONCURRENCY"
echo "successes=$successes"
echo "failures=$failures"
echo "avg_elapsed_s=$avg_s"
echo "max_elapsed_s=$max_s"

if [[ "$failures" != "0" ]]; then
  echo "---- FAILURES ----"
  printf "%s\n" "$all_json" | jq -c 'select(.ok != true)'
  fail "soak run has failures"
fi

pass "soak run passed"
