#!/usr/bin/env python3
"""
E2E real sync test against production using calibre-debug.

1. Copy CalibreLargeLocal fixture to temp dir
2. Keep 500 random books, delete the rest, scramble metadata
3. Create empty library on production
4. Run sync_v5 via calibre-debug — first sync (upload all 500)
5. Log timing
6. Scramble 10% on server, 10% locally
7. Run sync_v5 again — verify changes propagate
8. Cleanup

Usage:
  python3 tests/server/e2e_real_sync_production.py
"""

import json
import os
import random
import shutil
import sqlite3
import subprocess
import sys
import tempfile
import time

BASE_URL = "https://coral-shark-984693.hostingersite.com"
TOKEN = "44|jHjh0i1wsHYoPpSz2m7gRoUmWhtd7E2K5SiN1MEt984e5f11"
FIXTURE = os.path.join(os.path.dirname(__file__), '..', 'plugin', 'fixtures', 'CalibreLargeLocal', 'metadata.db')
NUM_BOOKS = 500
SCRAMBLE_PCT = 0.10
CALIBRE_DEBUG = '/Applications/calibre.app/Contents/MacOS/calibre-debug'

LOG = []


def log(msg):
    ts = time.strftime('%H:%M:%S')
    line = f"[{ts}] {msg}"
    print(line, flush=True)
    LOG.append(line)


def sql_prod(query):
    r = subprocess.run([
        'curl', '-s',
        '-H', f'Authorization: Bearer {TOKEN}',
        '-H', 'Accept: application/json',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps({'q': query}),
        f'{BASE_URL}/api/tools/sql'
    ], capture_output=True, text=True, timeout=60)
    try:
        data = json.loads(r.stdout)
        if data.get('status') == 'error':
            log(f"  SQL ERROR: {data.get('message', '?')[:200]}")
        return data.get('rows', [])
    except Exception:
        return []


def prepare_test_library(tmp_dir):
    """Copy fixture, keep 500 random books, scramble metadata."""
    log("  Copying fixture...")
    db_path = os.path.join(tmp_dir, 'metadata.db')
    shutil.copy2(FIXTURE, db_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row

    # Get all book IDs and keep 500 random
    all_ids = [r[0] for r in conn.execute("SELECT id FROM books").fetchall()]
    random.seed(42)
    keep_ids = set(random.sample(all_ids, min(NUM_BOOKS, len(all_ids))))
    delete_ids = [i for i in all_ids if i not in keep_ids]

    log(f"  Keeping {len(keep_ids)} books, deleting {len(delete_ids)}...")

    # Delete non-selected books and their relations
    for chunk_start in range(0, len(delete_ids), 500):
        chunk = delete_ids[chunk_start:chunk_start + 500]
        placeholders = ','.join(['?'] * len(chunk))
        conn.execute(f"DELETE FROM books_authors_link WHERE book IN ({placeholders})", chunk)
        conn.execute(f"DELETE FROM books_tags_link WHERE book IN ({placeholders})", chunk)
        conn.execute(f"DELETE FROM books_series_link WHERE book IN ({placeholders})", chunk)
        conn.execute(f"DELETE FROM books_publishers_link WHERE book IN ({placeholders})", chunk)
        conn.execute(f"DELETE FROM books_languages_link WHERE book IN ({placeholders})", chunk)
        conn.execute(f"DELETE FROM identifiers WHERE book IN ({placeholders})", chunk)
        conn.execute(f"DELETE FROM comments WHERE book IN ({placeholders})", chunk)
        conn.execute(f"DELETE FROM books_ratings_link WHERE book IN ({placeholders})", chunk)
        conn.execute(f"DELETE FROM books WHERE id IN ({placeholders})", chunk)
    conn.execute("DELETE FROM authors WHERE id NOT IN (SELECT DISTINCT author FROM books_authors_link)")
    conn.execute("DELETE FROM tags WHERE id NOT IN (SELECT DISTINCT tag FROM books_tags_link)")
    conn.commit()

    remaining = conn.execute("SELECT COUNT(*) FROM books").fetchone()[0]
    log(f"  Remaining books: {remaining}")

    # Drop Calibre triggers that call title_sort() UDF (not available outside Calibre)
    for trigger in ['books_insert_trg', 'books_update_trg']:
        conn.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    conn.commit()

    # Scramble: swap author_sort between random pairs
    books = conn.execute("SELECT id, author_sort FROM books ORDER BY id").fetchall()
    scramble_count = len(books) // 5  # 20% scrambled
    pairs = random.sample(range(len(books)), scramble_count * 2)
    for i in range(0, len(pairs) - 1, 2):
        a, b = books[pairs[i]], books[pairs[i + 1]]
        conn.execute("UPDATE books SET author_sort = ? WHERE id = ?", (a['author_sort'], b['id']))
        conn.execute("UPDATE books SET author_sort = ? WHERE id = ?", (b['author_sort'], a['id']))
    conn.commit()
    log(f"  Scrambled {scramble_count} author_sort pairs")

    # Generate a unique library UUID for this test
    import uuid
    lib_uuid = str(uuid.uuid4())

    # Clean up any calimob tables/views (fresh sync)
    for table in ['calimob_books_sync', 'calimob_books_hash_v2', 'calimob_books_hash_v2_base',
                   'calimob_books_hash_v2_payload', 'calimob_library_hash_payload',
                   'calimob_merkle_leaves_v1', 'calimob_merkle_branches_v1', 'calimob_merkle_root_v1']:
        try:
            conn.execute(f"DROP VIEW IF EXISTS {table}")
        except sqlite3.OperationalError:
            pass
        try:
            conn.execute(f"DROP TABLE IF EXISTS {table}")
        except sqlite3.OperationalError:
            pass
    conn.commit()

    conn.close()
    return db_path, lib_uuid, remaining


def create_prod_library(lib_uuid):
    """Create library via REST API."""
    r = subprocess.run([
        'curl', '-s', '-w', '\n__HTTP__%{http_code}',
        '-H', f'Authorization: Bearer {TOKEN}',
        '-H', 'Accept: application/json',
        '-H', 'Content-Type: application/json',
        '-d', json.dumps({'name': 'E2E Real Sync Test', 'calibre_library_uuid': lib_uuid, 'type': 'calibre'}),
        f'{BASE_URL}/api/libraries'
    ], capture_output=True, text=True, timeout=30)
    lines = r.stdout.strip().split('\n')
    http_line = [l for l in lines if l.startswith('__HTTP__')]
    code = int(http_line[0].replace('__HTTP__', '')) if http_line else 0
    body_text = '\n'.join(l for l in lines if not l.startswith('__HTTP__'))
    try:
        data = json.loads(body_text) if body_text else {}
    except json.JSONDecodeError:
        data = {}
    if code in (200, 201):
        lib_id = data.get('id') or (data.get('library') or {}).get('id')
        if lib_id:
            return lib_id
    log(f"  Create library API: HTTP {code} — {json.dumps(data)[:200]}")
    # Fallback
    rows = sql_prod(f"SELECT id FROM libraries WHERE calibre_library_id = '{lib_uuid}' AND user_id = 1")
    return rows[0]['id'] if rows else None


def write_sync_script(script_path, lib_path, lib_uuid, calimob_lib_id):
    """Write a calibre-debug script that runs sync_v5."""
    with open(script_path, 'w') as f:
        f.write(f"""#!/usr/bin/env python
import sys, os, time, json
sys.path.insert(0, '{os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..', 'sync_calimob'))}')

# Patch config to point to test library
os.environ['CALIMOB_PLUGIN_COMMIT'] = 'e2e-test'

from sync_worker import SyncWorker
from calibre.library import db

library_path = '{lib_path}'
library_uuid = '{lib_uuid}'
calimob_library_id = '{calimob_lib_id}'

print("=" * 60)
print("E2E Sync: library_uuid=%s calimob_id=%s" % (library_uuid, calimob_library_id))
print("Library path: %s" % library_path)
print("=" * 60)

database = db(library_path)
worker = SyncWorker(None, database, library_uuid, calimob_library_id)

start = time.time()
summary = worker.sync_v5(metadata_only=True)
elapsed = time.time() - start

print()
print("=" * 60)
print("SYNC SUMMARY (%.1fs)" % elapsed)
for k, v in sorted(summary.items()):
    if k != 'errors' or v:
        print("  %s: %s" % (k, v))
if summary.get('errors'):
    print("  ERRORS:")
    for e in summary['errors']:
        print("    %s" % e)
print("=" * 60)

# Save summary as JSON for the test script to read
with open('{script_path}.result.json', 'w') as f:
    json.dump({{'summary': summary, 'elapsed_s': elapsed}}, f, indent=2, default=str)
""")


def run_sync(script_path):
    """Run sync via calibre-debug and return summary."""
    log("  Running calibre-debug...")
    start = time.time()
    r = subprocess.run(
        [CALIBRE_DEBUG, '-e', script_path],
        capture_output=True, text=True, timeout=600
    )
    elapsed = int((time.time() - start) * 1000)

    # Print stdout/stderr for debugging
    for line in r.stdout.strip().split('\n')[-20:]:
        log(f"  [calibre] {line}")
    # Always log stderr (contains debug prints from sync)
    if r.stderr:
        stderr_lines = r.stderr.strip().split('\n')
        important = [l for l in stderr_lines if 'CALIMOB' in l or 'ERROR' in l or 'Fast path' in l
                     or 'Merkle' in l or 'missing' in l.lower() or 'candidates' in l.lower()]
        for line in important[-30:]:
            log(f"  [stderr] {line[:200]}")
        if not important and r.returncode != 0:
            for line in stderr_lines[-10:]:
                log(f"  [stderr] {line[:200]}")

    # Read result JSON
    result_path = script_path + '.result.json'
    if os.path.exists(result_path):
        with open(result_path) as f:
            return json.load(f), elapsed
    return None, elapsed


def cleanup_prod(lib_id, lib_uuid):
    if lib_uuid:
        log("[CLEANUP] Removing production test library via API...")
        r = subprocess.run([
            'curl', '-s', '-w', '\n__HTTP__%{http_code}', '-X', 'DELETE',
            '-H', f'Authorization: Bearer {TOKEN}',
            '-H', 'Accept: application/json',
            f'{BASE_URL}/api/libraries/uuid/{lib_uuid}'
        ], capture_output=True, text=True, timeout=30)
        lines = r.stdout.strip().split('\n')
        http_line = [l for l in lines if l.startswith('__HTTP__')]
        code = int(http_line[0].replace('__HTTP__', '')) if http_line else 0
        log(f"  DELETE library: HTTP {code}")
        if code != 200 and lib_id:
            log("  Fallback: SQL cleanup...")
            for table in ['books_authors_link', 'books_tags_link', 'books_series_link',
                           'books_publishers_link', 'books_languages_link', 'books_identifiers',
                           'books_ratings_links']:
                sql_prod(f"DELETE FROM {table} WHERE user_id = 1 AND library_id = {lib_id}")
            sql_prod(f"DELETE FROM books WHERE user_id = 1 AND library_id = {lib_id}")
            sql_prod(f"DELETE FROM libraries WHERE id = {lib_id}")
        log("[CLEANUP] Done")


def main():
    lib_id = None
    lib_uuid = None
    result1 = result2 = result3 = result4 = None
    tmp_dir = tempfile.mkdtemp(prefix='e2e_sync_')

    log("=" * 70)
    log("E2E REAL SYNC PRODUCTION TEST (via calibre-debug)")
    log(f"Fixture: {FIXTURE}")
    log(f"Books: {NUM_BOOKS}, Scramble: {int(SCRAMBLE_PCT*100)}%")
    log(f"Temp dir: {tmp_dir}")
    log("=" * 70)

    try:
        # ── Step 1: Prepare local test library ───────────────────────
        log("\n[1] Preparing local test library...")
        t0 = time.time()
        db_path, lib_uuid, book_count = prepare_test_library(tmp_dir)
        log(f"  Done in {int((time.time()-t0)*1000)}ms")
        log(f"  UUID: {lib_uuid}, Books: {book_count}")

        # ── Step 2: Create empty library on production ───────────────
        log("\n[2] Creating production library...")
        lib_id = create_prod_library(lib_uuid)
        if not lib_id:
            log("  FATAL: Could not create library")
            return
        log(f"  Library ID: {lib_id}")

        # ── Step 3: First sync — upload all books ────────────────────
        log(f"\n[3] First sync: {book_count} books → production (expect uploads)...")
        script1 = os.path.join(tmp_dir, 'sync1.py')
        write_sync_script(script1, os.path.dirname(db_path), lib_uuid, str(lib_id))
        result1, ms1 = run_sync(script1)
        if result1:
            s = result1['summary']
            log(f"  Elapsed: {result1['elapsed_s']:.1f}s")
            log(f"  books_synced: {s.get('books_synced', 0)}")
            log(f"  books_missing_from_server: {s.get('books_missing_from_server', 0)}")
            log(f"  books_from_server: {s.get('books_from_server', 0)}")
            log(f"  books_skipped_hash: {s.get('books_skipped_hash', 0)}")
            log(f"  fast_path_used: {s.get('fast_path_used', False)}")
            log(f"  errors: {len(s.get('errors', []))}")
        else:
            log("  WARNING: No result JSON (calibre-debug may have failed)")

        # Check server state
        server_count = sql_prod(f"SELECT COUNT(*) as c FROM books WHERE user_id = 1 AND library_id = {lib_id} AND deleted_at IS NULL")
        sc = server_count[0]['c'] if server_count else 0
        log(f"  Server books after sync: {sc}")

        # ── Step 4: Second sync — should converge ────────────────────
        log(f"\n[4] Second sync: expect convergence (0 updates)...")
        script2 = os.path.join(tmp_dir, 'sync2.py')
        write_sync_script(script2, os.path.dirname(db_path), lib_uuid, str(lib_id))
        result2, ms2 = run_sync(script2)
        if result2:
            s = result2['summary']
            log(f"  Elapsed: {result2['elapsed_s']:.1f}s")
            log(f"  books_from_server: {s.get('books_from_server', 0)}")
            log(f"  books_skipped_hash: {s.get('books_skipped_hash', 0)}")
            log(f"  fast_path_used: {s.get('fast_path_used', False)}")

        # ── Step 5: Scramble on server ───────────────────────────────
        scramble_n = int(book_count * SCRAMBLE_PCT)
        log(f"\n[5] Scrambling {scramble_n} books on production server...")
        server_uuids = [r['uuid'] for r in sql_prod(
            f"SELECT uuid FROM books WHERE user_id = 1 AND library_id = {lib_id} AND deleted_at IS NULL"
        )]
        random.seed(99)
        server_scramble = random.sample(server_uuids, min(scramble_n, len(server_uuids)))
        for i, u in enumerate(server_scramble):
            sql_prod(f"UPDATE books SET title = 'SERVER_MODIFIED_{i}' WHERE uuid = '{u}' AND user_id = 1 AND library_id = {lib_id}")
        log(f"  Scrambled {len(server_scramble)} server books")

        # ── Step 6: Scramble locally ─────────────────────────────────
        log(f"\n[6] Scrambling {scramble_n} books locally (author_sort)...")
        local_conn = sqlite3.connect(db_path)
        local_ids = [r[0] for r in local_conn.execute("SELECT id FROM books ORDER BY RANDOM() LIMIT ?", (scramble_n,)).fetchall()]
        for i, bid in enumerate(local_ids):
            local_conn.execute("UPDATE books SET author_sort = ? WHERE id = ?", (f"Local Modified Author {i}", bid))
        local_conn.commit()
        local_conn.close()
        log(f"  Scrambled {len(local_ids)} local books")

        # ── Step 7: Third sync — detect changes ─────────────────────
        log(f"\n[7] Third sync: detect server + local changes...")
        script3 = os.path.join(tmp_dir, 'sync3.py')
        write_sync_script(script3, os.path.dirname(db_path), lib_uuid, str(lib_id))
        result3, ms3 = run_sync(script3)
        if result3:
            s = result3['summary']
            log(f"  Elapsed: {result3['elapsed_s']:.1f}s")
            log(f"  books_from_server: {s.get('books_from_server', 0)}")
            log(f"  books_missing_from_server: {s.get('books_missing_from_server', 0)}")
            log(f"  books_skipped_hash: {s.get('books_skipped_hash', 0)}")

        # ── Step 8: Fourth sync — should converge ────────────────────
        log(f"\n[8] Fourth sync: expect convergence...")
        script4 = os.path.join(tmp_dir, 'sync4.py')
        write_sync_script(script4, os.path.dirname(db_path), lib_uuid, str(lib_id))
        result4, ms4 = run_sync(script4)
        if result4:
            s = result4['summary']
            log(f"  Elapsed: {result4['elapsed_s']:.1f}s")
            log(f"  books_from_server: {s.get('books_from_server', 0)}")
            log(f"  books_skipped_hash: {s.get('books_skipped_hash', 0)}")
            log(f"  fast_path_used: {s.get('fast_path_used', False)}")

    except Exception as e:
        log(f"\nFATAL: {e}")
        import traceback; traceback.print_exc()
    finally:
        cleanup_prod(lib_id, lib_uuid)
        # Keep tmp_dir for debugging
        log(f"\nTemp dir preserved: {tmp_dir}")

    log("\n" + "=" * 70)
    log("TIMING SUMMARY")
    for name, var in [('Sync 1 (first upload)', 'result1'), ('Sync 2 (convergence)', 'result2'),
                       ('Sync 3 (scrambled)', 'result3'), ('Sync 4 (re-converge)', 'result4')]:
        r = locals().get(var)
        if r:
            log(f"  {name}: {r['elapsed_s']:.1f}s")
    log("=" * 70)

    log_path = os.path.join(os.path.dirname(__file__), 'e2e_real_sync_production.log')
    with open(log_path, 'w') as f:
        f.write('\n'.join(LOG))
    print(f"\nLog saved to: {log_path}")


if __name__ == '__main__':
    main()
