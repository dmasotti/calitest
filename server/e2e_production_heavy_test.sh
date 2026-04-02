#!/usr/bin/env bash
set -euo pipefail

# Heavy E2E test against production: large library (12870 books)
# Tests: batched sync, load, concurrency across libraries.
# Read-only on existing data — does NOT create or modify books.

BASE_URL="https://coral-shark-984693.hostingersite.com"
TOKEN="44|jHjh0i1wsHYoPpSz2m7gRoUmWhtd7E2K5SiN1MEt984e5f11"
LARGE_LIB_ID="2"
LARGE_LIB_UUID="782613eb-e228-4f08-8747-d502386ca95f"
PASS_COUNT=0
FAIL_COUNT=0

sql() {
  curl -s -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -d "{\"q\": \"$1\"}" \
    "$BASE_URL/api/tools/sql"
}

sync_v5() {
  curl -s -w "\n__HTTP_CODE__%{http_code}" \
    -H "Authorization: Bearer $TOKEN" \
    -H "Accept: application/json" \
    -H "Content-Type: application/json" \
    -d "$1" \
    "$BASE_URL/api/sync/v5"
}

parse_sync() {
  local raw="$1" field="$2"
  echo "$raw" | sed '/__HTTP_CODE__/d' | python3 -c "
import sys, json
d = json.load(sys.stdin)
v = d
for k in '$field'.split('.'):
    if isinstance(v, dict):
        v = v.get(k)
    elif isinstance(v, list):
        v = len(v)
    else:
        break
if isinstance(v, list):
    print(len(v))
elif v is None:
    print('null')
else:
    print(v)
" 2>/dev/null || echo "?"
}

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

assert_lt() {
  local label="$1" max="$2" actual="$3"
  if [ "$actual" -lt "$max" ] 2>/dev/null; then
    echo "  ✅ PASS: $label (${actual} < ${max})"
    PASS_COUNT=$((PASS_COUNT + 1))
  else
    echo "  ❌ FAIL: $label — ${actual} >= ${max}"
    FAIL_COUNT=$((FAIL_COUNT + 1))
  fi
}

echo "============================================"
echo "E2E Production HEAVY Test"
echo "Server: $BASE_URL"
echo "Library: $LARGE_LIB_ID ($LARGE_LIB_UUID)"
echo "============================================"

# ── Get book count and sample UUIDs ──────────────────────────────────
echo
echo "[SETUP] Fetching library stats..."
BOOK_COUNT=$(sql "SELECT COUNT(*) as cnt FROM books WHERE user_id = 1 AND library_id = $LARGE_LIB_ID AND deleted_at IS NULL" \
  | python3 -c 'import sys,json; print(json.load(sys.stdin)["rows"][0]["cnt"])' 2>/dev/null)
echo "  Books: $BOOK_COUNT"

# ── Test 1: Small batch (100 books) — 10% mismatch ──────────────────
echo
echo "[1] Small batch: 100 candidates, all mismatch..."

SAMPLE_100=$(sql "SELECT uuid FROM books WHERE user_id = 1 AND library_id = $LARGE_LIB_ID AND deleted_at IS NULL LIMIT 100")
CB_100=$(echo "$SAMPLE_100" | python3 -c '
import sys, json
rows = json.load(sys.stdin)["rows"]
books = {r["uuid"]: {"m": "0" * 64, "c": None, "f": None} for r in rows}
print(json.dumps(books))
')
CU_100=$(echo "$SAMPLE_100" | python3 -c '
import sys, json
rows = json.load(sys.stdin)["rows"]
print(json.dumps([r["uuid"] for r in rows]))
')
BODY_100=$(python3 -c "
import json, sys
cb = json.loads(sys.argv[1]); cu = json.loads(sys.argv[2])
print(json.dumps({'library_id': '$LARGE_LIB_ID', 'calibre_library_uuid': '$LARGE_LIB_UUID',
  'cursor': None, 'batch_size': 200, 'client_books': {'b': cb, 'd': []},
  'options': {'sync_files_enabled': False, 'sync_covers_enabled': False, 'metadata_candidate_uuids': cu}}))
" "$CB_100" "$CU_100")

START=$(python3 -c "import time; print(time.time())")
R1=$(sync_v5 "$BODY_100")
MS1=$(python3 -c "import time; print(int((time.time() - $START) * 1000))")

U1=$(parse_sync "$R1" "updates_for_client")
HM1=$(parse_sync "$R1" "has_more")
echo "  Time: ${MS1}ms | Updates: $U1 | has_more: $HM1"
assert_eq "100 candidates: 100 updates" "100" "$U1"
assert_eq "100 candidates: has_more=False" "False" "$HM1"
assert_lt "100 candidates: under 10s" 10000 "$MS1"

# ── Test 2: Medium batch (500 books) — all mismatch ─────────────────
echo
echo "[2] Medium batch: 500 candidates, all mismatch..."

SAMPLE_500=$(sql "SELECT uuid FROM books WHERE user_id = 1 AND library_id = $LARGE_LIB_ID AND deleted_at IS NULL LIMIT 500")
CB_500=$(echo "$SAMPLE_500" | python3 -c '
import sys, json
rows = json.load(sys.stdin)["rows"]
books = {r["uuid"]: {"m": "0" * 64, "c": None, "f": None} for r in rows}
print(json.dumps(books))
')
CU_500=$(echo "$SAMPLE_500" | python3 -c '
import sys, json
rows = json.load(sys.stdin)["rows"]
print(json.dumps([r["uuid"] for r in rows]))
')
BODY_500=$(python3 -c "
import json, sys
cb = json.loads(sys.argv[1]); cu = json.loads(sys.argv[2])
print(json.dumps({'library_id': '$LARGE_LIB_ID', 'calibre_library_uuid': '$LARGE_LIB_UUID',
  'cursor': None, 'batch_size': 1000, 'client_books': {'b': cb, 'd': []},
  'options': {'sync_files_enabled': False, 'sync_covers_enabled': False, 'metadata_candidate_uuids': cu}}))
" "$CB_500" "$CU_500")

START=$(python3 -c "import time; print(time.time())")
R2=$(sync_v5 "$BODY_500")
MS2=$(python3 -c "import time; print(int((time.time() - $START) * 1000))")

U2=$(parse_sync "$R2" "updates_for_client")
echo "  Time: ${MS2}ms | Updates: $U2"
assert_eq "500 candidates: 500 updates" "500" "$U2"
assert_lt "500 candidates: under 30s" 30000 "$MS2"

# ── Test 3: 500 candidates all MATCH (correct hashes) ───────────────
echo
echo "[3] Medium batch: 500 candidates, all match..."

HASHES_500=$(sql "SELECT uuid, metadata_hash FROM books_hash_v2 WHERE user_id = 1 AND library_id = $LARGE_LIB_ID LIMIT 500")
CB_MATCH=$(echo "$HASHES_500" | python3 -c '
import sys, json
rows = json.load(sys.stdin)["rows"]
books = {r["uuid"]: {"m": r["metadata_hash"].lower(), "c": None, "f": None} for r in rows}
print(json.dumps(books))
')
CU_MATCH=$(echo "$HASHES_500" | python3 -c '
import sys, json
rows = json.load(sys.stdin)["rows"]
print(json.dumps([r["uuid"] for r in rows]))
')
BODY_MATCH=$(python3 -c "
import json, sys
cb = json.loads(sys.argv[1]); cu = json.loads(sys.argv[2])
print(json.dumps({'library_id': '$LARGE_LIB_ID', 'calibre_library_uuid': '$LARGE_LIB_UUID',
  'cursor': None, 'batch_size': 1000, 'client_books': {'b': cb, 'd': []},
  'options': {'sync_files_enabled': False, 'sync_covers_enabled': False, 'metadata_candidate_uuids': cu}}))
" "$CB_MATCH" "$CU_MATCH")

START=$(python3 -c "import time; print(time.time())")
R3=$(sync_v5 "$BODY_MATCH")
MS3=$(python3 -c "import time; print(int((time.time() - $START) * 1000))")

U3=$(parse_sync "$R3" "updates_for_client")
echo "  Time: ${MS3}ms | Updates: $U3"
assert_eq "500 match: 0 updates" "0" "$U3"
assert_lt "500 match: under 10s" 10000 "$MS3"

# ── Test 4: Load — 5 rapid sequential syncs (500 match each) ────────
echo
echo "[4] Load: 5 rapid sequential syncs (500 match)..."
LOAD_TIMES=""
for i in $(seq 1 5); do
  START_L=$(python3 -c "import time; print(time.time())")
  RL=$(sync_v5 "$BODY_MATCH")
  MS_L=$(python3 -c "import time; print(int((time.time() - $START_L) * 1000))")
  LOAD_TIMES="$LOAD_TIMES $MS_L"
  UL=$(parse_sync "$RL" "updates_for_client")
  echo "  Request $i: ${MS_L}ms, $UL updates"
  assert_eq "Load $i: 0 updates" "0" "$UL"
done
AVG_LOAD=$(python3 -c "t=[int(x) for x in '$LOAD_TIMES'.split()]; print(int(sum(t)/len(t)))")
P95_LOAD=$(python3 -c "t=sorted([int(x) for x in '$LOAD_TIMES'.split()]); print(t[int(len(t)*0.95)])")
echo "  Average: ${AVG_LOAD}ms | P95: ${P95_LOAD}ms"

# ── Test 5: Concurrency — 2 libraries simultaneously ────────────────
echo
echo "[5] Concurrency: large lib (500 match) + small lib (100 mismatch) back-to-back..."

# Small lib = library 1 (95 books)
SMALL_LIB_ID="1"
SMALL_LIB_UUID="1685fd4f-054e-4451-9df8-119c27fc1289"

SAMPLE_SMALL=$(sql "SELECT uuid FROM books WHERE user_id = 1 AND library_id = $SMALL_LIB_ID AND deleted_at IS NULL LIMIT 50")
CB_SMALL=$(echo "$SAMPLE_SMALL" | python3 -c '
import sys, json
rows = json.load(sys.stdin)["rows"]
books = {r["uuid"]: {"m": "0" * 64, "c": None, "f": None} for r in rows}
print(json.dumps(books))
')
CU_SMALL=$(echo "$SAMPLE_SMALL" | python3 -c '
import sys, json
rows = json.load(sys.stdin)["rows"]
print(json.dumps([r["uuid"] for r in rows]))
')
BODY_SMALL=$(python3 -c "
import json, sys
cb = json.loads(sys.argv[1]); cu = json.loads(sys.argv[2])
print(json.dumps({'library_id': '$SMALL_LIB_ID', 'calibre_library_uuid': '$SMALL_LIB_UUID',
  'cursor': None, 'batch_size': 100, 'client_books': {'b': cb, 'd': []},
  'options': {'sync_files_enabled': False, 'sync_covers_enabled': False, 'metadata_candidate_uuids': cu}}))
" "$CB_SMALL" "$CU_SMALL")

# Fire both sequentially (bash can't do true parallel HTTP easily)
START_C1=$(python3 -c "import time; print(time.time())")
RC1=$(sync_v5 "$BODY_MATCH")
MS_C1=$(python3 -c "import time; print(int((time.time() - $START_C1) * 1000))")

START_C2=$(python3 -c "import time; print(time.time())")
RC2=$(sync_v5 "$BODY_SMALL")
MS_C2=$(python3 -c "import time; print(int((time.time() - $START_C2) * 1000))")

UC1=$(parse_sync "$RC1" "updates_for_client")
UC2=$(parse_sync "$RC2" "updates_for_client")
echo "  Large lib (500 match): ${MS_C1}ms, $UC1 updates"
echo "  Small lib (50 mismatch): ${MS_C2}ms, $UC2 updates"
assert_eq "Concurrent large: 0 updates" "0" "$UC1"
assert_eq "Concurrent small: 50 updates" "50" "$UC2"

# Verify isolation: small lib updates must not contain large lib UUIDs
LARGE_SAMPLE_UUID=$(echo "$HASHES_500" | python3 -c 'import sys,json; print(json.load(sys.stdin)["rows"][0]["uuid"])' 2>/dev/null)
SMALL_UUIDS=$(echo "$RC2" | sed '/__HTTP_CODE__/d' | python3 -c '
import sys, json
d = json.load(sys.stdin)
for u in d.get("updates_for_client", []):
    print(u.get("uuid",""))
' 2>/dev/null)
if echo "$SMALL_UUIDS" | grep -q "$LARGE_SAMPLE_UUID" 2>/dev/null; then
  echo "  ❌ FAIL: Library isolation broken"
  FAIL_COUNT=$((FAIL_COUNT + 1))
else
  echo "  ✅ PASS: Library isolation verified"
  PASS_COUNT=$((PASS_COUNT + 1))
fi

# ── Test 6: True parallel — 3 curl requests at once ─────────────────
echo
echo "[6] True parallel: 3 sync requests fired simultaneously..."

TMPDIR=$(mktemp -d)
START_P=$(python3 -c "import time; print(time.time())")

# Fire 3 requests in parallel
curl -s -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" -H "Content-Type: application/json" \
  -d "$BODY_MATCH" "$BASE_URL/api/sync/v5" > "$TMPDIR/r1.json" &
PID1=$!

curl -s -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" -H "Content-Type: application/json" \
  -d "$BODY_MATCH" "$BASE_URL/api/sync/v5" > "$TMPDIR/r2.json" &
PID2=$!

curl -s -H "Authorization: Bearer $TOKEN" -H "Accept: application/json" -H "Content-Type: application/json" \
  -d "$BODY_SMALL" "$BASE_URL/api/sync/v5" > "$TMPDIR/r3.json" &
PID3=$!

wait $PID1 $PID2 $PID3
MS_P=$(python3 -c "import time; print(int((time.time() - $START_P) * 1000))")

P_U1=$(python3 -c 'import sys,json; d=json.load(open(sys.argv[1])); print(len(d.get("updates_for_client",[])))' "$TMPDIR/r1.json" 2>/dev/null || echo "?")
P_U2=$(python3 -c 'import sys,json; d=json.load(open(sys.argv[1])); print(len(d.get("updates_for_client",[])))' "$TMPDIR/r2.json" 2>/dev/null || echo "?")
P_U3=$(python3 -c 'import sys,json; d=json.load(open(sys.argv[1])); print(len(d.get("updates_for_client",[])))' "$TMPDIR/r3.json" 2>/dev/null || echo "?")

echo "  Wall time: ${MS_P}ms (3 parallel requests)"
echo "  R1 (500 match): $P_U1 updates"
echo "  R2 (500 match): $P_U2 updates"
echo "  R3 (50 mismatch): $P_U3 updates"
assert_eq "Parallel R1: 0 updates" "0" "$P_U1"
assert_eq "Parallel R2: 0 updates" "0" "$P_U2"
assert_eq "Parallel R3: 50 updates" "50" "$P_U3"

rm -rf "$TMPDIR"

# ── Summary ──────────────────────────────────────────────────────────
echo
echo "============================================"
echo "E2E Production HEAVY Test — RESULTS"
echo "  Library: $BOOK_COUNT books"
echo "  100 mismatch:  ${MS1}ms"
echo "  500 mismatch:  ${MS2}ms"
echo "  500 match:     ${MS3}ms"
echo "  Load avg:      ${AVG_LOAD}ms (5 sequential)"
echo "  Parallel (3):  ${MS_P}ms wall time"
echo "  Passed: $PASS_COUNT | Failed: $FAIL_COUNT"
echo "============================================"

if [ "$FAIL_COUNT" -gt 0 ]; then
  exit 1
fi
