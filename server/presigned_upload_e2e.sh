#!/usr/bin/env bash
# Live E2E for presigned upload flow:
# start -> PUT presigned URL -> complete -> verify -> status -> start(same hash) reuse check
#
# Usage:
#   CALIMOB_E2E_BASE_URL="https://coral-shark-984693.hostingersite.com" \
#   CALIMOB_E2E_TOKEN="<token>" \
#   CALIMOB_E2E_CONFIRM="YES" \
#   ./tests/server/presigned_upload_e2e.sh

set -euo pipefail

BASE_URL="${CALIMOB_E2E_BASE_URL:-https://coral-shark-984693.hostingersite.com}"
TOKEN="${CALIMOB_E2E_TOKEN:-}"
API_BASE="${BASE_URL%/}/api"
CONFIRM="${CALIMOB_E2E_CONFIRM:-NO}"
LIBRARY_ID="${CALIMOB_E2E_LIBRARY_ID:-}"
BOOK_UUID="${CALIMOB_E2E_BOOK_UUID:-}"
FORMAT="${CALIMOB_E2E_FORMAT:-EPUB}"
CONTENT_TYPE="${CALIMOB_E2E_CONTENT_TYPE:-application/octet-stream}"
POLL_SECONDS="${CALIMOB_E2E_POLL_SECONDS:-1}"
POLL_MAX="${CALIMOB_E2E_POLL_MAX:-20}"
EXPECT_PROVIDER="${CALIMOB_E2E_EXPECT_PROVIDER:-}"
TMPDIR="$(mktemp -d)"

cleanup() {
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

log() { echo "[PRESIGNED-E2E] $1"; }
fail() { echo "✗ $1"; exit 1; }
pass() { echo "✓ $1"; }

if ! command -v curl >/dev/null 2>&1; then fail "curl not found"; fi
if ! command -v jq >/dev/null 2>&1; then fail "jq not found"; fi
if [[ -z "$TOKEN" ]]; then fail "set CALIMOB_E2E_TOKEN"; fi
if [[ "$CONFIRM" != "YES" ]]; then
  echo "This test uploads bytes to real object storage and writes DB state."
  echo "Set CALIMOB_E2E_CONFIRM=YES to proceed."
  exit 2
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

api_post_json() {
  local path="$1"
  local payload="$2"
  local out="$TMPDIR/resp.json"
  local code
  set +e
  code=$(curl -sS --retry 2 --retry-all-errors --max-time 60 -o "$out" -w "%{http_code}" \
    -H "$AUTH_HEADER" -H "$JSON_HEADER" -H "Content-Type: application/json" \
    -X POST "$API_BASE$path" -d "$payload")
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

if [[ -z "$LIBRARY_ID" ]]; then
  log "Resolving library_id"
  api_get "/libraries"
  [[ "$RESPONSE_CODE" == "200" ]] || fail "Cannot list libraries status=$RESPONSE_CODE body=$RESPONSE_BODY"
  LIBRARY_ID="$(echo "$RESPONSE_BODY" | jq -r '.[0].id // empty')"
  [[ -n "$LIBRARY_ID" ]] || fail "No libraries available"
fi
pass "library_id=$LIBRARY_ID"

if [[ -z "$BOOK_UUID" ]]; then
  log "Resolving a book uuid in library_id=$LIBRARY_ID"
  api_get "/user-books?library_id=$LIBRARY_ID&limit=1"
  [[ "$RESPONSE_CODE" == "200" ]] || fail "Cannot list user-books status=$RESPONSE_CODE body=$RESPONSE_BODY"
  BOOK_UUID="$(echo "$RESPONSE_BODY" | jq -r '.data[0].uuid // empty')"
  [[ -n "$BOOK_UUID" ]] || fail "No user-books found in library_id=$LIBRARY_ID"
fi
pass "book_uuid=$BOOK_UUID"

PAYLOAD_TEXT="presigned-e2e $(date -u +%Y-%m-%dT%H:%M:%S.000Z) $RANDOM"
PAYLOAD_FILE="$TMPDIR/payload.bin"
printf "%s" "$PAYLOAD_TEXT" > "$PAYLOAD_FILE"
EXPECTED_SIZE="$(wc -c < "$PAYLOAD_FILE" | tr -d ' ')"
EXPECTED_SHA256="$(shasum -a 256 "$PAYLOAD_FILE" | awk '{print $1}')"
EXPECTED_B64="$(printf "%s" "$EXPECTED_SHA256" | xxd -r -p | openssl base64 -A)"

log "start session"
START_PAYLOAD=$(jq -nc \
  --arg library_id "$LIBRARY_ID" \
  --arg book_uuid "$BOOK_UUID" \
  --arg format "$FORMAT" \
  --arg expected_sha256 "$EXPECTED_SHA256" \
  --argjson expected_size "$EXPECTED_SIZE" \
  --arg content_type "$CONTENT_TYPE" \
  '{library_id: ($library_id|tonumber), book_uuid: $book_uuid, format: $format, expected_sha256: $expected_sha256, expected_size: $expected_size, content_type: $content_type}')

api_post_json "/sync/uploads/start" "$START_PAYLOAD"
[[ "$RESPONSE_CODE" == "200" ]] || fail "start failed status=$RESPONSE_CODE body=$RESPONSE_BODY"

SESSION_ID="$(echo "$RESPONSE_BODY" | jq -r '.session_id // empty')"
STATUS="$(echo "$RESPONSE_BODY" | jq -r '.status // empty')"
UPLOAD_URL="$(echo "$RESPONSE_BODY" | jq -r '.upload_url // empty')"
TEMP_KEY="$(echo "$RESPONSE_BODY" | jq -r '.temp_object_key // empty')"
START_PROVIDER="$(echo "$RESPONSE_BODY" | jq -r '.storage_provider // empty')"
[[ -n "$SESSION_ID" ]] || fail "start: missing session_id"

if [[ -n "$EXPECT_PROVIDER" && -n "$START_PROVIDER" && "$START_PROVIDER" != "$EXPECT_PROVIDER" ]]; then
  fail "start storage_provider mismatch expected=$EXPECT_PROVIDER got=$START_PROVIDER"
fi

if [[ "$STATUS" == "verified" ]]; then
  pass "start returned already verified (dedup hit), skipping upload phase"
else
  [[ -n "$UPLOAD_URL" ]] || fail "start: missing upload_url"
  [[ -n "$TEMP_KEY" ]] || fail "start: missing temp_object_key"

  log "upload to presigned URL"
  PUT_CODE=$(curl -sS --max-time 120 -o "$TMPDIR/put.out" -w "%{http_code}" \
    -X PUT "$UPLOAD_URL" \
    -H "Content-Type: $CONTENT_TYPE" \
    -H "x-amz-checksum-sha256: $EXPECTED_B64" \
    -H "x-amz-sdk-checksum-algorithm: SHA256" \
    --data-binary "@$PAYLOAD_FILE")
  if [[ "$PUT_CODE" != "200" && "$PUT_CODE" != "201" && "$PUT_CODE" != "204" ]]; then
    fail "presigned PUT failed status=$PUT_CODE body=$(cat "$TMPDIR/put.out")"
  fi
  pass "presigned PUT status=$PUT_CODE"

  log "complete session"
  COMPLETE_PAYLOAD=$(jq -nc \
    --arg session_id "$SESSION_ID" \
    --arg object_key "$TEMP_KEY" \
    --argjson size "$EXPECTED_SIZE" \
    '{session_id: $session_id, object_key: $object_key, size: $size}')
  api_post_json "/sync/uploads/complete" "$COMPLETE_PAYLOAD"
  [[ "$RESPONSE_CODE" == "200" ]] || fail "complete failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
  CSTATUS="$(echo "$RESPONSE_BODY" | jq -r '.status // empty')"
  [[ "$CSTATUS" == "uploaded_unverified" || "$CSTATUS" == "verified" ]] || fail "unexpected complete status=$CSTATUS body=$RESPONSE_BODY"
  pass "complete status=$CSTATUS"

  log "verify session (sync)"
  VERIFY_PAYLOAD=$(jq -nc --arg session_id "$SESSION_ID" '{session_id: $session_id}')
  api_post_json "/sync/uploads/verify" "$VERIFY_PAYLOAD"
  [[ "$RESPONSE_CODE" == "200" ]] || fail "verify failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
  VSTATUS="$(echo "$RESPONSE_BODY" | jq -r '.status // empty')"
  [[ "$VSTATUS" == "verified" ]] || fail "verify: expected verified, got status=$VSTATUS body=$RESPONSE_BODY"
  pass "verify status=verified"
fi

log "read session status endpoint"
api_get "/sync/uploads/$SESSION_ID"
[[ "$RESPONSE_CODE" == "200" ]] || fail "status endpoint failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
SSTATUS="$(echo "$RESPONSE_BODY" | jq -r '.status // empty')"
STATUS_PROVIDER="$(echo "$RESPONSE_BODY" | jq -r '.storage_provider // empty')"
[[ "$SSTATUS" == "verified" ]] || fail "status endpoint expected verified, got $SSTATUS"
if [[ -n "$EXPECT_PROVIDER" && -n "$STATUS_PROVIDER" && "$STATUS_PROVIDER" != "$EXPECT_PROVIDER" ]]; then
  fail "status storage_provider mismatch expected=$EXPECT_PROVIDER got=$STATUS_PROVIDER"
fi
pass "status endpoint verified"

log "dedup start check with same hash"
api_post_json "/sync/uploads/start" "$START_PAYLOAD"
[[ "$RESPONSE_CODE" == "200" ]] || fail "2nd start failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
SECOND_STATUS="$(echo "$RESPONSE_BODY" | jq -r '.status // empty')"
ALREADY_EXISTS="$(echo "$RESPONSE_BODY" | jq -r '.already_exists // false')"
if [[ "$SECOND_STATUS" != "verified" || "$ALREADY_EXISTS" != "true" ]]; then
  fail "2nd start expected verified+already_exists=true, got status=$SECOND_STATUS already_exists=$ALREADY_EXISTS body=$RESPONSE_BODY"
fi
pass "dedup reuse confirmed"

echo "✓ Presigned upload live E2E passed"
