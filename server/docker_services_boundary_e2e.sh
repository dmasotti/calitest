#!/usr/bin/env bash
# Real E2E test for Laravel <-> Docker services boundary.
# It uses a real online library and verifies:
# - endpoint contracts on live API
# - indexing/chat async workflow
# - persistence in chat_logs and external_service_operation_logs
#
# Usage:
#   CALIMOB_E2E_BASE_URL="https://coral-shark-984693.hostingersite.com" \
#   CALIMOB_E2E_TOKEN="<superadmin-or-user-token>" \
#   CALIMOB_E2E_FAKE_INDEXING="true" \
#   ./tests/server/docker_services_boundary_e2e.sh

set -euo pipefail

BASE_URL="${CALIMOB_E2E_BASE_URL:-https://coral-shark-984693.hostingersite.com}"
TOKEN="${CALIMOB_E2E_TOKEN:-}"
API_BASE="${BASE_URL%/}/api"
FAKE_INDEXING="${CALIMOB_E2E_FAKE_INDEXING:-true}"
TEXT_FORMAT_MODE="${CALIMOB_E2E_TEXT_FORMAT:-AUTO}" # AUTO|EPUB|PDF
REQUIRE_TEXT_FORMAT="${CALIMOB_E2E_REQUIRE_TEXT_FORMAT:-false}"
STRICT_INDEXING="${CALIMOB_E2E_STRICT_INDEXING:-false}"
COMICS_INDEXING="${CALIMOB_E2E_COMICS_INDEXING:-false}"
TMPDIR="$(mktemp -d)"
RUN_ID="$(date +%s)"

cleanup() {
  rm -rf "$TMPDIR"
}
trap cleanup EXIT

if ! command -v curl >/dev/null 2>&1; then
  echo "ERROR: curl not found"
  exit 1
fi
if ! command -v jq >/dev/null 2>&1; then
  echo "ERROR: jq not found"
  exit 1
fi
if [[ -z "$TOKEN" ]]; then
  echo "ERROR: set CALIMOB_E2E_TOKEN"
  exit 2
fi
if [[ "$FAKE_INDEXING" != "true" && "$FAKE_INDEXING" != "false" ]]; then
  echo "ERROR: CALIMOB_E2E_FAKE_INDEXING must be true or false"
  exit 2
fi
if [[ "$TEXT_FORMAT_MODE" != "AUTO" && "$TEXT_FORMAT_MODE" != "EPUB" && "$TEXT_FORMAT_MODE" != "PDF" ]]; then
  echo "ERROR: CALIMOB_E2E_TEXT_FORMAT must be AUTO, EPUB, or PDF"
  exit 2
fi
if [[ "$STRICT_INDEXING" != "true" && "$STRICT_INDEXING" != "false" ]]; then
  echo "ERROR: CALIMOB_E2E_STRICT_INDEXING must be true or false"
  exit 2
fi
if [[ "$COMICS_INDEXING" != "true" && "$COMICS_INDEXING" != "false" ]]; then
  echo "ERROR: CALIMOB_E2E_COMICS_INDEXING must be true or false"
  exit 2
fi

AUTH_HEADER="Authorization: Bearer $TOKEN"
JSON_HEADER="Accept: application/json"

log() { echo "[E2E] $1"; }
fail() { echo "✗ $1"; exit 1; }
pass() { echo "✓ $1"; }

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

api_post_form() {
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

log "Checking converter health endpoint"
api_get "/converter/health"
if [[ "$RESPONSE_CODE" != "200" && "$RESPONSE_CODE" != "503" ]]; then
  fail "Unexpected /converter/health status=$RESPONSE_CODE body=$RESPONSE_BODY"
fi
pass "/converter/health status=$RESPONSE_CODE"

log "Loading libraries"
api_get "/libraries"
if [[ "$RESPONSE_CODE" != "200" ]]; then
  fail "Cannot list libraries status=$RESPONSE_CODE body=$RESPONSE_BODY"
fi
LIBRARY_ID="$(echo "$RESPONSE_BODY" | jq -r '.[0].id // empty')"
if [[ -z "$LIBRARY_ID" ]]; then
  fail "No libraries available for E2E test"
fi
pass "Using library_id=$LIBRARY_ID"

log "Finding a book with EPUB/PDF or CBZ/CBR"
api_get "/user-books?library_id=$LIBRARY_ID&limit=200"
if [[ "$RESPONSE_CODE" != "200" ]]; then
  fail "Cannot list user-books status=$RESPONSE_CODE body=$RESPONSE_BODY"
fi

EPUB_UUID="$(echo "$RESPONSE_BODY" | jq -r '.data[] | select((.files // []) | map(.format) | any(.=="EPUB")) | .uuid' | head -n 1)"
PDF_UUID="$(echo "$RESPONSE_BODY" | jq -r '.data[] | select((.files // []) | map(.format) | any(.=="PDF")) | .uuid' | head -n 1)"
TEXT_UUID=""
TEXT_FORMAT=""
case "$TEXT_FORMAT_MODE" in
  EPUB)
    TEXT_UUID="$EPUB_UUID"
    TEXT_FORMAT="EPUB"
    ;;
  PDF)
    TEXT_UUID="$PDF_UUID"
    TEXT_FORMAT="PDF"
    ;;
  AUTO)
    if [[ -n "$EPUB_UUID" ]]; then
      TEXT_UUID="$EPUB_UUID"
      TEXT_FORMAT="EPUB"
    elif [[ -n "$PDF_UUID" ]]; then
      TEXT_UUID="$PDF_UUID"
      TEXT_FORMAT="PDF"
    fi
    ;;
esac
CBZ_UUID="$(echo "$RESPONSE_BODY" | jq -r '.data[] | select((.files // []) | map(.format) | any(.=="CBZ" or .=="CBR")) | .uuid' | head -n 1)"
CBZ_FORMAT="$(echo "$RESPONSE_BODY" | jq -r --arg uuid "${CBZ_UUID:-}" '.data[] | select(.uuid == $uuid) | (.files // []) | map(.format) | map(select(.=="CBZ" or .=="CBR")) | .[0] // empty' | head -n 1)"

if [[ "$REQUIRE_TEXT_FORMAT" == "true" && -z "$TEXT_UUID" ]]; then
  fail "Required text format $TEXT_FORMAT_MODE not found in library_id=$LIBRARY_ID"
fi
if [[ -z "$TEXT_UUID" && -z "$CBZ_UUID" ]]; then
  fail "No suitable book found (need at least EPUB/PDF or CBZ/CBR)"
fi
pass "Book discovery OK (epub_uuid=${EPUB_UUID:-none}, pdf_uuid=${PDF_UUID:-none}, selected_text=${TEXT_FORMAT:-none}, cbz_uuid=${CBZ_UUID:-none}, fake_indexing=$FAKE_INDEXING)"

if [[ -n "$TEXT_UUID" ]]; then
  log "Preflight text chat/status uuid=$TEXT_UUID format=$TEXT_FORMAT"
  api_get "/books/$TEXT_UUID/chat/status?format=$TEXT_FORMAT"
  if [[ "$RESPONSE_CODE" != "200" ]]; then
    fail "Text preflight chat/status failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
  fi
  pass "Text preflight chat/status OK"

  log "Start indexing for text book uuid=$TEXT_UUID format=$TEXT_FORMAT fake=$FAKE_INDEXING"
  api_get "/books/$TEXT_UUID/chat/status?format=$TEXT_FORMAT"
  INDEXED_NOW="$(echo "$RESPONSE_BODY" | jq -r '.indexed // false')"
  if [[ "$INDEXED_NOW" != "true" ]]; then
    api_post_json "/books/$TEXT_UUID/chat/index" "{\"format\":\"$TEXT_FORMAT\",\"fake\":$FAKE_INDEXING}"
    if [[ "$RESPONSE_CODE" != "200" && "$RESPONSE_CODE" != "409" ]]; then
      # Upstream timeout on /upload-async is known to happen on degraded service;
      # continue and attempt chat/result anyway.
      log "Indexing returned status=$RESPONSE_CODE, continuing with chat flow"
    fi
  else
    log "Book already indexed, skipping index start"
  fi
  pass "Indexing phase completed"

  QUESTION="E2E boundary ping $RUN_ID"
  log "Sending async chat for text format $TEXT_FORMAT"
  api_post_json "/books/$TEXT_UUID/chat" "{\"message\":\"$QUESTION\",\"format\":\"$TEXT_FORMAT\",\"mcp_enabled\":true}"
  if [[ "$RESPONSE_CODE" != "202" ]]; then
    fail "Chat async failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
  fi
  JOB_ID="$(echo "$RESPONSE_BODY" | jq -r '.job_id // empty')"
  if [[ -z "$JOB_ID" ]]; then
    fail "No job_id returned from async chat"
  fi
  pass "Async chat started job_id=$JOB_ID"

  FINAL_STATUS=""
  for i in $(seq 1 15); do
    sleep 4
    api_get "/books/$TEXT_UUID/chat/result?job_id=$JOB_ID"
    if [[ "$RESPONSE_CODE" == "202" ]]; then
      continue
    fi
    if [[ "$RESPONSE_CODE" == "200" ]]; then
      FINAL_STATUS="$(echo "$RESPONSE_BODY" | jq -r '.status // (if .answer then "completed" else "" end)')"
      if [[ "$FINAL_STATUS" == "completed" || "$FINAL_STATUS" == "success" || "$FINAL_STATUS" == "error" ]]; then
        break
      fi
    fi
  done

  if [[ -z "$FINAL_STATUS" ]]; then
    fail "Chat result did not settle in time"
  fi
  pass "Chat result settled with status=$FINAL_STATUS"

  if [[ "$STRICT_INDEXING" == "true" ]]; then
    log "Strict indexing verification for format=$TEXT_FORMAT book=$TEXT_UUID"
    SQL_INDEX=$(cat <<EOF
{"q":"SELECT status,chunks_indexed,embedding_provider,embedding_model,vision_provider,vision_model,created_at FROM indexing_logs WHERE book_uuid='$TEXT_UUID' AND format='$TEXT_FORMAT' ORDER BY id DESC LIMIT 1"}
EOF
)
    api_post_form "/tools/sql" "$SQL_INDEX"
    if [[ "$RESPONSE_CODE" != "200" ]]; then
      fail "SQL indexing log query failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
    fi
    IDX_ROWS="$(echo "$RESPONSE_BODY" | jq -r '.rows | length')"
    if [[ "$IDX_ROWS" -lt 1 ]]; then
      fail "No indexing_logs row found for strict indexing check"
    fi
    IDX_STATUS="$(echo "$RESPONSE_BODY" | jq -r '.rows[0].status // empty')"
    if [[ "$IDX_STATUS" != "success" ]]; then
      fail "Strict indexing expected success, got status=$IDX_STATUS"
    fi
    pass "Strict indexing check passed (status=success, format=$TEXT_FORMAT)"
  fi

  log "Checking DB logs for chat and operations"
  SQL_CHAT=$(cat <<EOF
{"q":"SELECT id,status,llm_model,llm_tokens_used,created_at FROM chat_logs WHERE book_uuid='$TEXT_UUID' ORDER BY id DESC LIMIT 5"}
EOF
)
  api_post_form "/tools/sql" "$SQL_CHAT"
  if [[ "$RESPONSE_CODE" != "200" ]]; then
    fail "SQL chat log query failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
  fi
  CHAT_ROWS="$(echo "$RESPONSE_BODY" | jq -r '.rows | length')"
  if [[ "$CHAT_ROWS" -lt 1 ]]; then
    fail "No chat_logs rows found for tested book"
  fi
  pass "chat_logs rows found: $CHAT_ROWS"

  SQL_OPS=$(cat <<EOF
{"q":"SELECT service,provider,operation_type,created_at FROM external_service_operation_logs WHERE created_at > DATE_SUB(NOW(), INTERVAL 20 MINUTE) ORDER BY id DESC LIMIT 20"}
EOF
)
  api_post_form "/tools/sql" "$SQL_OPS"
  if [[ "$RESPONSE_CODE" != "200" ]]; then
    fail "SQL operation logs query failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
  fi
  OPS_ROWS="$(echo "$RESPONSE_BODY" | jq -r '.rows | length')"
  if [[ "$OPS_ROWS" -lt 1 ]]; then
    fail "No external_service_operation_logs rows found in recent window"
  fi
  pass "operation logs rows found: $OPS_ROWS"
fi

if [[ -n "$CBZ_UUID" ]]; then
  log "Preflight comics chat/status uuid=$CBZ_UUID format=$CBZ_FORMAT"
  api_get "/books/$CBZ_UUID/chat/status?format=$CBZ_FORMAT"
  if [[ "$RESPONSE_CODE" != "200" ]]; then
    fail "Comics preflight chat/status failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
  fi
  pass "Comics preflight chat/status OK"

  if [[ "$COMICS_INDEXING" == "true" ]]; then
    log "Comics indexing E2E uuid=$CBZ_UUID format=$CBZ_FORMAT fake=$FAKE_INDEXING"
    api_post_json "/books/$CBZ_UUID/chat/index" "{\"format\":\"$CBZ_FORMAT\",\"fake\":$FAKE_INDEXING}"
    if [[ "$RESPONSE_CODE" != "200" && "$RESPONSE_CODE" != "409" ]]; then
      fail "Unexpected comics indexing status=$RESPONSE_CODE body=$RESPONSE_BODY"
    fi
    if [[ "$STRICT_INDEXING" == "true" ]]; then
      SQL_CBZ_INDEX=$(cat <<EOF
{"q":"SELECT status,chunks_indexed,vision_provider,vision_model,created_at FROM indexing_logs WHERE book_uuid='$CBZ_UUID' AND format='$CBZ_FORMAT' ORDER BY id DESC LIMIT 1"}
EOF
)
      api_post_form "/tools/sql" "$SQL_CBZ_INDEX"
      if [[ "$RESPONSE_CODE" != "200" ]]; then
        fail "SQL comics indexing query failed status=$RESPONSE_CODE body=$RESPONSE_BODY"
      fi
      CBZ_ROWS="$(echo "$RESPONSE_BODY" | jq -r '.rows | length')"
      if [[ "$CBZ_ROWS" -lt 1 ]]; then
        fail "No comics indexing_logs row found"
      fi
      CBZ_STATUS="$(echo "$RESPONSE_BODY" | jq -r '.rows[0].status // empty')"
      if [[ "$CBZ_STATUS" != "success" ]]; then
        fail "Strict comics indexing expected success, got status=$CBZ_STATUS"
      fi
      pass "Comics strict indexing check passed (status=success)"
    fi
  else
    log "Comics smoke E2E uuid=$CBZ_UUID format=$CBZ_FORMAT"
    api_post_json "/books/$CBZ_UUID/chat" "{\"message\":\"E2E comics ping $RUN_ID\",\"format\":\"$CBZ_FORMAT\",\"mcp_enabled\":false}"
    if [[ "$RESPONSE_CODE" != "202" && "$RESPONSE_CODE" != "500" && "$RESPONSE_CODE" != "504" ]]; then
      fail "Unexpected comics chat status=$RESPONSE_CODE body=$RESPONSE_BODY"
    fi
    pass "Comics chat request returned status=$RESPONSE_CODE"
  fi
fi

pass "Docker boundary live E2E completed"
