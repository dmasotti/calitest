#!/usr/bin/env python3
"""
E2E scramble sync test against production.

Flow:
  1. Create test library on server
  2. Copy 500 books from large library (real metadata)
  3. Sync 1: all hashes should match (same data)
  4. Scramble 10% on server (change titles)
  5. Scramble 10% on client (different books, change titles in SQLite)
  6. Sync 2: server-changed books → updates_for_client, client-changed → hash mismatch
  7. Log everything: timing, hash comparison, payload diffs
  8. Cleanup

Usage:
  python3 tests/server/e2e_scramble_sync_test.py
"""

import json
import os
import random
import sqlite3
import subprocess
import sys
import time
import hashlib
import shutil
import tempfile

BASE_URL = "https://coral-shark-984693.hostingersite.com"
TOKEN = "44|jHjh0i1wsHYoPpSz2m7gRoUmWhtd7E2K5SiN1MEt984e5f11"
SOURCE_LIB_ID = 2  # Large library with 12870 books
SOURCE_LIB_UUID = "782613eb-e228-4f08-8747-d502386ca95f"
NUM_BOOKS = 500
SCRAMBLE_PCT = 0.10

# Add sync_calimob to path for hash UDFs
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'sync_calimob'))
from mapping_table import sha256_udf, json_quote_ascii_udf

PASS = 0
FAIL = 0
LOG_LINES = []


def log(msg):
    ts = time.strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line)
    LOG_LINES.append(line)


def sql(query):
    """Execute SQL on production server."""
    r = subprocess.run([
        'curl', '-s',
        '-H', f'Authorization: Bearer {TOKEN}',
        '-H', 'Accept: application/json',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps({'q': query}),
        f'{BASE_URL}/api/tools/sql'
    ], capture_output=True, text=True, timeout=60)
    if not r.stdout.strip():
        return {'rows': [], 'count': 0, 'status': 'empty_response'}
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        return {'rows': [], 'count': 0, 'status': 'json_error', 'raw': r.stdout[:200]}
    if data.get('status') == 'error':
        log(f"  SQL ERROR: {data.get('message', '?')[:200]}")
        return {'rows': [], 'count': 0}
    return data


def sync_v5(body):
    """POST /api/sync/v5 and return parsed response + timing."""
    start = time.time()
    r = subprocess.run([
        'curl', '-s',
        '-H', f'Authorization: Bearer {TOKEN}',
        '-H', 'Accept: application/json',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps(body),
        f'{BASE_URL}/api/sync/v5'
    ], capture_output=True, text=True, timeout=120)
    elapsed_ms = int((time.time() - start) * 1000)
    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:
        data = {'error': 'invalid JSON', 'raw': r.stdout[:500]}
    return data, elapsed_ms


def assert_eq(label, expected, actual):
    global PASS, FAIL
    if expected == actual:
        log(f"  ✅ {label}")
        PASS += 1
    else:
        log(f"  ❌ {label} — expected {expected!r}, got {actual!r}")
        FAIL += 1


def assert_gt(label, minimum, actual):
    global PASS, FAIL
    if actual > minimum:
        log(f"  ✅ {label} ({actual} > {minimum})")
        PASS += 1
    else:
        log(f"  ❌ {label} — {actual} <= {minimum}")
        FAIL += 1


def cleanup(lib_id):
    if lib_id:
        log(f"[CLEANUP] Removing test library {lib_id}...")
        sql(f"DELETE FROM books WHERE user_id = 1 AND library_id = {lib_id}")
        sql(f"DELETE FROM libraries WHERE id = {lib_id}")
        log("[CLEANUP] Done")


def main():
    test_lib_uuid = f"e2e-scramble-{int(time.time())}-{random.randint(1000,9999)}"
    lib_id = None

    log("=" * 70)
    log("E2E SCRAMBLE SYNC TEST")
    log(f"Server: {BASE_URL}")
    log(f"Source library: {SOURCE_LIB_ID} ({NUM_BOOKS} books)")
    log(f"Scramble: {int(SCRAMBLE_PCT*100)}%")
    log("=" * 70)

    try:
        # ── Step 1: Create test library ──────────────────────────────
        log("\n[1] Creating test library...")
        sql(f"INSERT INTO libraries (calibre_library_id, user_id, name, created_at, updated_at) "
            f"VALUES ('{test_lib_uuid}', 1, 'E2E Scramble Test', NOW(), NOW())")
        rows = sql(f"SELECT id FROM libraries WHERE calibre_library_id = '{test_lib_uuid}' AND user_id = 1")['rows']
        if not rows:
            log("  FATAL: Could not create test library")
            return
        lib_id = rows[0]['id']
        log(f"  Library ID: {lib_id}")

        # ── Step 2: Copy books from source library ───────────────────
        log(f"\n[2] Copying {NUM_BOOKS} books from library {SOURCE_LIB_ID}...")
        t0 = time.time()

        # Get source UUIDs
        source_books = sql(
            f"SELECT uuid, title, author_sort, series_index, pubdate, description, rating, has_cover "
            f"FROM books WHERE user_id = 1 AND library_id = {SOURCE_LIB_ID} AND deleted_at IS NULL "
            f"ORDER BY uuid LIMIT {NUM_BOOKS}"
        )['rows']
        log(f"  Fetched {len(source_books)} source books")

        # Insert copies — skip description (too complex for SQL string escaping)
        # Copy only scalar fields that affect the metadata hash
        inserted = 0
        for i, book in enumerate(source_books):
            try:
                title = (book['title'] or 'Unknown').replace("'", "''").replace("\\", "\\\\")
                author = (book['author_sort'] or 'Unknown').replace("'", "''").replace("\\", "\\\\")
                pubdate_val = f"'{book['pubdate']}'" if book['pubdate'] else 'NULL'
                rating_val = str(int(book['rating'])) if book['rating'] is not None else 'NULL'
                si = book['series_index'] if book['series_index'] else 1.0

                result = sql(
                    f"INSERT INTO books (id, uuid, user_id, library_id, title, path, author_sort, "
                    f"series_index, pubdate, rating, has_cover, last_modified, created_at, updated_at) "
                    f"VALUES ({100000+i}, '{book['uuid']}', 1, {lib_id}, '{title}', "
                    f"'path-{i}', '{author}', {si}, "
                    f"{pubdate_val}, {rating_val}, {int(book['has_cover'] or 0)}, NOW(), NOW(), NOW())"
                )
                inserted += 1
            except Exception as e:
                log(f"  WARN: Failed to insert book {i}: {e}")
        log(f"  Inserted {inserted}/{len(source_books)} books")

        copy_ms = int((time.time() - t0) * 1000)
        count = sql(f"SELECT COUNT(*) as c FROM books WHERE user_id = 1 AND library_id = {lib_id} AND deleted_at IS NULL")['rows'][0]['c']
        log(f"  Copied {count} books in {copy_ms}ms")

        # ── Step 3: Get server hashes ────────────────────────────────
        log("\n[3] Fetching server hashes...")
        t0 = time.time()
        hash_rows = sql(
            f"SELECT uuid, metadata_hash FROM books_hash_v2 "
            f"WHERE user_id = 1 AND library_id = {lib_id}"
        )['rows']
        server_hashes = {r['uuid']: r['metadata_hash'] for r in hash_rows}
        hash_ms = int((time.time() - t0) * 1000)
        log(f"  Got {len(server_hashes)} hashes in {hash_ms}ms")

        uuids = list(server_hashes.keys())
        if len(uuids) < NUM_BOOKS * 0.9:
            log(f"  WARNING: Only {len(uuids)} hashes (expected ~{NUM_BOOKS})")

        # ── Step 4: Sync 1 — all hashes match ───────────────────────
        log(f"\n[4] Sync 1: {len(uuids)} books, all correct hashes (expect 0 updates)...")
        client_books = {}
        for u in uuids:
            client_books[u] = {'m': server_hashes[u], 'c': None, 'f': None}

        resp1, ms1 = sync_v5({
            'library_id': str(lib_id),
            'calibre_library_uuid': test_lib_uuid,
            'cursor': None,
            'batch_size': 1000,
            'client_books': {'b': client_books, 'd': []},
            'options': {
                'sync_files_enabled': False,
                'sync_covers_enabled': False,
                'metadata_candidate_uuids': uuids,
            }
        })
        updates1 = len(resp1.get('updates_for_client', []))
        skipped1 = resp1.get('skipped_hash', 0)
        missing1 = len(resp1.get('missing_from_server', []))
        log(f"  Time: {ms1}ms | Updates: {updates1} | Skipped: {skipped1} | Missing: {missing1}")
        assert_eq("Sync1: 0 updates (all match)", 0, updates1)
        assert_eq("Sync1: 0 missing", 0, missing1)
        assert_eq("Sync1: has_more=False", False, resp1.get('has_more', True))

        # ── Step 5: Scramble 10% on server ───────────────────────────
        scramble_count = int(len(uuids) * SCRAMBLE_PCT)
        random.seed(42)  # deterministic for reproducibility
        server_scramble_uuids = random.sample(uuids, scramble_count)
        # Pick different books for client scramble (no overlap)
        remaining = [u for u in uuids if u not in server_scramble_uuids]
        client_scramble_uuids = random.sample(remaining, min(scramble_count, len(remaining)))

        log(f"\n[5] Scrambling {scramble_count} books on SERVER...")
        t0 = time.time()
        for i, u in enumerate(server_scramble_uuids):
            new_title = f"SERVER_SCRAMBLED_{i}_{random.randint(1000,9999)}"
            sql(f"UPDATE books SET title = '{new_title}' WHERE uuid = '{u}' AND user_id = 1 AND library_id = {lib_id}")
        scramble_server_ms = int((time.time() - t0) * 1000)
        log(f"  Scrambled {scramble_count} server books in {scramble_server_ms}ms")

        # ── Step 6: Re-fetch server hashes after scramble ────────────
        log("\n[6] Re-fetching server hashes after scramble...")
        new_hash_rows = sql(
            f"SELECT uuid, metadata_hash FROM books_hash_v2 "
            f"WHERE user_id = 1 AND library_id = {lib_id}"
        )['rows']
        new_server_hashes = {r['uuid']: r['metadata_hash'] for r in new_hash_rows}

        # Verify scrambled books have different hashes
        changed_on_server = 0
        for u in server_scramble_uuids:
            old_h = server_hashes.get(u)
            new_h = new_server_hashes.get(u)
            if old_h != new_h:
                changed_on_server += 1
        log(f"  Server hash changes: {changed_on_server}/{scramble_count}")
        assert_eq(f"Server scramble changed {scramble_count} hashes", scramble_count, changed_on_server)

        # ── Step 7: Sync 2 — client has OLD hashes for server-scrambled books ──
        log(f"\n[7] Sync 2: client sends OLD hashes (expect {scramble_count} updates)...")

        # Client still has the original hashes (pre-scramble)
        # For server-scrambled books: hash mismatch → server sends update
        # For client-scrambled books: we don't actually scramble locally here,
        # we simulate by sending a wrong hash
        client_books2 = {}
        expected_update_uuids = set()
        for u in uuids:
            if u in server_scramble_uuids:
                # Server changed this book — client has OLD hash
                client_books2[u] = {'m': server_hashes[u], 'c': None, 'f': None}
                expected_update_uuids.add(u)
            elif u in client_scramble_uuids:
                # Simulate client-side change: send a fake hash
                client_books2[u] = {'m': hashlib.sha256(f"scrambled-{u}".encode()).hexdigest(), 'c': None, 'f': None}
                expected_update_uuids.add(u)
            else:
                # Unchanged: send correct current hash
                client_books2[u] = {'m': new_server_hashes.get(u, server_hashes.get(u, '0' * 64)), 'c': None, 'f': None}

        resp2, ms2 = sync_v5({
            'library_id': str(lib_id),
            'calibre_library_uuid': test_lib_uuid,
            'cursor': None,
            'batch_size': 1000,
            'client_books': {'b': client_books2, 'd': []},
            'options': {
                'sync_files_enabled': False,
                'sync_covers_enabled': False,
                'metadata_candidate_uuids': uuids,
            }
        })
        updates2 = resp2.get('updates_for_client', [])
        skipped2 = resp2.get('skipped_hash', 0)
        missing2 = resp2.get('missing_from_server', [])
        log(f"  Time: {ms2}ms | Updates: {len(updates2)} | Skipped: {skipped2} | Missing: {len(missing2)}")

        expected_total = len(expected_update_uuids)
        assert_eq(f"Sync2: {expected_total} updates (scrambled)", expected_total, len(updates2))
        assert_eq("Sync2: has_more=False", False, resp2.get('has_more', True))

        # Verify scrambled server books have new titles
        update_map = {u['uuid']: u for u in updates2}
        server_title_correct = 0
        for u in server_scramble_uuids:
            upd = update_map.get(u)
            if upd and upd.get('title', '').startswith('SERVER_SCRAMBLED_'):
                server_title_correct += 1
        log(f"  Server-scrambled titles correct: {server_title_correct}/{scramble_count}")
        assert_eq("Server-scrambled titles propagated", scramble_count, server_title_correct)

        # Verify client-scrambled books also come back (hash mismatch → server sends its version)
        client_scramble_in_updates = sum(1 for u in client_scramble_uuids if u in update_map)
        log(f"  Client-scrambled books in updates: {client_scramble_in_updates}/{len(client_scramble_uuids)}")
        assert_eq("Client-scrambled books returned as updates", len(client_scramble_uuids), client_scramble_in_updates)

        # ── Step 8: Sync 3 — use NEW hashes → all match ─────────────
        log(f"\n[8] Sync 3: use response hashes (expect 0 updates)...")
        client_books3 = {}
        for u in uuids:
            upd = update_map.get(u)
            if upd and upd.get('metadata_hash'):
                client_books3[u] = {'m': upd['metadata_hash'], 'c': None, 'f': None}
            else:
                client_books3[u] = {'m': new_server_hashes.get(u, '0' * 64), 'c': None, 'f': None}

        resp3, ms3 = sync_v5({
            'library_id': str(lib_id),
            'calibre_library_uuid': test_lib_uuid,
            'cursor': None,
            'batch_size': 1000,
            'client_books': {'b': client_books3, 'd': []},
            'options': {
                'sync_files_enabled': False,
                'sync_covers_enabled': False,
                'metadata_candidate_uuids': uuids,
            }
        })
        updates3 = len(resp3.get('updates_for_client', []))
        skipped3 = resp3.get('skipped_hash', 0)
        log(f"  Time: {ms3}ms | Updates: {updates3} | Skipped: {skipped3}")
        assert_eq("Sync3: 0 updates (all aligned)", 0, updates3)

        # ── Step 9: Timing analysis ──────────────────────────────────
        log("\n[9] Timing analysis:")
        log(f"  Sync 1 (all match, {len(uuids)} books):     {ms1}ms")
        log(f"  Sync 2 ({expected_total} mismatch):            {ms2}ms")
        log(f"  Sync 3 (all match after align):  {ms3}ms")
        log(f"  Server scramble ({scramble_count} books):    {scramble_server_ms}ms")

        speedup = ms2 / ms3 if ms3 > 0 else 0
        log(f"  Speedup match vs mismatch:       {speedup:.1f}x")

    except Exception as e:
        log(f"\nFATAL ERROR: {e}")
        import traceback
        traceback.print_exc()
        global FAIL
        FAIL += 1
    finally:
        cleanup(lib_id)

    # ── Summary ──────────────────────────────────────────────────────
    log("\n" + "=" * 70)
    log(f"RESULTS: {PASS} passed, {FAIL} failed")
    log("=" * 70)

    # Save log
    log_path = os.path.join(os.path.dirname(__file__), 'e2e_scramble_sync_test.log')
    with open(log_path, 'w') as f:
        f.write('\n'.join(LOG_LINES))
    print(f"\nLog saved to: {log_path}")

    sys.exit(1 if FAIL > 0 else 0)


if __name__ == '__main__':
    main()
