#!/usr/bin/env bash
set -euo pipefail

# E2E sync test against production server.
# Creates a test library, seeds books, runs 2 syncs, verifies, cleans up.
# Fully idempotent: cleanup runs on exit (success or failure).

BASE_URL="https://coral-shark-984693.hostingersite.com"
TOKEN="44|jHjh0i1wsHYoPpSz2m7gRoUmWhtd7E2K5SiN1MEt984e5f11"
TEST_LIB_UUID="e2e-test-$(date +%s)-$(openssl rand -hex 4)"
LIB_ID=""
PASS_COUNT=0
FAIL_COUNT=0

sql() {
  local q="$1"
  curl -s -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -d "{\"q\": \"$q\"}" \
    "$BASE_URL/api/tools/sql"
}

sync_v5() {
  local body="$1"
  curl -s -w "\n__HTTP_CODE__%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -d "$body" \
    "$BASE_URL/api/sync/v5"
}

cleanup() {
  if [ -n "$LIB_ID" ]; then
    echo
    echo "[CLEANUP] Removing test library $LIB_ID and its books..."
    sql "DELETE FROM books WHERE user_id = 1 AND library_id = $LIB_ID" > /dev/null 2>&1 || true
    sql "DELETE FROM libraries WHERE id = $LIB_ID" > /dev/null 2>&1 || true
    echo "[CLEANUP] Done"
  fi
}
trap cleanup EXIT

assert_eq() {
  local label="$1" expected="$2" actual="$3"
  if [ "$expected" = "$actual" ]; then
    echo "  ✅ PASS: $label"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "  ❌ FAIL: $label — expected '$expected', got '$actual'"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

echo "============================================"
echo "E2E Production Sync Test"
echo "Server: $BASE_URL"
echo "Test library UUID: $TEST_LIB_UUID"
echo "============================================"
echo

# ── Step 1: Create test library ──────────────────────────────────────
echo "[1] Creating test library..."
LIB_RESULT=$(sql "INSERT INTO libraries (calibre_library_id, user_id, name, created_at, updated_at) VALUES ('$TEST_LIB_UUID', 1, 'E2E Test Library', NOW(), NOW())")
echo "  Result: $(echo "$LIB_RESULT" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("status","?"))' 2>/dev/null || echo "$LIB_RESULT")"

# Get library ID
LIB_ID=$(sql "SELECT id FROM libraries WHERE calibre_library_id = '$TEST_LIB_UUID' AND user_id = 1" | python3 -c 'import sys,json; print(json.load(sys.stdin)["rows"][0]["id"])' 2>/dev/null)
echo "  Library ID: $LIB_ID"

# ── Step 2: Seed 50 test books ───────────────────────────────────────
echo
echo "[2] Seeding 50 test books..."
for i in $(seq 1 50); do
  UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
  sql "INSERT INTO books (id, uuid, user_id, library_id, title, path, author_sort, series_index, pubdate, last_modified, has_cover, created_at, updated_at) VALUES ($((60000+i)), '$UUID', 1, $LIB_ID, 'E2E Test Book $i', 'e2e-test-$i', 'Test Author $i', 1.0, '2020-01-01', NOW(), 0, NOW(), NOW())" > /dev/null
done

# Verify count
BOOK_COUNT=$(sql "SELECT COUNT(*) as cnt FROM books WHERE user_id = 1 AND library_id = $LIB_ID AND deleted_at IS NULL" | python3 -c 'import sys,json; print(json.load(sys.stdin)["rows"][0]["cnt"])' 2>/dev/null)
echo "  Books seeded: $BOOK_COUNT"

# Get UUIDs and server hashes
echo "  Fetching server hashes..."
BOOKS_JSON=$(sql "SELECT uuid FROM books WHERE user_id = 1 AND library_id = $LIB_ID AND deleted_at IS NULL ORDER BY uuid")
UUIDS=$(echo "$BOOKS_JSON" | python3 -c 'import sys,json; [print(r["uuid"]) for r in json.load(sys.stdin)["rows"]]' 2>/dev/null)

# Get hashes from VIEW
HASHES_JSON=$(sql "SELECT uuid, metadata_hash FROM books_hash_v2 WHERE user_id = 1 AND library_id = $LIB_ID")
echo "  Hashes fetched: $(echo "$HASHES_JSON" | python3 -c 'import sys,json; print(json.load(sys.stdin).get("count",0))' 2>/dev/null)"

# ── Step 3: Sync 1 — all wrong hashes ───────────────────────────────
echo
echo "[3] Sync 1: all wrong hashes (expect 50 updates)..."

# Build client_books with wrong hashes
CLIENT_BOOKS=$(echo "$UUIDS" | python3 -c '
import sys, json
books = {}
for line in sys.stdin:
    uuid = line.strip()
    if uuid:
        books[uuid] = {"m": "0" * 64, "c": None, "f": None}
print(json.dumps(books))
')
CANDIDATE_UUIDS=$(echo "$UUIDS" | python3 -c '
import sys, json
uuids = [l.strip() for l in sys.stdin if l.strip()]
print(json.dumps(uuids))
')

SYNC1_BODY=$(python3 -c "
import json, sys
cb = json.loads(sys.argv[1])
cu = json.loads(sys.argv[2])
print(json.dumps({
    'library_id': '$LIB_ID',
    'calibre_library_uuid': '$TEST_LIB_UUID',
    'cursor': None,
    'batch_size': 100,
    'client_books': {'b': cb, 'd': []},
    'options': {
        'sync_files_enabled': False,
        'sync_covers_enabled': False,
        'metadata_candidate_uuids': cu
    }
}))
" "$CLIENT_BOOKS" "$CANDIDATE_UUIDS")

START1=$(python3 -c "import time; print(time.time())")
SYNC1_RAW=$(sync_v5 "$SYNC1_BODY")
END1=$(python3 -c "import time; print(time.time())")

SYNC1_HTTP=$(echo "$SYNC1_RAW" | grep "__HTTP_CODE__" | sed 's/__HTTP_CODE__//')
SYNC1_BODY_RESP=$(echo "$SYNC1_RAW" | sed '/__HTTP_CODE__/d')
SYNC1_MS=$(python3 -c "print(int(($END1 - $START1) * 1000))")

SYNC1_UPDATES=$(echo "$SYNC1_BODY_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get("updates_for_client",[])))' 2>/dev/null || echo "?")
SYNC1_SKIPPED=$(echo "$SYNC1_BODY_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("skipped_hash",0))' 2>/dev/null || echo "?")
SYNC1_HAS_MORE=$(echo "$SYNC1_BODY_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("has_more",False))' 2>/dev/null || echo "?")

echo "  HTTP: $SYNC1_HTTP | Time: ${SYNC1_MS}ms"
echo "  Updates: $SYNC1_UPDATES | Skipped: $SYNC1_SKIPPED | has_more: $SYNC1_HAS_MORE"

assert_eq "Sync1: 50 updates (all mismatch)" "50" "$SYNC1_UPDATES"
assert_eq "Sync1: has_more=False" "False" "$SYNC1_HAS_MORE"

# ── Step 4: Sync 2 — correct hashes (expect 0 updates) ──────────────
echo
echo "[4] Sync 2: correct hashes (expect 0 updates)..."

# Build client_books with correct hashes from server
CLIENT_BOOKS2=$(echo "$HASHES_JSON" | python3 -c '
import sys, json
data = json.load(sys.stdin)
books = {}
for row in data.get("rows", []):
    uuid = row["uuid"]
    h = row["metadata_hash"].lower() if row["metadata_hash"] else "0" * 64
    books[uuid] = {"m": h, "c": None, "f": None}
print(json.dumps(books))
')

SYNC2_BODY=$(python3 -c "
import json, sys
cb = json.loads(sys.argv[1])
cu = json.loads(sys.argv[2])
print(json.dumps({
    'library_id': '$LIB_ID',
    'calibre_library_uuid': '$TEST_LIB_UUID',
    'cursor': None,
    'batch_size': 100,
    'client_books': {'b': cb, 'd': []},
    'options': {
        'sync_files_enabled': False,
        'sync_covers_enabled': False,
        'metadata_candidate_uuids': cu
    }
}))
" "$CLIENT_BOOKS2" "$CANDIDATE_UUIDS")

START2=$(python3 -c "import time; print(time.time())")
SYNC2_RAW=$(sync_v5 "$SYNC2_BODY")
END2=$(python3 -c "import time; print(time.time())")

SYNC2_BODY_RESP=$(echo "$SYNC2_RAW" | sed '/__HTTP_CODE__/d')
SYNC2_MS=$(python3 -c "print(int(($END2 - $START2) * 1000))")

SYNC2_UPDATES=$(echo "$SYNC2_BODY_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get("updates_for_client",[])))' 2>/dev/null || echo "?")
SYNC2_SKIPPED=$(echo "$SYNC2_BODY_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(d.get("skipped_hash",0))' 2>/dev/null || echo "?")

echo "  Time: ${SYNC2_MS}ms"
echo "  Updates: $SYNC2_UPDATES | Skipped: $SYNC2_SKIPPED"

assert_eq "Sync2: 0 updates (all match)" "0" "$SYNC2_UPDATES"

# ── Step 5: Test server metadata change propagates ───────────────────
echo
echo "[5] Server change propagates..."
FIRST_UUID=$(echo "$UUIDS" | head -1)
sql "UPDATE books SET title = 'MODIFIED BY E2E TEST' WHERE uuid = '$FIRST_UUID' AND user_id = 1" > /dev/null

# Sync with old hash for that book
SYNC3_BODY=$(python3 -c "
import json, sys
uuid = sys.argv[1]
print(json.dumps({
    'library_id': sys.argv[2],
    'calibre_library_uuid': sys.argv[3],
    'cursor': None,
    'batch_size': 100,
    'client_books': {'b': {uuid: {'m': '0' * 64, 'c': None, 'f': None}}, 'd': []},
    'options': {
        'sync_files_enabled': False,
        'sync_covers_enabled': False,
        'metadata_candidate_uuids': [uuid]
    }
}))
" "$FIRST_UUID" "$LIB_ID" "$TEST_LIB_UUID")

SYNC3_RAW=$(sync_v5 "$SYNC3_BODY")
SYNC3_BODY_RESP=$(echo "$SYNC3_RAW" | sed '/__HTTP_CODE__/d')
SYNC3_TITLE=$(echo "$SYNC3_BODY_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); u=d.get("updates_for_client",[]); print(u[0]["title"] if u else "NONE")' 2>/dev/null || echo "?")

assert_eq "Server change propagates" "MODIFIED BY E2E TEST" "$SYNC3_TITLE"

# ── Step 6: Load test — 5 rapid sequential syncs ────────────────────
# Re-fetch hashes (step 5 modified one book)
echo
echo "[6] Load test: 5 rapid sequential syncs (50 books each)..."

HASHES_JSON_FRESH=$(sql "SELECT uuid, metadata_hash FROM books_hash_v2 WHERE user_id = 1 AND library_id = $LIB_ID")
CLIENT_BOOKS_FRESH=$(echo "$HASHES_JSON_FRESH" | python3 -c '
import sys, json
data = json.load(sys.stdin)
books = {}
for row in data.get("rows", []):
    uuid = row["uuid"]
    h = row["metadata_hash"].lower() if row["metadata_hash"] else "0" * 64
    books[uuid] = {"m": h, "c": None, "f": None}
print(json.dumps(books))
')
LOAD_BODY=$(python3 -c "
import json, sys
cb = json.loads(sys.argv[1])
cu = json.loads(sys.argv[2])
print(json.dumps({
    'library_id': sys.argv[3],
    'calibre_library_uuid': sys.argv[4],
    'cursor': None,
    'batch_size': 100,
    'client_books': {'b': cb, 'd': []},
    'options': {
        'sync_files_enabled': False,
        'sync_covers_enabled': False,
        'metadata_candidate_uuids': cu
    }
}))
" "$CLIENT_BOOKS_FRESH" "$CANDIDATE_UUIDS" "$LIB_ID" "$TEST_LIB_UUID")

LOAD_TIMES=""
for i in $(seq 1 5); do
  START_L=$(python3 -c "import time; print(time.time())")
  LOAD_RAW=$(sync_v5 "$LOAD_BODY")
  END_L=$(python3 -c "import time; print(time.time())")
  LOAD_MS=$(python3 -c "print(int(($END_L - $START_L) * 1000))")
  LOAD_TIMES="$LOAD_TIMES $LOAD_MS"
  LOAD_RESP=$(echo "$LOAD_RAW" | sed '/__HTTP_CODE__/d')
  LOAD_UPDATES=$(echo "$LOAD_RESP" | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get("updates_for_client",[])))' 2>/dev/null || echo "?")
  echo "  Batch $i: ${LOAD_MS}ms, $LOAD_UPDATES updates"
  assert_eq "Load batch $i: 0 updates" "0" "$LOAD_UPDATES"
done

AVG_LOAD=$(python3 -c "times=[int(x) for x in '$LOAD_TIMES'.split()]; print(int(sum(times)/len(times)))")
echo "  Average: ${AVG_LOAD}ms"

# ── Step 7: Concurrency — simulate 2 users syncing different libs ────
echo
echo "[7] Concurrency: create 2nd test library, sync both..."

TEST_LIB_UUID2="e2e-test2-$(date +%s)-$(openssl rand -hex 4)"
sql "INSERT INTO libraries (calibre_library_id, user_id, name, created_at, updated_at) VALUES ('$TEST_LIB_UUID2', 1, 'E2E Test Library 2', NOW(), NOW())" > /dev/null
LIB_ID2=$(sql "SELECT id FROM libraries WHERE calibre_library_id = '$TEST_LIB_UUID2' AND user_id = 1" | python3 -c 'import sys,json; print(json.load(sys.stdin)["rows"][0]["id"])' 2>/dev/null)

# Seed 20 books in lib2
LIB2_UUIDS=""
for i in $(seq 1 20); do
  UUID=$(python3 -c "import uuid; print(uuid.uuid4())")
  sql "INSERT INTO books (id, uuid, user_id, library_id, title, path, author_sort, series_index, pubdate, last_modified, has_cover, created_at, updated_at) VALUES ($((61000+i)), '$UUID', 1, $LIB_ID2, 'E2E Lib2 Book $i', 'e2e-lib2-$i', 'Author $i', 1.0, '2020-01-01', NOW(), 0, NOW(), NOW())" > /dev/null
  LIB2_UUIDS="$LIB2_UUIDS $UUID"
done

# Build sync request for lib2
LIB2_CLIENT_BOOKS=$(echo $LIB2_UUIDS | python3 -c '
import sys, json
books = {}
for uuid in sys.stdin.read().strip().split():
    books[uuid] = {"m": "0" * 64, "c": None, "f": None}
print(json.dumps(books))
')
LIB2_CANDIDATES=$(echo $LIB2_UUIDS | python3 -c '
import sys, json
uuids = sys.stdin.read().strip().split()
print(json.dumps(uuids))
')

LIB2_SYNC_BODY=$(python3 -c "
import json, sys
cb = json.loads(sys.argv[1])
cu = json.loads(sys.argv[2])
print(json.dumps({
    'library_id': sys.argv[3],
    'calibre_library_uuid': sys.argv[4],
    'cursor': None,
    'batch_size': 100,
    'client_books': {'b': cb, 'd': []},
    'options': {
        'sync_files_enabled': False,
        'sync_covers_enabled': False,
        'metadata_candidate_uuids': cu
    }
}))
" "$LIB2_CLIENT_BOOKS" "$LIB2_CANDIDATES" "$LIB_ID2" "$TEST_LIB_UUID2")

# Sync lib1 and lib2
SYNC_LIB1_RAW=$(sync_v5 "$SYNC1_BODY")
SYNC_LIB2_RAW=$(sync_v5 "$LIB2_SYNC_BODY")

SYNC_LIB1_UPDATES=$(echo "$SYNC_LIB1_RAW" | sed '/__HTTP_CODE__/d' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get("updates_for_client",[])))' 2>/dev/null || echo "?")
SYNC_LIB2_UPDATES=$(echo "$SYNC_LIB2_RAW" | sed '/__HTTP_CODE__/d' | python3 -c 'import sys,json; d=json.load(sys.stdin); print(len(d.get("updates_for_client",[])))' 2>/dev/null || echo "?")

assert_eq "Lib1: 50 updates" "50" "$SYNC_LIB1_UPDATES"
assert_eq "Lib2: 20 updates" "20" "$SYNC_LIB2_UPDATES"

# Verify isolation: lib2 response must not contain lib1 UUIDs
LIB2_UPDATE_UUIDS=$(echo "$SYNC_LIB2_RAW" | sed '/__HTTP_CODE__/d' | python3 -c 'import sys,json; d=json.load(sys.stdin); [print(u["uuid"]) for u in d.get("updates_for_client",[])]' 2>/dev/null)
FIRST_LIB1_UUID=$(echo "$UUIDS" | head -1)
if echo "$LIB2_UPDATE_UUIDS" | grep -q "$FIRST_LIB1_UUID" 2>/dev/null; then
  echo "  ❌ FAIL: Lib2 response contains Lib1 UUID (isolation broken)"
  FAIL_COUNT=$((FAIL_COUNT + 1))
else
  echo "  ✅ PASS: Library isolation verified"
  PASS_COUNT=$((PASS_COUNT + 1))
fi

# Cleanup lib2
sql "DELETE FROM books WHERE user_id = 1 AND library_id = $LIB_ID2" > /dev/null 2>&1 || true
sql "DELETE FROM libraries WHERE id = $LIB_ID2" > /dev/null 2>&1 || true

# ── Summary ──────────────────────────────────────────────────────────
# (Cleanup of lib1 happens via trap EXIT)
echo
echo "============================================"
echo "E2E Production Sync Test — RESULTS"
echo "  Sync 1 (mismatch): ${SYNC1_MS}ms, $SYNC1_UPDATES updates"
echo "  Sync 2 (match):    ${SYNC2_MS}ms, $SYNC2_UPDATES updates"
echo "  Load avg:          ${AVG_LOAD}ms"
echo "  Server change:     $SYNC3_TITLE"
echo "  Passed: $PASS_COUNT | Failed: $FAIL_COUNT"
echo "============================================"

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
