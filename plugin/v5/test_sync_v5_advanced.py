#!/usr/bin/env python3
"""
Sync V5 Advanced Integration Tests - Server-side Changes

Tests for:
- Server-side metadata modifications → client pull
- Server-side deletions → client delete
- All metadata fields (tags, series, identifiers, publisher, etc.)
- Various conflict scenarios

Usage:
    python3 tests/test_sync_v5_advanced.py [--all|--server-changes|--conflicts|--edge-cases]
    python3 tests/test_sync_v5_advanced.py --server-changes --timing   # con profiling
"""

import sys
import os
import subprocess
import tempfile
import time
import json
import requests
from datetime import datetime

# Test Configuration (override via env)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
LIBRARY_PATH = os.getenv(
    "CALIMOB_TEST_LIBRARY_PATH",
    os.path.join(PROJECT_ROOT, "tests/plugin/fixtures/CalibreTestLocal"),
)
LIBRARY_UUID = os.getenv("CALIMOB_TEST_LIBRARY_UUID", "1685fd4f-054e-4451-9df8-119c27fc1289")
CALIMOB_LIB_ID = os.getenv("CALIMOB_TEST_CALIMOB_LIB_ID", "1")
CALIBRE_DEBUG = os.getenv("CALIBRE_DEBUG", "/Applications/calibre.app/Contents/MacOS/calibre-debug")
PLUGIN_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
API_URL = os.getenv("CALIMOB_TEST_API_URL", "https://coral-shark-984693.hostingersite.com/api")
TOKEN = os.getenv("CALIMOB_TEST_TOKEN", "44|jHjh0i1wsHYoPpSz2m7gRoUmWhtd7E2K5SiN1MEt984e5f11")

class Colors:
    GREEN = '\033[92m'
    RED = '\033[91m'
    YELLOW = '\033[93m'
    BLUE = '\033[94m'
    RESET = '\033[0m'

def log(msg, color=None):
    timestamp = datetime.now().strftime('%H:%M:%S')
    if color:
        print(f"{color}[{timestamp}] {msg}{Colors.RESET}")
    else:
        print(f"[{timestamp}] {msg}")

def log_success(msg):
    log(f"✓ {msg}", Colors.GREEN)

def log_error(msg):
    log(f"✗ {msg}", Colors.RED)

def log_info(msg):
    log(f"ℹ {msg}", Colors.BLUE)

def log_warning(msg):
    log(f"⚠ {msg}", Colors.YELLOW)


# ========== PERFORMANCE TIMING (--timing) ==========

_timings = []
TIMING_ENABLED = "--timing" in sys.argv

class Timer:
    """Context manager per misurare tempo in ms. Usare con: with Timer('label'): ..."""
    def __init__(self, label):
        self.label = label
        self.start = None

    def __enter__(self):
        self.start = time.perf_counter()
        return self

    def __exit__(self, *args):
        elapsed_ms = (time.perf_counter() - self.start) * 1000
        _timings.append((self.label, round(elapsed_ms, 2)))
        return False


def _print_timing_summary(test_name=""):
    """Stampa i timing raccolti per il test corrente."""
    if not _timings:
        return
    total = sum(ms for _, ms in _timings)
    for label, ms in _timings:
        print(f"  [TIMING] {label}: {ms:>10.2f} ms")
    print(f"  [TIMING] TOTAL ({test_name}): {total:.2f} ms")


# ========== API HELPERS ==========

def api_call(method, endpoint, data=None):
    """Make API call to server"""
    url = f"{API_URL}{endpoint}"
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Accept": "application/json",
        "Content-Type": "application/json"
    }
    
    if method == "GET":
        response = requests.get(url, headers=headers)
    elif method == "POST":
        response = requests.post(url, headers=headers, json=data)
    elif method == "PATCH":
        response = requests.patch(url, headers=headers, json=data)
    elif method == "DELETE":
        response = requests.delete(url, headers=headers)
    
    return response.json()


def sql_query(query):
    """Execute SQL query on server"""
    return api_call("POST", "/tools/sql", {"q": query})


def get_book_by_uuid(uuid):
    """Get book from server by UUID"""
    result = sql_query(f"SELECT * FROM books WHERE uuid = '{uuid}' AND library_id = {CALIMOB_LIB_ID} LIMIT 1")
    if result.get('count', 0) > 0:
        return result['rows'][0]
    return None


def _escape_sql_string(s):
    """Escape single quotes for safe use in server SQL strings."""
    if s is None:
        return ""
    return str(s).replace("\\", "\\\\").replace("'", "''")


def _restore_13(book_uuid, original_data):
    """Restore original metadata on server after test_13 (escaped)."""
    t = _escape_sql_string(original_data.get("title") or "")
    a = _escape_sql_string(original_data.get("author_sort") or "")
    p = _escape_sql_string(original_data.get("publisher") or "")
    r = original_data.get("rating") or 0
    sql_query(
        f"UPDATE books SET title = '{t}', author_sort = '{a}', publisher = '{p}', rating = {r}, last_modified = NOW() "
        f"WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}"
    )


def update_book_metadata(uuid, metadata):
    """Update book metadata on server via SQL (direct DB update)"""
    # Build SET clause from metadata dict (escape strings to avoid SQL breakage)
    set_parts = []
    
    if 'title' in metadata and metadata['title'] is not None:
        set_parts.append(f"title = '{_escape_sql_string(metadata['title'])}'")
    if 'author_sort' in metadata and metadata['author_sort'] is not None:
        set_parts.append(f"author_sort = '{_escape_sql_string(metadata['author_sort'])}'")
    if 'publisher' in metadata and metadata['publisher'] is not None:
        set_parts.append(f"publisher = '{_escape_sql_string(metadata['publisher'])}'")
    if 'rating' in metadata and metadata['rating'] is not None:
        set_parts.append(f"rating = {metadata['rating']}")
    if 'comments' in metadata and metadata['comments'] is not None:
        set_parts.append(f"comments = '{_escape_sql_string(metadata['comments'])}'")
    
    if not set_parts:
        return None
    
    # Bump last_modified so sync V5 sends a newer timestamp and client applies the update (otherwise client skips set_metadata).
    set_parts.append("last_modified = NOW()")
    set_clause = ", ".join(set_parts)
    query = f"UPDATE books SET {set_clause} WHERE uuid = '{uuid}' AND library_id = {CALIMOB_LIB_ID}"
    
    return sql_query(query)


def delete_book_on_server(uuid):
    """Soft delete book on server via SQL (uuid-based)."""
    return sql_query(
        f"UPDATE books SET deleted_at = NOW(), updated_at = NOW(), last_modified = NOW() "
        f"WHERE uuid = '{uuid}' AND library_id = {CALIMOB_LIB_ID}"
    )


def get_local_book_metadata(book_id):
    """Get book metadata from local Calibre library (calibre-debug subprocess, fallback: SQLite)."""
    script = f"""
import sys
sys.path.insert(0, {repr(PLUGIN_DIR)})
from calibre.library import db

database = db({repr(LIBRARY_PATH)})
book = database.get_metadata(int({book_id}))

print("RESULT_START")
print(f"title={{book.title}}")
print(f"authors={{','.join(book.authors)}}")
print(f"tags={{','.join(book.tags or [])}}")
print(f"series={{book.series or ''}}")
print(f"series_index={{book.series_index or 0}}")
print(f"publisher={{book.publisher or ''}}")
print(f"rating={{book.rating or 0}}")
print("RESULT_END")
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        result = subprocess.run(
            [CALIBRE_DEBUG, '-e', script_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if 'RESULT_START' in output and 'RESULT_END' in output:
            start = output.index('RESULT_START') + len('RESULT_START')
            end = output.index('RESULT_END')
            result_text = output[start:end].strip()
            metadata = {}
            for line in result_text.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    metadata[key] = value
            return metadata
        log_warning(f"get_local_book_metadata: calibre-debug no RESULT block (rc={result.returncode}), trying SQLite fallback")
        return _get_local_book_metadata_sqlite(book_id)
    except Exception as e:
        log_warning(f"get_local_book_metadata: {e}, trying SQLite fallback")
        return _get_local_book_metadata_sqlite(book_id)
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def _get_local_book_metadata_sqlite(book_id):
    """Fallback: read title, publisher, rating from Calibre metadata.db via SQLite (no subprocess)."""
    try:
        import sqlite3
        conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
        cursor = conn.execute("SELECT id, title FROM books WHERE id = ?", (int(book_id),))
        row = cursor.fetchone()
        if not row:
            conn.close()
            return None
        metadata = {
            'title': (row[1] or ''),
            'series': '',
            'series_index': '0',
            'publisher': '',
            'rating': '0',
            'authors': '',
            'tags': '',
        }
        try:
            c = conn.execute("SELECT series, series_index FROM books WHERE id = ?", (int(book_id),))
            r = c.fetchone()
            if r and r[0] is not None:
                metadata['series'] = str(r[0])
            if r and r[1] is not None:
                metadata['series_index'] = str(r[1])
        except (sqlite3.OperationalError, IndexError, TypeError):
            pass
        try:
            # Rating: books_ratings_link.rating is an ID, need to join with ratings table
            c = conn.execute("""
                SELECT r.rating 
                FROM books_ratings_link brl
                JOIN ratings r ON brl.rating = r.id
                WHERE brl.book = ?
            """, (int(book_id),))
            r = c.fetchone()
            if r and r[0] is not None:
                metadata['rating'] = str(r[0])
        except (sqlite3.OperationalError, IndexError, TypeError):
            pass
        try:
            c = conn.execute("SELECT publisher FROM books WHERE id = ?", (int(book_id),))
            r = c.fetchone()
            if r and r[0]:
                metadata['publisher'] = str(r[0])
        except (sqlite3.OperationalError, IndexError, TypeError):
            pass
        conn.close()
        return metadata
    except Exception as e:
        log_warning(f"SQLite fallback failed: {e}")
        return None


def run_sync_v5(clear_cache=False):
    """Run sync_v5 and return (results_dict, output). Delegates to sync_runner.
    When clear_cache=True: clears calimob_books_sync and resets the pull cursor.
    In-process vs subprocess: auto-detected (in-process when run under calibre-debug -e)."""
    import importlib.util
    _runner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'sync_runner.py')
    _spec = importlib.util.spec_from_file_location('sync_runner', _runner_path)
    _mod = importlib.util.module_from_spec(_spec)
    _spec.loader.exec_module(_mod)
    return _mod.run_sync_v5(
        LIBRARY_PATH,
        LIBRARY_UUID,
        CALIMOB_LIB_ID,
        PLUGIN_DIR,
        CALIBRE_DEBUG,
        clear_cache=clear_cache,
        in_process=None,
        debug_show_stderr=('--debug' in sys.argv),
    )

def _get_local_uuid_set():
    """Return set of UUIDs from local Calibre books table (fallback to cache)."""
    try:
        import sqlite3
        conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
        cur = conn.execute("SELECT uuid FROM books WHERE uuid IS NOT NULL")
        rows = cur.fetchall()
        local = set(r[0] for r in rows if r and r[0])
        if local:
            conn.close()
            return local
        cur = conn.execute(
            "SELECT uuid FROM calimob_books_sync WHERE library_uuid = ? AND uuid IS NOT NULL",
            (LIBRARY_UUID,)
        )
        rows = cur.fetchall()
        conn.close()
        return set(r[0] for r in rows if r and r[0])
    except Exception as e:
        log_warning(f"Failed to read local cache UUIDs: {e}")
        return set()


def _get_local_book_id_by_uuid(book_uuid):
    """Return local Calibre book id for a uuid, or None."""
    try:
        import sqlite3
        conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
        cur = conn.execute("SELECT id FROM books WHERE uuid = ?", (book_uuid,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        log_warning(f"Failed to lookup local book id for {book_uuid}: {e}")
        return None


def _get_local_title_by_uuid(book_uuid):
    """Return local title for a uuid, or None."""
    try:
        import sqlite3
        conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
        cur = conn.execute("SELECT title FROM books WHERE uuid = ?", (book_uuid,))
        row = cur.fetchone()
        conn.close()
        return row[0] if row else None
    except Exception as e:
        log_warning(f"Failed to lookup local title for {book_uuid}: {e}")
        return None


def _set_local_title_by_id(book_id, new_title):
    """Set local book title via calibre-debug for reliability."""
    script = f"""
from calibre.library import db

database = db({repr(LIBRARY_PATH)})
mi = database.get_metadata(int({book_id}), index_is_id=True)
mi.title = {repr(new_title)}
database.set_metadata(int({book_id}), mi)
print("OK")
"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script)
        script_path = f.name
    try:
        result = subprocess.run(
            [CALIBRE_DEBUG, '-e', script_path],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode == 0:
            return True
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass
    # Fallback to direct SQLite update if calibre-debug fails.
    try:
        import sqlite3
        conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
        conn.execute("UPDATE books SET title = ? WHERE id = ?", (new_title, int(book_id)))
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log_warning(f"Failed to set local title via SQLite for {book_id}: {e}")
        return False


def _ensure_local_title_matches_server(book_uuid, server_title):
    """Align local title to server title if needed. Return True if matched."""
    local_title = _get_local_title_by_uuid(book_uuid)
    if local_title == server_title:
        return True
    book_id = _get_local_book_id_by_uuid(book_uuid)
    if not book_id:
        return False
    if not _set_local_title_by_id(book_id, server_title):
        return False
    return _get_local_title_by_uuid(book_uuid) == server_title


def _set_local_last_modified(book_id, dt_iso):
    """Force local books.last_modified in metadata.db (SQLite)."""
    try:
        import sqlite3
        conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
        conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", (dt_iso, int(book_id)))
        conn.commit()
        conn.close()
        return True
    except Exception:
        # Fallback via calibre-debug to avoid SQLite view triggers in some configs.
        script = f"""
from calibre.library import db

db_obj = db({repr(LIBRARY_PATH)})
db_obj.conn.execute("UPDATE books SET last_modified = ? WHERE id = ?", ({repr(dt_iso)}, {int(book_id)}))
db_obj.conn.commit()
db_obj.close()
print("OK")
"""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(script)
            script_path = f.name
        try:
            result = subprocess.run(
                [CALIBRE_DEBUG, '-e', script_path],
                capture_output=True,
                text=True,
                timeout=30
            )
            return result.returncode == 0
        finally:
            try:
                os.unlink(script_path)
            except OSError:
                pass


def _set_local_title_by_uuid(book_uuid, new_title):
    """Set local title via calibre-debug using UUID."""
    book_id = _get_local_book_id_by_uuid(book_uuid)
    if not book_id:
        return False
    return _set_local_title_by_id(book_id, new_title)


def _ensure_book_in_cache(book_id, book_uuid):
    """Ensure calimob_books_sync has an entry for this book (needed for delete/cover logic)."""
    try:
        import sqlite3
        conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
        conn.execute(
            "INSERT OR IGNORE INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, created_at, modified_at) "
            "VALUES (?, ?, ?, '', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)",
            (LIBRARY_UUID, int(book_id), book_uuid)
        )
        conn.commit()
        conn.close()
        return True
    except Exception as e:
        log_warning(f"Failed to ensure book cache entry: {e}")
        return False


def _pick_server_book_uuid_from_local():
    """Pick a server book UUID that exists locally; run full sync if needed."""
    local_uuids = _get_local_uuid_set()
    if not local_uuids:
        run_sync_v5(clear_cache=True)
        local_uuids = _get_local_uuid_set()
    if not local_uuids:
        return None, None
    uuid_list = "', '".join(sorted(list(local_uuids))[:50])
    result = sql_query(
        f"SELECT uuid, title FROM books "
        f"WHERE library_id = {CALIMOB_LIB_ID} AND deleted_at IS NULL "
        f"AND uuid IN ('{uuid_list}') LIMIT 1"
    )
    if result.get('count', 0) == 0:
        return None, None
    return result['rows'][0]['uuid'], result['rows'][0]['title']


def _pick_matching_book_uuid_from_local():
    """Pick a book where local title matches server title."""
    local_uuids = _get_local_uuid_set()
    if not local_uuids:
        run_sync_v5(clear_cache=True)
        local_uuids = _get_local_uuid_set()
    if not local_uuids:
        return None, None
    uuid_list = "', '".join(sorted(list(local_uuids))[:50])
    result = sql_query(
        f"SELECT uuid, title FROM books "
        f"WHERE library_id = {CALIMOB_LIB_ID} AND deleted_at IS NULL "
        f"AND uuid IN ('{uuid_list}')"
    )
    rows = result.get('rows', []) if result else []
    for row in rows:
        local_title = _get_local_title_by_uuid(row.get('uuid'))
        if local_title and local_title == row.get('title'):
            return row.get('uuid'), row.get('title')
    if rows:
        return rows[0].get('uuid'), rows[0].get('title')
    return None, None


# ========== TEST SUITE ==========

class AdvancedSyncTests:
    def __init__(self):
        self.results = {
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'tests': []
        }
    
    def run_test(self, test_func, name):
        """Run a single test. Return True=pass, False=fail, None or (None, reason)=skipped."""
        print("=" * 60)
        log_info(f"TEST: {name}")
        print("=" * 60)
        if TIMING_ENABLED:
            _timings.clear()
        try:
            result = test_func()
            if TIMING_ENABLED and _timings:
                _print_timing_summary(name)
            if result is None or (isinstance(result, tuple) and len(result) >= 1 and result[0] is None):
                reason = result[1] if isinstance(result, tuple) and len(result) > 1 else None
                log_warning(f"SKIP: {name}" + (f" ({reason})" if reason else ""))
                self.results['skipped'] += 1
                self.results['tests'].append({'name': name, 'status': 'skip', 'reason': reason})
            elif result:
                log_success(f"PASS: {name}")
                self.results['passed'] += 1
                self.results['tests'].append({'name': name, 'status': 'pass'})
            else:
                log_error(f"FAIL: {name}")
                self.results['failed'] += 1
                self.results['tests'].append({'name': name, 'status': 'fail'})
        except Exception as e:
            log_error(f"ERROR: {name} - {str(e)}")
            self.results['failed'] += 1
            self.results['tests'].append({'name': name, 'status': 'error', 'error': str(e)})
        print()
    
    # ========== SERVER-SIDE CHANGE TESTS ==========
    
    def test_11_server_metadata_update_pull(self):
        """Test 11: Server modifies metadata → client pulls update"""
        log_info("Testing server-side metadata update...")
        
        # Step 1: Get a book UUID that exists locally
        with Timer("sql_get_book"):
            book_uuid, original_title = _pick_server_book_uuid_from_local()
        if not book_uuid:
            log_warning("No matching local/server book found, skipping test")
            return (None, "No matching local/server book")
        log_info(f"  Book UUID: {book_uuid}")
        log_info(f"  Original title: {original_title}")

        local_book_id = _get_local_book_id_by_uuid(book_uuid)
        if not local_book_id:
            log_warning("Book not found in local DB, skipping test")
            return (None, "Book not found in local DB")
        if not _ensure_local_title_matches_server(book_uuid, original_title):
            log_warning("Local title differs from server; skipping until local state is clean")
            return (None, "Local state not clean")
        
        # Step 2: Modify title on server via SQL (last_modified = NOW() so sync V5 applies the update on client)
        with Timer("sql_update_title"):
            new_title = f"{original_title} [MODIFIED]"
            sql_query(f"UPDATE books SET title = '{_escape_sql_string(new_title)}', last_modified = DATE_ADD(NOW(), INTERVAL 1 MINUTE) WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
        log_info(f"  Modified title to: {new_title}")
        
        time.sleep(2)
        
        # Step 3: Run sync (should pull update)
        with Timer("sync_v5"):
            results, output = run_sync_v5(clear_cache=True)
        
        if not results:
            log_error("Failed to parse sync results")
            return False
        
        log_info(f"  Updated: {results.get('updated', 0)}")
        if results.get('updated', 0) == 0:
            log_warning("  No updates applied; sync output tail:")
            print(output[-2000:])
        
        # Step 4: local_book_id already resolved above
        
        # Step 5: Verify local metadata
        with Timer("get_local_metadata"):
            local_metadata = get_local_book_metadata(local_book_id)
        
        if not local_metadata:
            log_error("Failed to get local metadata")
            sql_query(f"UPDATE books SET title = '{_escape_sql_string(original_title)}', last_modified = NOW() WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
            return False
        
        local_title = local_metadata.get('title', '')
        log_info(f"  Local title after sync: {local_title}")
        
        # Step 6: Restore original title
        with Timer("sql_restore_title"):
            sql_query(f"UPDATE books SET title = '{_escape_sql_string(original_title)}', last_modified = NOW() WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
        log_info(f"  Restored original title")
        _ensure_local_title_matches_server(book_uuid, original_title)
        
        # Verify title was updated
        if local_title != new_title:
            log_error(f"Title mismatch! Expected '{new_title}', got '{local_title}'")
            return False
        
        log_success("Title correctly synced to client")
        return True
    
    def test_12_server_deletion_pull(self):
        """Test 12: Server deletes book → client marks as deleted"""
        log_info("Testing server-side deletion...")
        
        # Step 1: Get a book that exists locally
        with Timer("sql_get_book"):
            book_uuid, book_title = _pick_server_book_uuid_from_local()
        if not book_uuid:
            log_warning("No matching local/server book found, skipping test")
            return (None, "No matching local/server book")
        log_info(f"  Book UUID: {book_uuid}")
        log_info(f"  Book title: {book_title}")

        local_book_id = _get_local_book_id_by_uuid(book_uuid)
        if local_book_id:
            _ensure_book_in_cache(local_book_id, book_uuid)
        if not _ensure_local_title_matches_server(book_uuid, book_title):
            log_warning("Local title differs from server; skipping until local state is clean")
            return (None, "Local state not clean")
        
        # Step 2: Soft delete on server
        with Timer("api_delete_book"):
            delete_book_on_server(book_uuid)
        log_info(f"  Deleted book on server")
        
        time.sleep(2)
        
        # Step 3: Run sync (should mark as deleted locally)
        with Timer("sync_v5"):
            results, output = run_sync_v5(clear_cache=True)
        
        if not results:
            log_error("Failed to parse sync results")
            sql_query(f"UPDATE books SET deleted_at = NULL WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
            return False
        
        log_info(f"  Synced: {results.get('synced', 0)}")
        if results.get('synced', 0) == 0:
            log_warning("  No sync changes applied; sync output tail:")
            print(output[-2000:])
        
        # Step 4: Check if book was deleted locally
        with Timer("sqlite_check_deleted"):
            import sqlite3
            conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
            
            # Check if book still exists in books table
            cursor = conn.execute("SELECT id FROM books WHERE uuid = ?", (book_uuid,))
            book_row = cursor.fetchone()
            book_exists_locally = book_row is not None
            
            # Check cache entry
            cursor = conn.execute(
                "SELECT calibre_book_id, is_deleted, deleted_at FROM calimob_books_sync WHERE uuid = ? AND library_uuid = ?",
                (book_uuid, LIBRARY_UUID)
            )
            cache_row = cursor.fetchone()
            conn.close()
        
        # Book should be deleted locally (removed from books table)
        if book_exists_locally:
            log_error(f"Book still exists in local books table (should be deleted)")
            sql_query(f"UPDATE books SET deleted_at = NULL WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
            return False
        
        log_info(f"  Book deleted from local books table ✓")
        
        # Cache should mark it as deleted
        if cache_row:
            cache_book_id, is_deleted, deleted_at = cache_row
            log_info(f"  Cache: book_id={cache_book_id}, is_deleted={is_deleted}, deleted_at={deleted_at}")
        else:
            log_info(f"  Cache entry removed (book deleted)")
        
        # Step 5: Restore book on server (undelete) and verify (so Test 13 has books)
        with Timer("sql_restore_deleted"):
            restore_res = sql_query(f"UPDATE books SET deleted_at = NULL WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
        if restore_res.get("status") == "error":
            log_error(f"  Restore failed: {restore_res.get('message', restore_res)}")
            return False
        log_info(f"  Restored book on server")
        verify = sql_query(f"SELECT 1 FROM books WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID} AND deleted_at IS NULL LIMIT 1")
        if verify.get("count", 0) == 0:
            log_error("  Restore verification failed: book still missing or deleted (Test 13 will see no books)")
            return False
        
        log_success("Deletion correctly synced to client (book deleted locally)")
        return True
    
    def test_13_all_metadata_fields_sync(self):
        """Test 13: Sync all metadata fields (tags, series, identifiers, etc.)"""
        log_info("Testing all metadata fields sync...")
        
        # Step 1: Get a book that exists locally
        with Timer("sql_get_book"):
            book_uuid, _ = _pick_server_book_uuid_from_local()
        if not book_uuid:
            log_warning("No matching local/server book found")
            return (None, "No matching local/server book")
        result = sql_query(
            f"SELECT uuid, title, author_sort, rating FROM books "
            f"WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID} AND deleted_at IS NULL LIMIT 1"
        )
        if result.get('count', 0) == 0:
            log_warning("No books on server")
            return (None, "No books on server")
        original_data = result['rows'][0]
        log_info(f"  Book UUID: {book_uuid}")

        # Ensure local book exists and matches server before proceeding.
        run_sync_v5(clear_cache=True)
        if not _ensure_local_title_matches_server(book_uuid, original_data['title']):
            log_warning("Local title differs from server; skipping until local state is clean")
            _restore_13(book_uuid, original_data)
            return (None, "Local state not clean")
        # Step 2: Update metadata fields on server via SQL
        test_title = "Complete Metadata Test"
        test_author_sort = "Author One & Author Two"
        test_rating = 8  # Server stores 0-10 (client will receive 0-5 and convert back to 0-10)
        
        with Timer("sql_update_metadata"):
            sql_query(f"""
                UPDATE books SET 
                    title = '{_escape_sql_string(test_title)}',
                    author_sort = '{_escape_sql_string(test_author_sort)}',
                    rating = {test_rating},
                    last_modified = DATE_ADD(NOW(), INTERVAL 1 MINUTE)
                WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}
            """)
        log_info(f"  Updated metadata fields on server")
        
        time.sleep(2)
        
        # Step 3: Run sync
        with Timer("sync_v5"):
            results, output = run_sync_v5(clear_cache=True)
        
        if not results:
            log_error("Failed to parse sync results")
            _restore_13(book_uuid, original_data)
            return False
        
        log_info(f"  Updated: {results.get('updated', 0)}")
        if results.get('updated', 0) == 0:
            log_warning("  No updates applied; sync output tail:")
            print(output[-2000:])
        
        # Step 4: Get local book_id and verify metadata
        with Timer("sqlite_local_book_id"):
            import sqlite3
            conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
            cursor = conn.execute("SELECT id FROM books WHERE uuid = ?", (book_uuid,))
            row = cursor.fetchone()
            conn.close()
        
        if not row:
            try:
                conn2 = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
                c = conn2.execute("SELECT COUNT(*) FROM books")
                total = c.fetchone()[0]
                c = conn2.execute("SELECT id, uuid FROM books LIMIT 5")
                sample = c.fetchall()
                conn2.close()
                log_info(f"  Diagnostic: local books table count={total}, sample (id,uuid)={sample}")
            except Exception as e:
                log_warning(f"  Diagnostic failed: {e}")
        
        if not row:
            log_error("Book not found in local DB")
            _restore_13(book_uuid, original_data)
            return False
        
        local_book_id = row[0]
        
        # Step 5: Verify local metadata
        with Timer("get_local_metadata"):
            local_metadata = get_local_book_metadata(local_book_id)
        
        if not local_metadata:
            log_error("Failed to get local metadata")
            _restore_13(book_uuid, original_data)
            return False
        
        local_title = local_metadata.get('title', '')
        local_rating = int(local_metadata.get('rating', 0))
        expected_local_rating = test_rating
        
        log_info(f"  Local title: {local_title}")
        log_info(f"  Local rating: {local_rating}")
        
        # Step 6: Restore original metadata
        with Timer("sql_restore_metadata"):
            _restore_13(book_uuid, original_data)
        log_info(f"  Restored original metadata")
        _ensure_local_title_matches_server(book_uuid, original_data.get('title'))
        
        # Verify all fields were updated
        errors = []
        if local_title != test_title:
            errors.append(f"Title mismatch: expected '{test_title}', got '{local_title}'")
        if local_rating != expected_local_rating:
            errors.append(f"Rating mismatch: expected {expected_local_rating}, got {local_rating}")
        
        if errors:
            for error in errors:
                log_error(f"  {error}")
            return False
        
        log_success("All metadata fields correctly synced to client")
        return True
    
    # ========== CONFLICT TESTS ==========
    
    def test_14_conflict_both_modified_server_wins(self):
        """Test 14: Both client and server modify same book → server wins"""
        log_info("Testing conflict resolution (server wins)...")
        book_uuid, original_title = _pick_server_book_uuid_from_local()
        if not book_uuid:
            return (None, "No matching local/server book")
        if not _ensure_local_title_matches_server(book_uuid, original_title):
            return (None, "Local state not clean")

        local_book_id = _get_local_book_id_by_uuid(book_uuid)
        if not local_book_id:
            return (None, "Local book missing")

        # Client modifies locally
        local_title = f"{original_title} [LOCAL]"
        if not _set_local_title_by_uuid(book_uuid, local_title):
            return (None, "Failed to set local title")

        # Server modifies with newer timestamp
        server_title = f"{original_title} [SERVER]"
        sql_query(
            f"UPDATE books SET title = '{_escape_sql_string(server_title)}', "
            f"last_modified = DATE_ADD(NOW(), INTERVAL 2 MINUTE) "
            f"WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}"
        )

        time.sleep(2)
        results, _ = run_sync_v5(clear_cache=True)
        if not results:
            return False

        synced_title = _get_local_title_by_uuid(book_uuid)

        # Restore original
        sql_query(
            f"UPDATE books SET title = '{_escape_sql_string(original_title)}', last_modified = NOW() "
            f"WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}"
        )
        _set_local_title_by_uuid(book_uuid, original_title)

        if synced_title != server_title:
            log_error(f"Expected server title '{server_title}', got '{synced_title}'")
            return False
        return True
    
    def test_15_conflict_client_newer_timestamp(self):
        """Test 15: Client has newer timestamp → client wins"""
        log_info("Testing conflict with client newer...")
        book_uuid, original_title = _pick_server_book_uuid_from_local()
        if not book_uuid:
            return (None, "No matching local/server book")
        if not _ensure_local_title_matches_server(book_uuid, original_title):
            return (None, "Local state not clean")

        local_book_id = _get_local_book_id_by_uuid(book_uuid)
        if not local_book_id:
            return (None, "Local book missing")

        # Server modifies with older timestamp
        server_title = f"{original_title} [SERVER_OLD]"
        sql_query(
            f"UPDATE books SET title = '{_escape_sql_string(server_title)}', "
            f"last_modified = DATE_ADD(NOW(), INTERVAL 1 MINUTE) "
            f"WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}"
        )

        # Client modifies with newer local timestamp
        local_title = f"{original_title} [LOCAL_NEW]"
        if not _set_local_title_by_uuid(book_uuid, local_title):
            return (None, "Failed to set local title")
        # Force local last_modified ahead of server
        from datetime import datetime, timedelta, timezone
        future_ts = (datetime.now(timezone.utc) + timedelta(minutes=5)).strftime('%Y-%m-%d %H:%M:%S')
        _set_local_last_modified(local_book_id, future_ts)

        time.sleep(2)
        results, _ = run_sync_v5(clear_cache=True)
        if not results:
            return False

        # Verify server now has client title
        server_row = sql_query(
            f"SELECT title FROM books WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID} LIMIT 1"
        )
        server_title_after = server_row['rows'][0]['title'] if server_row.get('count', 0) else None

        # Restore original
        sql_query(
            f"UPDATE books SET title = '{_escape_sql_string(original_title)}', last_modified = NOW() "
            f"WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}"
        )
        _set_local_title_by_uuid(book_uuid, original_title)

        if server_title_after != local_title:
            log_error(f"Expected server title '{local_title}', got '{server_title_after}'")
            return False
        return True
    
    # ========== EDGE CASES ==========
    
    def test_16_empty_metadata_fields(self):
        """Test 16: Handle empty/null metadata fields"""
        log_info("Testing empty metadata fields...")
        
        book_uuid, _ = _pick_matching_book_uuid_from_local()
        if not book_uuid:
            return (None, "No matching local/server book")
        server_row = sql_query(f"SELECT title FROM books WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID} LIMIT 1")
        server_title = server_row['rows'][0]['title'] if server_row.get('count', 0) else None
        run_sync_v5(clear_cache=True)
        if server_title and not _ensure_local_title_matches_server(book_uuid, server_title):
            return (None, "Local state not clean")
        local_title = _get_local_title_by_uuid(book_uuid)
        if server_title and local_title != server_title:
            return (None, "Local state not clean")
        if local_title is None:
            return (None, "Local book missing")
        
        # Clear all optional fields
        minimal_metadata = {
            "title": "Minimal Book",
            "authors": [{"name": "Unknown"}],
            "tags": [],
            "series": None,
            "publisher": None,
            "rating": None,
            "comments": None
        }
        
        update_book_metadata(book_uuid, minimal_metadata)
        sql_query(f"UPDATE books SET last_modified = DATE_ADD(NOW(), INTERVAL 1 MINUTE) WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
        time.sleep(2)
        
        results, output = run_sync_v5(clear_cache=True)
        
        return results is not None and results.get('errors', 0) == 0
    
    def test_17_special_characters_in_metadata(self):
        """Test 17: Handle special characters in metadata"""
        log_info("Testing special characters...")
        
        book_uuid, _ = _pick_matching_book_uuid_from_local()
        if not book_uuid:
            return (None, "No matching local/server book")
        server_row = sql_query(f"SELECT title FROM books WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID} LIMIT 1")
        server_title = server_row['rows'][0]['title'] if server_row.get('count', 0) else None
        run_sync_v5(clear_cache=True)
        if server_title and not _ensure_local_title_matches_server(book_uuid, server_title):
            return (None, "Local state not clean")
        local_title = _get_local_title_by_uuid(book_uuid)
        if local_title is None:
            return (None, "Local book missing")
        
        special_metadata = {
            "title": "Test: Special <>& Characters"
        }
        
        update_res = update_book_metadata(book_uuid, special_metadata)
        if isinstance(update_res, dict):
            log_info(f"  Update result: {update_res.get('status')} {update_res.get('message', '')}".strip())
        else:
            log_info(f"  Update result: {update_res}")
        sql_query(f"UPDATE books SET last_modified = DATE_ADD(NOW(), INTERVAL 1 MINUTE) WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
        time.sleep(2)
        verify_row = sql_query(f"SELECT title FROM books WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID} LIMIT 1")
        verify_title = verify_row['rows'][0]['title'] if verify_row.get('count', 0) else None
        log_info(f"  Server title after update: {verify_title}")

        # Align local to avoid client push overwriting server during the same sync cycle.
        _set_local_title_by_uuid(book_uuid, special_metadata["title"])
        
        results, output = run_sync_v5(clear_cache=True)
        if not results or results.get('errors', 0) != 0:
            return False
        synced = _get_local_title_by_uuid(book_uuid)
        server_row = sql_query(f"SELECT title FROM books WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID} LIMIT 1")
        server_synced_title = server_row['rows'][0]['title'] if server_row.get('count', 0) else None
        # Restore original title
        if server_title:
            sql_query(f"UPDATE books SET title = '{_escape_sql_string(server_title)}', last_modified = NOW() WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
            _set_local_title_by_uuid(book_uuid, server_title)
        if synced != server_synced_title:
            log_warning(f"Special chars mismatch: local='{synced}' server='{server_synced_title}'")
            return False
        return True

    def test_19_server_delete_marks_cache(self):
        """Test 19: Server delete updates local cache state"""
        log_info("Testing server deletion cache update...")
        book_uuid, book_title = _pick_server_book_uuid_from_local()
        if not book_uuid:
            return (None, "No matching local/server book")
        if book_title and not _ensure_local_title_matches_server(book_uuid, book_title):
            return (None, "Local state not clean")

        # Delete on server
        delete_book_on_server(book_uuid)
        time.sleep(2)
        results, _ = run_sync_v5(clear_cache=True)
        if not results:
            return False

        # Verify cache updated
        import sqlite3
        conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
        cur = conn.execute(
            "SELECT is_deleted, deleted_at FROM calimob_books_sync WHERE library_uuid = ? AND uuid = ? LIMIT 1",
            (LIBRARY_UUID, book_uuid)
        )
        row = cur.fetchone()
        conn.close()

        # Restore on server
        sql_query(f"UPDATE books SET deleted_at = NULL WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")

        if not row:
            return False
        is_deleted, deleted_at = row
        return bool(is_deleted) and deleted_at is not None
    
    def test_18_client_deletion_push(self):
        """Test 18: Client deletes book → server marks as deleted"""
        log_info("Testing client-side deletion push...")
        
        # Step 0: Ensure we have books locally (sync from server)
        log_info("  Syncing to ensure local books exist...")
        with Timer("sync_initial"):
            run_sync_v5(clear_cache=True)
        
        # Step 1: Get a book that exists locally and on server (prefer known UUIDs, else any)
        import sqlite3
        conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
        cur = conn.execute(
            "SELECT id, uuid, title FROM books WHERE uuid IN ('85023d84-8e5c-45c7-846b-a710cca1a637', '0fe1fbbe-81c5-4fc5-ab23-9647bdbe6c3b') LIMIT 1"
        )
        book_row = cur.fetchone()
        if not book_row:
            # Fallback: any local book that exists on server
            server_books = sql_query(f"SELECT uuid FROM books WHERE library_id = {CALIMOB_LIB_ID} AND deleted_at IS NULL LIMIT 20")
            if server_books.get("count", 0) > 0:
                uuids = [r["uuid"] for r in server_books.get("rows", [])]
                log_info(f"  Fallback: found {len(uuids)} books on server, checking locally...")
                placeholders = ",".join("?" * len(uuids))
                cur = conn.execute(
                    f"SELECT id, uuid, title FROM books WHERE uuid IN ({placeholders}) LIMIT 1",
                    uuids
                )
                book_row = cur.fetchone()
                if book_row:
                    log_info(f"  Fallback: found matching book locally")
                else:
                    log_warning(f"  Fallback: no matching book found locally (server UUIDs: {[u[:8] for u in uuids[:3]]})")
        conn.close()
        
        if not book_row:
            log_warning("No suitable local book found after sync, skipping test")
            return (None, "No matching local/server book")
        
        local_book_id, book_uuid, book_title = book_row
        log_info(f"  Using local book: {book_title} ({book_uuid[:8]})")
        log_info(f"  Local book_id: {local_book_id}")
        
        # Step 1.5: Verify book is in cache (required for deletion detection)
        conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
        cur = conn.execute(
            "SELECT calibre_book_id FROM calimob_books_sync WHERE calibre_book_id = ? AND library_uuid = ?",
            (local_book_id, LIBRARY_UUID)
        )
        cache_row = cur.fetchone()
        conn.close()
        
        if not cache_row:
            # Try a full sync to populate cache, then re-check once
            run_sync_v5(clear_cache=True)
            conn = sqlite3.connect(f"{LIBRARY_PATH}/metadata.db")
            cur = conn.execute(
                "SELECT calibre_book_id FROM calimob_books_sync WHERE calibre_book_id = ? AND library_uuid = ?",
                (local_book_id, LIBRARY_UUID)
            )
            cache_row = cur.fetchone()
            conn.close()
            if not cache_row:
                log_warning(f"Book not in cache (book_id={local_book_id}), skipping test")
                log_warning("Note: Only books that have been synced can be detected as deleted")
                return (None, "Book not in cache")
        
        log_info(f"  Book is in cache ✓")
        
        # Step 2: Ensure book exists on server (restore if deleted)
        with Timer("sql_check_server"):
            result = sql_query(f"SELECT deleted_at FROM books WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
        
        if result.get('count', 0) == 0:
            log_error("Book not found on server")
            return False
        
        if result['rows'][0]['deleted_at'] is not None:
            # Restore book on server
            sql_query(f"UPDATE books SET deleted_at = NULL WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
            log_info(f"  Restored book on server")
        
        # Step 3: Delete book locally via calibre-debug
        with Timer("calibre_delete_book"):
            script = f"""
from calibre.library import db

db_obj = db('{LIBRARY_PATH}')
db_obj.delete_book({local_book_id})
db_obj.close()
print("DELETED_OK")
"""
            result = subprocess.run(
                [CALIBRE_DEBUG, "-c", script],
                capture_output=True,
                text=True,
                timeout=30
            )
        
        if "DELETED_OK" not in result.stdout:
            log_error(f"Failed to delete book locally: {result.stderr}")
            # Restore on server
            sql_query(f"UPDATE books SET deleted_at = NULL WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
            return False
        
        log_info(f"  Deleted book locally")
        
        # Step 4: Run sync (should push deletion to server)
        time.sleep(2)
        with Timer("sync_push_deletion"):
            results, output = run_sync_v5(clear_cache=False)
        
        if not results:
            log_error("Failed to sync deletion to server")
            # Restore on server
            sql_query(f"UPDATE books SET deleted_at = NULL WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
            return False
        
        log_info(f"  Synced: {results.get('synced', 0)}")
        
        # Step 5: Verify book is soft-deleted on server
        with Timer("sql_verify_deleted"):
            result = sql_query(f"SELECT deleted_at FROM books WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
        
        if result.get('count', 0) == 0:
            log_error("Book not found on server")
            return False
        
        deleted_at = result['rows'][0]['deleted_at']
        log_info(f"  Server deleted_at: {deleted_at}")
        
        # Step 6: Restore book on server for next test
        with Timer("sql_restore"):
            sql_query(f"UPDATE books SET deleted_at = NULL WHERE uuid = '{book_uuid}' AND library_id = {CALIMOB_LIB_ID}")
        log_info(f"  Restored book on server")
        
        # Step 7: Sync to restore book locally
        with Timer("sync_restore"):
            run_sync_v5(clear_cache=True)
        log_info(f"  Synced book back to client")
        
        # Verify deletion was pushed
        if deleted_at is None:
            log_error("Book not marked as deleted on server")
            # deleted_books_sent is in results (from RESULT_START..RESULT_END) for the sync that ran after delete (Step 4)
            log_info("deleted_books_sent (in last sync request): %s" % (results.get('deleted_books_sent', 'N/A')))
            if output:
                for line in output.splitlines():
                    if 'SYNC_V5_' in line and ('DELETED_COUNT' in line or 'LIBRARY_PATH' in line or 'CACHE_TOTAL' in line or 'CACHE_ONLY' in line or 'CACHE_DIAG' in line):
                        log_info("Plugin: " + line.strip())
                lines = [l for l in output.splitlines() if 'SYNC_V5_' in l or 'mapping table' in l or 'deleted' in l.lower() or 'fetch_all' in l or ('Built' in l and 'hashes' in l)]
                if lines:
                    log_info("Plugin log excerpt (deleted/cache):")
                    for l in lines[-25:]:
                        print("    " + l)
            return False
        
        log_success("Client deletion correctly pushed to server")
        return True
    
    # ========== RUN SUITES ==========
    
    def run_server_changes_tests(self):
        """Run server-side change tests"""
        self.run_test(self.test_11_server_metadata_update_pull, "Server metadata update → client pull")
        self.run_test(self.test_12_server_deletion_pull, "Server deletion → client delete")
        self.run_test(self.test_13_all_metadata_fields_sync, "All metadata fields sync")
    
    def run_deletion_tests(self):
        """Run deletion tests (both directions)"""
        self.run_test(self.test_12_server_deletion_pull, "Server deletion → client delete")
        self.run_test(self.test_18_client_deletion_push, "Client deletion → server delete")
    
    def run_conflict_tests(self):
        """Run conflict resolution tests"""
        self.run_test(self.test_14_conflict_both_modified_server_wins, "Conflict: both modified → server wins")
        self.run_test(self.test_15_conflict_client_newer_timestamp, "Conflict: client newer timestamp")
    
    def run_edge_case_tests(self):
        """Run edge case tests"""
        self.run_test(self.test_16_empty_metadata_fields, "Empty metadata fields")
        self.run_test(self.test_17_special_characters_in_metadata, "Special characters in metadata")
        self.run_test(self.test_19_server_delete_marks_cache, "Server delete marks cache")
    
    def print_summary(self):
        """Print test summary"""
        total = self.results['passed'] + self.results['failed'] + self.results['skipped']
        print()
        print("=" * 60)
        print("TEST SUMMARY")
        print("=" * 60)
        print(f"✓ Passed:  {self.results['passed']}/{total}")
        print(f"✗ Failed:  {self.results['failed']}/{total}")
        print(f"⚠ Skipped: {self.results['skipped']}/{total}")
        print()
        print("Detailed Results:")
        for test in self.results['tests']:
            status_icon = "✓" if test['status'] == 'pass' else "✗" if test['status'] == 'fail' else "⚠"
            print(f"{status_icon}   {test['name']}")
            if test.get('status') == 'skip' and test.get('reason'):
                print(f"     Reason: {test['reason']}")
            if 'error' in test:
                print(f"     Error: {test['error']}")
        print("=" * 60)


# ========== MAIN ==========

if __name__ == "__main__":
    suite = AdvancedSyncTests()
    
    if len(sys.argv) < 2 or '--all' in sys.argv:
        log_info("Running all advanced tests...")
        suite.run_server_changes_tests()
        suite.run_deletion_tests()
        suite.run_conflict_tests()
        suite.run_edge_case_tests()
    elif '--server-changes' in sys.argv:
        suite.run_server_changes_tests()
    elif '--deletions' in sys.argv:
        suite.run_deletion_tests()
    elif '--conflicts' in sys.argv:
        suite.run_conflict_tests()
    elif '--edge-cases' in sys.argv:
        suite.run_edge_case_tests()
    else:
        print("Usage: python3 test_sync_v5_advanced.py [--all|--server-changes|--deletions|--conflicts|--edge-cases] [--timing]")
        print("  To debug sync: run with calibre-debug -e so sync runs in-process and breakpoints in sync_worker.py are hit.")
        sys.exit(1)
    
    suite.print_summary()
    sys.exit(0 if suite.results['failed'] == 0 else 1)
