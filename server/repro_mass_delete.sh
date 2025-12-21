#!/usr/bin/env bash
# Reproduce mass-delete / heavy delta on staging (production-like) server
# Usage:
#   DISCOVERY_URL=https://coral-shark-984693.hostingersite.com \
#   TEST_USER_EMAIL=dmasotti@gmail.com TEST_USER_PASSWORD='Danny72boy!' \
#   LIBRARY_ID=35 CALIBRE_LIBRARY_ID=c25af01bde8caaac76a023bb035c4a16 \
#   START_CURSOR=OTQ2Njg0ODAw ./repro_mass_delete.sh

set -euo pipefail

DISCOVERY_URL=${DISCOVERY_URL:-https://coral-shark-984693.hostingersite.com}
TEST_EMAIL=${TEST_USER_EMAIL:-}
TEST_PASSWORD=${TEST_USER_PASSWORD:-}
LIB_ID=${LIBRARY_ID:-}
CAL_LIB_ID=${CALIBRE_LIBRARY_ID:-}
CURSOR=${START_CURSOR:-}
LIMIT=${LIMIT:-500}
MAX_PAGES=${MAX_PAGES:-15}

if [[ -z "$TEST_EMAIL" || -z "$TEST_PASSWORD" || -z "$LIB_ID" || -z "$CAL_LIB_ID" || -z "$CURSOR" ]]; then
  echo "Missing required env: TEST_USER_EMAIL, TEST_USER_PASSWORD, LIBRARY_ID, CALIBRE_LIBRARY_ID, START_CURSOR" >&2
  exit 2
fi

API_URL="$DISCOVERY_URL/api"

echo "Authenticating against $API_URL ..."
TOKEN=$(curl -s -X POST "$API_URL/auth/login" -H 'Content-Type: application/json' -d "{\"email\":\"$TEST_EMAIL\",\"password\":\"$TEST_PASSWORD\"}" | jq -r '.token // empty')
if [[ -z "$TOKEN" ]]; then
  echo "Login failed" >&2
  exit 3
fi

page=0
total_changes=0
total_deletes=0
cur="$CURSOR"

while :; do
  echo "--- page $page cursor=$cur ---"
  RESP=$(curl -s -H "Authorization: Bearer $TOKEN" "$API_URL/sync?cursor=$cur&library_id=$LIB_ID&calibre_library_id=$CAL_LIB_ID&limit=$LIMIT")
  count=$(echo "$RESP" | jq -r '.changes | length')
  deletes=$(echo "$RESP" | jq -r '[.changes[] | select(.op=="delete")] | length')
  has_more=$(echo "$RESP" | jq -r '.has_more')
  new_cursor=$(echo "$RESP" | jq -r '.new_cursor // empty')

  echo "count=$count deletes=$deletes has_more=$has_more"
  total_changes=$((total_changes + count))
  total_deletes=$((total_deletes + deletes))

  # Stop conditions
  if [[ "$has_more" != "true" ]]; then
    echo "No more pages"; break
  fi
  if [[ $page -ge $MAX_PAGES ]]; then
    echo "Reached MAX_PAGES=$MAX_PAGES"; break
  fi
  if [[ -z "$new_cursor" ]]; then
    echo "No new_cursor returned, stopping"; break
  fi

  cur="$new_cursor"
  page=$((page + 1))
done

echo "==== summary ===="
echo "pages=$((page+1)) total_changes=$total_changes total_deletes=$total_deletes"
