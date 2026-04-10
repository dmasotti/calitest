#!/usr/bin/env python3
"""
E2E large scramble test using REAL sync client.

Flow:
  1. Copy 5000 books from fixture into a temporary metadata.db
  2. Scramble all titles (make them unique to this test run)
  3. Sync 1: full push to server (creates everything)
  4. Verify server has all books
  5. Scramble 10% titles locally
  6. Sync 2: detect mismatches, push local changes
  7. Sync 3: convergence — 0 updates expected

Uses calibre-debug + sync_worker.py (real client code).

Usage:
  # First bootstrap the integration environment:
  eval "$(./scripts/init_menu39_local.sh)"
  # Then run:
  python3 tests/plugin/v5/e2e_large_scramble_real.py
"""
from __future__ import annotations

import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

# ── Config ──
FIXTURE_DB = os.path.join(
    os.path.dirname(__file__), '..', '..', '..', 'tests', 'plugin', 'fixtures', 'CalibreLargeLocal', 'metadata.db'
)
NUM_BOOKS = int(os.getenv('E2E_NUM_BOOKS', '5000'))
SCRAMBLE_PCT = float(os.getenv('E2E_SCRAMBLE_PCT', '0.10'))
CALIBRE_DEBUG = os.getenv('CALIBRE_DEBUG', '/Applications/calibre.app/Contents/MacOS/calibre-debug')
PLUGIN_DIR = os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sync_calimob')
API_URL = os.getenv('CALIMOB_TEST_API_URL', 'http://caliserver-integration.test/api')
TOKEN = os.getenv('CALIMOB_TEST_TOKEN', '')
SYNC_TIMEOUT = int(os.getenv('E2E_SYNC_TIMEOUT', '600'))

# ── Helpers ──
PASS = FAIL = 0
LOG_LINES = []


def log(msg):
    ts = time.strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG_LINES.append(line)


def check(label, expected, actual):
    global PASS, FAIL
    if expected == actual:
        log(f"  OK {label}")
        PASS += 1
    else:
        log(f"  FAIL {label} — expected {expected!r}, got {actual!r}")
        FAIL += 1


def check_gt(label, minimum, actual):
    global PASS, FAIL
    if actual > minimum:
        log(f"  OK {label} ({actual} > {minimum})")
        PASS += 1
    else:
        log(f"  FAIL {label} — {actual} <= {minimum}")
        FAIL += 1


def run_sync(library_path, library_uuid, calimob_lib_id, clear_cache=False):
    """Run real sync via sync_runner."""
    sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
    from sync_runner import run_sync_v5
    start = time.time()
    results, output = run_sync_v5(
        library_path=library_path,
        library_uuid=library_uuid,
        calimob_lib_id=calimob_lib_id,
        plugin_dir=os.path.abspath(PLUGIN_DIR),
        calibre_debug_path=CALIBRE_DEBUG,
        clear_cache=clear_cache,
        in_process=False,
        debug_show_stderr=True,
        timeout=SYNC_TIMEOUT,
    )
    elapsed = int((time.time() - start) * 1000)
    return results, elapsed, output


def sql_api(query):
    """Query server via /api/tools/sql."""
    r = subprocess.run([
        'curl', '-s', '-m', '30',
        '-H', f'Authorization: Bearer {TOKEN}',
        '-H', 'Accept: application/json',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps({'q': query}),
        f'{API_URL.rstrip("/")}/tools/sql'
    ], capture_output=True, text=True, timeout=45)
    try:
        return json.loads(r.stdout)
    except Exception:
        return {'rows': [], 'error': r.stdout[:300]}


def main():
    if not TOKEN:
        log("ERROR: CALIMOB_TEST_TOKEN not set. Run: eval \"$(./scripts/init_menu39_local.sh)\"")
        sys.exit(1)
    if not os.path.isfile(FIXTURE_DB):
        log(f"ERROR: Fixture not found: {FIXTURE_DB}")
        sys.exit(1)

    log("=" * 70)
    log(f"E2E LARGE SCRAMBLE — REAL CLIENT")
    log(f"Books: {NUM_BOOKS} | Scramble: {int(SCRAMBLE_PCT * 100)}%")
    log(f"Server: {API_URL}")
    log("=" * 70)

    # ── Step 1: Create temporary library ──
    log("\n[1] Creating temporary library from fixture...")
    tmp_dir = tempfile.mkdtemp(prefix='e2e_large_scramble_')
    tmp_db = os.path.join(tmp_dir, 'metadata.db')
    shutil.copy2(FIXTURE_DB, tmp_db)

    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row

    # Count available books
    total = conn.execute("SELECT COUNT(*) FROM books WHERE uuid IS NOT NULL").fetchone()[0]
    log(f"  Fixture has {total} books")

    # Keep only NUM_BOOKS (delete the rest)
    if total > NUM_BOOKS:
        conn.execute(f"""
            DELETE FROM books WHERE id NOT IN (
                SELECT id FROM books WHERE uuid IS NOT NULL ORDER BY id LIMIT {NUM_BOOKS}
            )
        """)
        conn.commit()
        remaining = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
        log(f"  Trimmed to {remaining} books")

    # Generate unique library UUID to avoid colliding with production
    import uuid as uuid_mod
    library_uuid = str(uuid_mod.uuid4())
    conn.execute("UPDATE library_id SET uuid = ?", (library_uuid,))
    conn.commit()
    log(f"  Library UUID: {library_uuid} (unique for this test run)")

    # ── Step 2: Scramble ALL titles (make unique) ──
    log("\n[2] Scrambling all titles...")
    random.seed(int(time.time()))
    run_id = random.randint(10000, 99999)
    # Calibre triggers call title_sort() which doesn't exist outside Calibre.
    # Drop the trigger on our temp copy, scramble, then we don't need it.
    conn.execute("DROP TRIGGER IF EXISTS books_update_trg")
    conn.execute("DROP TRIGGER IF EXISTS books_insert_trg")
    books = conn.execute("SELECT id, title FROM books").fetchall()
    for book in books:
        new_title = f"E2E_{run_id}_book{book['id']}_{(book['title'] or 'unknown')[:30]}"
        conn.execute("UPDATE books SET title = ?, sort = ? WHERE id = ?", (new_title, new_title, book['id']))
    conn.commit()
    log(f"  Scrambled {len(books)} titles (prefix E2E_{run_id}_)")

    conn.close()

    # ── Step 3: Register library on server ──
    log("\n[3] Registering library on server...")
    # The library must be owned by the SAME user as the API token, not the
    # first user in the table (which on multi-user dev DBs is a stale bench
    # user that doesn't own the API token). Resolve the token user via the
    # bootstrap-created library (CALIMOB_TEST_CALIMOB_LIB_ID).
    bootstrap_lib_id = os.getenv('CALIMOB_TEST_CALIMOB_LIB_ID', '')
    token_user_id = None
    if bootstrap_lib_id:
        token_user_rows = sql_api(
            f"SELECT user_id FROM libraries WHERE id = {int(bootstrap_lib_id)} LIMIT 1"
        ).get('rows', [])
        if token_user_rows:
            token_user_id = int(token_user_rows[0]['user_id'])
    if token_user_id is None:
        log("  FATAL: cannot resolve token user via CALIMOB_TEST_CALIMOB_LIB_ID")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.exit(1)
    log(f"  Token user_id={token_user_id}")

    lib_rows = sql_api(
        f"SELECT id FROM libraries WHERE calibre_library_id = '{library_uuid}' AND user_id = {token_user_id}"
    ).get('rows', [])
    if lib_rows:
        calimob_lib_id = lib_rows[0]['id']
        log(f"  Existing library: {calimob_lib_id}")
        # Clear existing books for clean test
        sql_api(f"UPDATE books SET deleted_at = NOW() WHERE library_id = {calimob_lib_id}")
        log("  Soft-deleted existing books")
    else:
        sql_api(
            f"INSERT INTO libraries (calibre_library_id, user_id, name, created_at, updated_at) "
            f"VALUES ('{library_uuid}', {token_user_id}, 'E2E Large Scramble', NOW(), NOW())"
        )
        lib_rows = sql_api(
            f"SELECT id FROM libraries WHERE calibre_library_id = '{library_uuid}' AND user_id = {token_user_id}"
        ).get('rows', [])
        calimob_lib_id = lib_rows[0]['id']
        log(f"  Created library: {calimob_lib_id}")

    # ── Step 4: Sync 1 — full push ──
    log(f"\n[4] Sync 1: full push ({NUM_BOOKS} books)...")
    r1, ms1, out1 = run_sync(tmp_dir, library_uuid, calimob_lib_id, clear_cache=True)
    if r1 is None:
        log(f"  FATAL: sync failed. Output:\n{out1[-2000:]}")
        shutil.rmtree(tmp_dir, ignore_errors=True)
        sys.exit(1)
    log(f"  {ms1}ms | created={r1.get('created',0)} updated={r1.get('updated',0)} "
        f"skipped_hash={r1.get('skipped_hash',0)} errors={r1.get('errors',0)}")
    check_gt("Sync1: created > 0", 0, r1.get('created', 0))
    check("Sync1: 0 errors", 0, r1.get('errors', 0))

    # Verify server count
    srv_count = sql_api(
        f"SELECT COUNT(*) as c FROM books WHERE library_id = {calimob_lib_id} AND deleted_at IS NULL"
    ).get('rows', [{}])[0].get('c', 0)
    log(f"  Server has {srv_count} books")
    check(f"Server has {NUM_BOOKS} books", NUM_BOOKS, srv_count)

    # ── Step 5: Sync 2 — re-sync should be no-op ──
    log(f"\n[5] Sync 2: re-sync (expect ~0 updates)...")
    r2, ms2, _ = run_sync(tmp_dir, library_uuid, calimob_lib_id, clear_cache=False)
    log(f"  {ms2}ms | created={r2.get('created',0)} updated={r2.get('updated',0)} "
        f"skipped_hash={r2.get('skipped_hash',0)}")
    check("Sync2: 0 created", 0, r2.get('created', 0))
    check("Sync2: 0 errors", 0, r2.get('errors', 0))

    # ── Step 6: Scramble 10% locally ──
    scramble_n = int(NUM_BOOKS * SCRAMBLE_PCT)
    log(f"\n[6] Scrambling {scramble_n} books locally...")
    conn = sqlite3.connect(tmp_db)
    conn.row_factory = sqlite3.Row
    conn.execute("DROP TRIGGER IF EXISTS books_update_trg")
    conn.execute("DROP TRIGGER IF EXISTS books_insert_trg")
    all_ids = [r[0] for r in conn.execute("SELECT id FROM books ORDER BY id").fetchall()]
    random.seed(42)
    scramble_ids = random.sample(all_ids, scramble_n)
    for book_id in scramble_ids:
        new_title = f"LOCAL_SCRAMBLED_{book_id}_{random.randint(10000, 99999)}"
        conn.execute("UPDATE books SET title = ?, sort = ? WHERE id = ?", (new_title, new_title, book_id))
    conn.commit()
    conn.close()
    log(f"  Scrambled {scramble_n} titles locally")

    # ── Step 7: Sync 3 — push local changes ──
    log(f"\n[7] Sync 3: push {scramble_n} local changes...")
    r3, ms3, _ = run_sync(tmp_dir, library_uuid, calimob_lib_id, clear_cache=False)
    log(f"  {ms3}ms | created={r3.get('created',0)} updated={r3.get('updated',0)} "
        f"skipped_hash={r3.get('skipped_hash',0)} errors={r3.get('errors',0)}")
    check("Sync3: 0 errors", 0, r3.get('errors', 0))
    # updated should be ~scramble_n (client pushes changed books)
    check_gt(f"Sync3: updated > 0", 0, r3.get('updated', 0) + r3.get('created', 0))

    # ── Step 8: Sync 4 — convergence ──
    log(f"\n[8] Sync 4: convergence (expect 0 updates)...")
    r4, ms4, _ = run_sync(tmp_dir, library_uuid, calimob_lib_id, clear_cache=False)
    log(f"  {ms4}ms | created={r4.get('created',0)} updated={r4.get('updated',0)} "
        f"skipped_hash={r4.get('skipped_hash',0)} errors={r4.get('errors',0)}")
    check("Sync4: 0 created", 0, r4.get('created', 0))
    check("Sync4: 0 updated", 0, r4.get('updated', 0))
    check("Sync4: 0 errors", 0, r4.get('errors', 0))

    # ── Summary ──
    log("\n" + "=" * 70)
    log("TIMING:")
    log(f"  Sync 1 (full push {NUM_BOOKS}):  {ms1}ms")
    log(f"  Sync 2 (no-op):                  {ms2}ms")
    log(f"  Sync 3 ({scramble_n} changes):   {ms3}ms")
    log(f"  Sync 4 (convergence):            {ms4}ms")
    log(f"\nRESULTS: {PASS} passed, {FAIL} failed")
    log("=" * 70)

    # ── Cleanup ──
    shutil.rmtree(tmp_dir, ignore_errors=True)
    # Cleanup server library (skipped if E2E_KEEP_LIBRARY=1 — useful for post-mortem inspection)
    if calimob_lib_id and not os.getenv('E2E_KEEP_LIBRARY'):
        log(f"Cleaning up server library {calimob_lib_id}...")
        sql_api(f"DELETE FROM books WHERE library_id = {calimob_lib_id}")
        sql_api(f"DELETE FROM libraries WHERE id = {calimob_lib_id}")
    elif calimob_lib_id:
        log(f"E2E_KEEP_LIBRARY=1 → leaving server library {calimob_lib_id} intact for post-mortem")

    # Save log
    log_path = os.path.join(os.path.dirname(__file__), 'e2e_large_scramble_real.log')
    with open(log_path, 'w') as f:
        f.write('\n'.join(LOG_LINES))
    log(f"Log saved to: {log_path}")

    sys.exit(1 if FAIL > 0 else 0)


if __name__ == '__main__':
    main()
