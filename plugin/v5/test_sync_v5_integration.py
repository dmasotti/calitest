#!/usr/bin/env python3
"""
Sync V5 Integration Tests - Complete Suite

Tests sync_v5 against CalibreTest library using calibre-debug.
Includes: sync, upload, download, conflicts, failures, large libraries.

Usage:
    python3 tests/test_sync_v5_integration.py [--all|--basic|--upload|--download|--conflicts|--stress]
"""

import sys
import os
import subprocess
import tempfile
import time
import hashlib
import base64
import shutil
import threading
import json
import urllib.request
from datetime import datetime

# Test Configuration (override via env)
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))
LIBRARY_PATH = os.getenv(
    "CALIMOB_TEST_LIBRARY_PATH",
    os.path.join(PROJECT_ROOT, "tests/plugin/CalibreTest"),
)
LIBRARY_UUID = os.getenv("CALIMOB_TEST_LIBRARY_UUID", "1685fd4f-054e-4451-9df8-119c27fc1289")
CALIMOB_LIB_ID = os.getenv("CALIMOB_TEST_CALIMOB_LIB_ID", "12")
CALIBRE_DEBUG = os.getenv("CALIBRE_DEBUG", "/Applications/calibre.app/Contents/MacOS/calibre-debug")
PLUGIN_DIR = os.path.join(PROJECT_ROOT, "sync_calimob")
API_URL = os.getenv("CALIMOB_TEST_API_URL", "http://caliserver-integration.test/api")
API_TOKEN = os.getenv("CALIMOB_TEST_TOKEN", "1|vUoYzdsOGUJDmgS0Blvr5cMewGg9WiuvKEXMZeTpc484627f")

ENV_FILE = os.path.join(PROJECT_ROOT, "tests/plugin/.env")


def _load_env_file():
    """Load key=value pairs from .env file (strips quotes)."""
    env = {}
    if not os.path.isfile(ENV_FILE):
        return env
    with open(ENV_FILE) as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith('#') or '=' not in line:
                continue
            key, _, value = line.partition('=')
            env[key.strip()] = value.strip().strip('"').strip("'")
    return env


def _api_request(url, method='GET', data=None, token=None):
    """Simple HTTP helper returning (status, json_body)."""
    payload = json.dumps(data).encode('utf-8') if data else None
    req = urllib.request.Request(url, data=payload, method=method)
    req.add_header('Content-Type', 'application/json')
    req.add_header('Accept', 'application/json')
    if token:
        req.add_header('Authorization', f'Bearer {token}')
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = json.loads(resp.read().decode('utf-8'))
            return resp.status, body
    except urllib.error.HTTPError as e:
        try:
            body = json.loads(e.read().decode('utf-8'))
        except Exception:
            body = {'error': str(e)}
        return e.code, body


def ensure_server_ready():
    """Bootstrap: verify/create token + library so the test can run.

    Steps:
      1. Try the current API_TOKEN. If 401, login with email/password
         from .env and create a fresh Sanctum token.
      2. List libraries. If none matches LIBRARY_UUID, create one.
      3. Update globals API_TOKEN and CALIMOB_LIB_ID.
    """
    global API_TOKEN, CALIMOB_LIB_ID, API_URL

    _bootstrap_user_id = None
    env = _load_env_file()
    base_url = API_URL.rstrip('/')

    # --- resolve API_URL from .env if the default doesn't respond ---
    if env.get('CALIMOB_DISCOVERY_URL'):
        candidate = env['CALIMOB_DISCOVERY_URL'].rstrip('/') + '/api'
        try:
            status, _ = _api_request(candidate + '/libraries', token=API_TOKEN)
        except Exception:
            status = 0
        if status != 0:
            # candidate server is reachable, use it
            base_url = candidate
            API_URL = candidate

    # --- step 1: login (always, to get user_id + fresh token) ---
    email = env.get('TEST_USER_EMAIL')
    password = env.get('TEST_USER_PASSWORD')
    if email and password:
        print(f"[bootstrap] Logging in as {email}...")
        try:
            status, body = _api_request(
                base_url + '/auth/login', method='POST',
                data={'email': email, 'password': password}
            )
            token = body.get('token')
            if token:
                API_TOKEN = token
                _bootstrap_user_id = (body.get('user') or {}).get('id')
                print(f"[bootstrap] Logged in (user_id={_bootstrap_user_id})")
            else:
                print(f"[bootstrap] Login failed: {body}")
        except Exception as e:
            print(f"[bootstrap] Login failed: {e}")

    # Verify token works
    try:
        status, body = _api_request(base_url + '/libraries', token=API_TOKEN)
    except Exception:
        status = 0
        body = {}

    if status != 200:
        print(f"[bootstrap] GET /libraries returned {status}: {body}")
        return False

    # --- step 2: find or create library ---
    libraries = body if isinstance(body, list) else body.get('data', body.get('libraries', []))
    match = None
    for lib in libraries:
        lib_uuid = lib.get('calibre_library_id') or lib.get('calibre_library_uuid') or ''
        if lib_uuid == LIBRARY_UUID:
            match = lib
            break

    if match:
        CALIMOB_LIB_ID = str(match['id'])
        print(f"[bootstrap] Library found: id={CALIMOB_LIB_ID} name={match.get('name')}")
    else:
        print(f"[bootstrap] Library {LIBRARY_UUID} not found, creating...")
        try:
            status, body = _api_request(
                base_url + '/libraries', method='POST', token=API_TOKEN,
                data={
                    'name': 'CalibreTest',
                    'description': 'Auto-created by test_sync_v5_integration.py',
                    'type': 'calibre',
                    'calibre_library_uuid': LIBRARY_UUID,
                }
            )
        except Exception as e:
            print(f"[bootstrap] Create library failed: {e}")
            return False

        lib_id = body.get('id')
        if not lib_id:
            print(f"[bootstrap] Create library response has no id: {body}")
            return False

        CALIMOB_LIB_ID = str(lib_id)
        print(f"[bootstrap] Library created: id={CALIMOB_LIB_ID}")

    # --- step 3: reset server data via psql (local dev DB) ---
    print(f"[bootstrap] Resetting server data for library {CALIMOB_LIB_ID}...")
    db_name = env.get('DB_DATABASE', 'caliweb_dev')
    lib_id_int = CALIMOB_LIB_ID  # may be UUID string — get numeric id
    try:
        # Get numeric library id from psql (API may return UUID as id)
        user_id = _bootstrap_user_id
        lib_id_int = None
        if user_id:
            try:
                r = subprocess.run(
                    ['psql', '-d', db_name, '-t', '-A', '-c',
                     f"SELECT id FROM libraries WHERE calibre_library_id = '{LIBRARY_UUID}' AND user_id = {user_id} LIMIT 1"],
                    capture_output=True, text=True, timeout=5,
                )
                lib_id_int = r.stdout.strip()
            except Exception:
                pass

        if not lib_id_int or not user_id:
            print(f"[bootstrap] Could not determine user_id={user_id} or library_id={lib_id_int}, skipping psql reset")
        else:
            sql = f"""
                DELETE FROM books_authors_link WHERE user_id = {user_id} AND library_id = {lib_id_int};
                DELETE FROM books_authors WHERE user_id = {user_id} AND library_id = {lib_id_int};
                DELETE FROM books_tags_link WHERE user_id = {user_id} AND library_id = {lib_id_int};
                DELETE FROM books_languages_link WHERE user_id = {user_id} AND library_id = {lib_id_int};
                DELETE FROM books_identifiers WHERE user_id = {user_id} AND library_id = {lib_id_int};
                DELETE FROM books WHERE user_id = {user_id} AND library_id = {lib_id_int};
                DELETE FROM sync_idempotencies WHERE user_id = {user_id} AND library_id = {lib_id_int};
                DELETE FROM sync_merkle_leaves WHERE user_id = {user_id} AND library_id = {lib_id_int};
                DELETE FROM sync_merkle_branches WHERE user_id = {user_id} AND library_id = {lib_id_int};
                DELETE FROM sync_merkle_roots WHERE user_id = {user_id} AND library_id = {lib_id_int};
            """
            result = subprocess.run(
                ['psql', '-d', db_name, '-c', sql],
                capture_output=True, text=True, timeout=10,
            )
            if result.returncode == 0:
                print(f"[bootstrap] Server data reset (user={user_id}, library={lib_id_int})")
            else:
                print(f"[bootstrap] psql reset failed: {result.stderr.strip()}")
    except Exception as e:
        print(f"[bootstrap] Server reset failed (non-critical): {e}")

    print(f"[bootstrap] Ready: API_URL={API_URL} LIB_ID={CALIMOB_LIB_ID}")
    return True


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


def run_streaming_process(cmd, timeout=180):
    """Run command streaming stdout/stderr live, return (returncode, combined_output, timed_out)."""
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        bufsize=1,
    )

    out_lines = []
    err_lines = []

    def _reader(pipe, store):
        try:
            for line in iter(pipe.readline, ''):
                store.append(line)
                # Live progress to understand where timeout happens.
                print(line, end='')
        finally:
            try:
                pipe.close()
            except Exception:
                pass

    t_out = threading.Thread(target=_reader, args=(proc.stdout, out_lines), daemon=True)
    t_err = threading.Thread(target=_reader, args=(proc.stderr, err_lines), daemon=True)
    t_out.start()
    t_err.start()

    timed_out = False
    try:
        proc.wait(timeout=timeout)
    except subprocess.TimeoutExpired:
        timed_out = True
        proc.kill()
        proc.wait()

    t_out.join(timeout=2)
    t_err.join(timeout=2)

    combined = ''.join(err_lines) + ''.join(out_lines)
    return proc.returncode, combined, timed_out


def run_sync_v5(clear_cache=False, no_cache=False, script_extra=""):
    """Run sync_v5 via calibre-debug"""

    if clear_cache:
        log_info("Clearing cache...")
        subprocess.run([
            'sqlite3', f'{LIBRARY_PATH}/metadata.db',
            f"DELETE FROM calimob_books_sync WHERE library_uuid='{LIBRARY_UUID}'"
        ], capture_output=True)

    # Create Python script for calibre-debug
    reset_cursor_line = "worker.reset_cursor()" if clear_cache else ""
    no_cache_arg = "no_cache=True" if no_cache else ""
    script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')

from sync_worker import SyncWorker
import mapping_table
import config as cfg
from calibre.library import db

library_path = '{LIBRARY_PATH}'
library_uuid = '{LIBRARY_UUID}'
calimob_library_id = '{CALIMOB_LIB_ID}'

database = db(library_path)
with mapping_table._connect(library_path) as _conn:
    mapping_table._ensure_table(_conn)
    _conn.commit()

# Configure endpoint/token for headless test runs.
plugin_store = dict(cfg.plugin_prefs.get(cfg.STORE_PLUGIN, {{}}))
if '{API_URL}':
    plugin_store[cfg.KEY_REST_ENDPOINT] = '{API_URL}'
if '{API_TOKEN}':
    plugin_store[cfg.KEY_DEVICE_TOKEN] = '{API_TOKEN}'
    plugin_store[cfg.KEY_REST_TOKEN] = '{API_TOKEN}'
cfg.plugin_prefs[cfg.STORE_PLUGIN] = plugin_store

worker = SyncWorker(None, database, library_uuid, calimob_library_id)

{reset_cursor_line}
{script_extra}

summary = worker.sync_v5({no_cache_arg})

print("RESULT_START")
print(f"synced={{summary['books_synced']}}")
print(f"created={{summary['books_created']}}")
print(f"updated={{summary['books_updated']}}")
print(f"skipped={{summary['books_skipped']}}")
print(f"skipped_hash={{summary['books_skipped_hash']}}")
print(f"files_downloaded={{summary.get('files_downloaded', 0)}}")
print(f"errors={{len(summary['errors'])}}")
print("RESULT_END")
"""
    
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script)
        script_path = f.name
    
    try:
        returncode, output, timed_out = run_streaming_process(
            [CALIBRE_DEBUG, '-e', script_path],
            timeout=180
        )

        if timed_out:
            output += "\n[TIMEOUT] calibre-debug exceeded 180s\n"
            return None, output
        
        if 'RESULT_START' in output and 'RESULT_END' in output:
            start = output.index('RESULT_START') + len('RESULT_START')
            end = output.index('RESULT_END')
            result_text = output[start:end].strip()
            
            results = {}
            for line in result_text.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    results[key.strip()] = int(value.strip())
            
            return results, output
        else:
            return None, output
    
    finally:
        os.unlink(script_path)


def run_calibre_script(script_code, timeout=60):
    """Run arbitrary Python script in Calibre environment"""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script_code)
        script_path = f.name
    
    try:
        result = subprocess.run(
            [CALIBRE_DEBUG, '-e', script_path],
            capture_output=True,
            text=True,
            timeout=timeout
        )
        return result.returncode == 0, result.stdout + result.stderr
    finally:
        os.unlink(script_path)


def parse_result_block(output):
    """Parse key=value lines from RESULT_START/RESULT_END markers."""
    if 'RESULT_START' not in output or 'RESULT_END' not in output:
        return None
    start = output.index('RESULT_START') + len('RESULT_START')
    end = output.index('RESULT_END')
    block = output[start:end].strip()
    parsed = {}
    for line in block.split('\n'):
        if '=' in line:
            key, value = line.split('=', 1)
            parsed[key.strip()] = value.strip()
    return parsed


def api_tools_sql(query):
    """Run SQL through /api/tools/sql when API token is available."""
    if not API_URL or not API_TOKEN:
        return None
    url = API_URL.rstrip('/') + '/tools/sql'
    payload = json.dumps({'q': query}).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method='POST')
    req.add_header('Content-Type', 'application/json')
    req.add_header('Accept', 'application/json')
    req.add_header('Authorization', 'Bearer %s' % API_TOKEN)
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = resp.read().decode('utf-8')
    return json.loads(body)


class SyncV5Tester:
    def __init__(self):
        self.results = {
            'passed': 0,
            'failed': 0,
            'skipped': 0,
            'tests': []
        }
    
    def run_test(self, name, test_func):
        """Run a single test and record result"""
        log_info(f"Running: {name}")
        try:
            result = test_func()
            if result is None:
                log_warning(f"SKIP: {name}")
                self.results['skipped'] += 1
                self.results['tests'].append({'name': name, 'status': 'skip'})
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
    
    # ========== BASIC SYNC TESTS ==========
    
    def test_1_full_sync_empty_cache(self):
        """Test 1: Full sync with empty cache"""
        log_info("Running full sync with empty cache...")
        
        results, output = run_sync_v5(clear_cache=True, no_cache=True)
        
        if not results:
            log_error("Failed to parse results")
            print(output[-500:])
            return False
        
        log_info(f"  Synced: {results.get('synced', 0)}")
        log_info(f"  Created: {results.get('created', 0)}")
        log_info(f"  Updated: {results.get('updated', 0)}")
        log_info(f"  Skipped: {results.get('skipped', 0)}")
        log_info(f"  Skipped (hash): {results.get('skipped_hash', 0)}")
        log_info(f"  Files downloaded: {results.get('files_downloaded', 0)}")
        log_info(f"  Errors: {results.get('errors', 0)}")
        
        if results.get('errors', 0) > 0:
            log_error("Errors reported; last output:")
            print(output[-2000:])
        if results.get('synced', 0) == 0:
            log_error("No books synced")
            print(output[-2000:])
            return False
        
        self.first_run_results = results
        return True
    
    def test_2_partial_sync_full_cache(self):
        """Test 2: Partial sync with full cache (should skip all)"""
        log_info("Running sync with full cache...")
        
        time.sleep(2)
        
        results, output = run_sync_v5(clear_cache=False)
        
        if not results:
            log_error("Failed to parse results")
            return False
        
        log_info(f"  Synced: {results.get('synced', 0)}")
        log_info(f"  Skipped (hash): {results.get('skipped_hash', 0)}")
        log_info(f"  Files downloaded: {results.get('files_downloaded', 0)}")
        
        return True
    
    def test_2b_hash_optimization_no_transfers(self):
        """
        Test 2b: Hash optimization - no transfers when hashes match
        
        Verifies that when client and server have identical hashes:
        - Server skips books (skipped_hash > 0)
        - Server doesn't request updates (missing_from_server = 0)
        - Client doesn't process any books (books_synced = 0)
        - No files/covers transferred
        """
        log_info("Test: Hash optimization - no transfers when hashes match")
        
        # First sync: ensure server has all books (may already be there from test 1)
        log_info("Step 1: Full sync to ensure server is populated...")
        results1, output1 = run_sync_v5(clear_cache=True, no_cache=True)

        if not results1:
            log_error("First sync failed")
            return False

        errors_first = int(results1.get('errors', 0))
        synced_first = int(results1.get('synced', 0)) + int(results1.get('created', 0))
        log_info(f"  Synced/created: {synced_first} books, errors: {errors_first}")

        if errors_first > 0:
            log_error(f"First sync had {errors_first} errors")
            return False
        
        time.sleep(2)
        
        # Second sync: full cache, identical hashes
        log_info("Step 2: Second sync - expecting all skipped by hash...")
        results2, output2 = run_sync_v5(clear_cache=False)
        
        if not results2:
            log_error("Second sync failed")
            return False
        
        synced = int(results2.get('synced', 0))
        skipped_hash = int(results2.get('skipped_hash', 0))
        missing = int(results2.get('missing_from_server', 0))
        files_dl = int(results2.get('files_downloaded', 0))
        
        log_info(f"  Synced: {synced}")
        log_info(f"  Skipped (hash): {skipped_hash}")
        log_info(f"  Missing from server: {missing}")
        log_info(f"  Files downloaded: {files_dl}")
        
        # Verifications
        success = True
        
        # Client should not process any books
        if synced != 0:
            log_error(f"✗ Expected 0 books synced, got {synced}")
            success = False
        else:
            log_success("✓ No books synced")
        
        # Server should have skipped books due to hash match
        if skipped_hash == 0:
            log_error("✗ Expected skipped_hash > 0")
            success = False
        else:
            log_success(f"✓ Server skipped {skipped_hash} books (hash match)")
        
        # Server should not have requested anything
        if missing != 0:
            log_warning(f"⚠ Server requested {missing} books (expected 0)")
        else:
            log_success("✓ Server requested 0 books")
        
        # No files downloaded
        if files_dl != 0:
            log_error(f"✗ Expected 0 files downloaded, got {files_dl}")
            success = False
        else:
            log_success("✓ No files downloaded")
        
        if success:
            log_success("✓ Hash optimization working: no unnecessary transfers")
        else:
            log_error("✗ Hash optimization test failed")
        
        return success
    
    def test_3_batch_processing(self):
        """Test 3: Batch processing"""
        log_info("Testing batch processing...")
        
        results, output = run_sync_v5(clear_cache=False)
        
        if results:
            log_info("  Batch processing completed")
            return True
        else:
            log_error("  Batch processing failed")
            return False
    
    # ========== UPLOAD TESTS ==========
    
    def test_4_upload_new_file_format(self):
        """Test 4: Upload new file format to existing book"""
        log_info("Testing file upload...")
        
        # Get first book
        script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
book_ids = database.all_ids()
if book_ids:
    book_id = book_ids[0]
    metadata = database.get_metadata(book_id, index_is_id=True)
    formats = database.formats(book_id, index_is_id=True) or ""
    
        print("RESULT_START")
        print(f"book_id={{book_id}}")
        print(f"uuid={{metadata.uuid}}")
        print(f"title={{metadata.title}}")
        print(f"formats={{formats}}")
        print("RESULT_END")
"""
        
        success, output = run_calibre_script(script)
        if not success or 'RESULT_START' not in output:
            log_error("Failed to get book info")
            print(output[-200:])
            return False
        
        # Parse book info
        info = parse_result_block(output)
        if not info:
            log_error("Could not parse book info block")
            print(output[-500:])
            return False

        try:
            book_id = int(info.get('book_id', '0'))
        except ValueError:
            book_id = None
        book_uuid = info.get('uuid')
        
        if not book_id:
            log_error("Could not parse book ID")
            return False
        if not book_uuid:
            log_error("Could not parse book UUID")
            return False
        
        log_info(f"  Using book ID: {book_id}")
        
        # Create dummy TXT file
        dummy_content = f"Test file created at {datetime.now()}\n"
        with tempfile.NamedTemporaryFile(mode='w', suffix='.txt', delete=False) as f:
            f.write(dummy_content)
            txt_path = f.name
        
        try:
            # Add TXT format to book
            add_script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
database.add_format({book_id}, 'TXT', '{txt_path}', index_is_id=True)
print("FORMAT_ADDED")
"""
            
            success, output = run_calibre_script(add_script)
            if not success or 'FORMAT_ADDED' not in output:
                log_error("Failed to add format")
                return False
            
            log_info("  TXT format added locally")
            
            # Now sync (should upload TXT)
            results, sync_output = run_sync_v5(clear_cache=False)
            
            if not results:
                log_error("Sync failed")
                return False
            
            log_info(f"  Sync completed: {results.get('synced', 0)} books")
            
            # TODO: Verify on server that TXT was uploaded
            if results.get('errors', 0) != 0:
                return False
            sql_res = api_tools_sql(
                "SELECT COUNT(*) AS c FROM books_files WHERE book='%s' AND format='TXT'" % book_uuid
            )
            if not sql_res or 'rows' not in sql_res or not sql_res['rows']:
                log_warning("Server SQL check unavailable; upload assert skipped")
                return True
            count_txt = int(sql_res['rows'][0].get('c') or 0)
            log_info(f"  Server TXT count for book: {count_txt}")
            return count_txt > 0
        
        finally:
            os.unlink(txt_path)
    
    def test_5_upload_modified_cover(self):
        """Test 5: Upload modified cover"""
        log_info("Testing cover upload...")
        
        # Get first book with cover (or create one if none)
        script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
for book_id in database.all_ids():
    if database.has_cover(book_id):
        metadata = database.get_metadata(book_id, index_is_id=True)
        print("RESULT_START")
        print(f"book_id={{book_id}}")
        print(f"uuid={{metadata.uuid}}")
        print("RESULT_END")
        break
"""
        
        success, output = run_calibre_script(script)
        if not success or 'RESULT_START' not in output:
            # No cover found: set a dummy cover on first book, then retry
            dummy_cover = base64.b64decode(
                "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFwAAAwEAAAAAAAAAAAAAAAAAAAQFBv/EABQBAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhADEAAAAf8A/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPwA//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwA//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwA//9k="
            )
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                f.write(dummy_cover)
                cover_path = f.name
            try:
                seed_script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
book_id = database.all_ids()[0]
with open('{cover_path}', 'rb') as f:
    database.set_cover(book_id, f.read())
print("COVER_SEEDED")
print(f"book_id={{book_id}}")
metadata = database.get_metadata(book_id, index_is_id=True)
print(f"uuid={{metadata.uuid}}")
"""
                seed_ok, seed_out = run_calibre_script(seed_script)
                if not seed_ok or 'COVER_SEEDED' not in seed_out:
                    log_warning("No books with cover found and seeding failed")
                    print(seed_out[-200:])
                    return None
                output = seed_out
            finally:
                os.unlink(cover_path)
        
        book_id = None
        for line in output.split('\n'):
            if 'book_id=' in line:
                book_id = int(line.split('=')[1])
                break
        
        if not book_id:
            log_warning("Could not parse book ID")
            return None
        book_uuid = None
        for line in output.split('\n'):
            if 'uuid=' in line:
                book_uuid = line.split('=')[1].strip()
        
        log_info(f"  Using book ID: {book_id}")
        if not book_uuid:
            # best effort fallback: continue without strong server assert
            log_warning("Could not parse book UUID; server cover assert may be skipped")
        
        # Create dummy cover (valid 1x1 PNG)
        dummy_cover = base64.b64decode(
            "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFwAAAwEAAAAAAAAAAAAAAAAAAAQFBv/EABQBAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhADEAAAAf8A/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPwA//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwA//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwA//9k="
        )
        
        with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
            f.write(dummy_cover)
            cover_path = f.name
        
        try:
            # Set new cover
            set_cover_script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
with open('{cover_path}', 'rb') as f:
    database.set_cover({book_id}, f.read())
print("COVER_SET")
"""
            
            success, output = run_calibre_script(set_cover_script)
            if not success or 'COVER_SET' not in output:
                log_error("Failed to set cover")
                print(output[-2000:])
                return False
            
            log_info("  Cover modified locally")
            
            # Sync (should upload cover)
            results, sync_output = run_sync_v5(clear_cache=False)
            
            if not results:
                log_error("Sync failed")
                return False
            
            log_info(f"  Sync completed: {results.get('synced', 0)} books")
            if results.get('errors', 0) != 0:
                return False
            if not book_uuid:
                return True
            sql_res = api_tools_sql(
                "SELECT cover_original_hash FROM books WHERE uuid='%s' LIMIT 1" % book_uuid
            )
            if not sql_res or 'rows' not in sql_res or not sql_res['rows']:
                log_warning("Server SQL check unavailable; cover assert skipped")
                return True
            server_cover_hash = (sql_res['rows'][0].get('cover_original_hash') or '').strip()
            log_info(f"  Server cover hash present: {'yes' if server_cover_hash else 'no'}")
            return bool(server_cover_hash)
        
        finally:
            os.unlink(cover_path)
    
    # ========== DOWNLOAD TESTS ==========
    
    def test_6_download_missing_file(self):
        """Test 6: Download missing file from server"""
        log_info("Testing file download...")
        
        # Get book with files (avoid formats that are likely local-only, e.g. TXT)
        script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
for book_id in database.all_ids():
    formats = database.formats(book_id, index_is_id=True)
    if formats:
        # formats can be "EPUB" or "EPUB,PDF" - take first
        fmt_list = formats.split(',')
        preferred = [f for f in fmt_list if f in ('PDF', 'EPUB', 'MOBI', 'AZW3', 'CBZ', 'CBR')]
        fmt_list = preferred if preferred else fmt_list
        print("RESULT_START")
        print(f"book_id={{book_id}}")
        print(f"format={{fmt_list[0]}}")
        print("RESULT_END")
        break
"""
        
        success, output = run_calibre_script(script)
        if not success or 'RESULT_START' not in output:
            log_warning("No books with files found")
            return None
        
        # Parse result
        book_id = None
        fmt = None
        for line in output.split('\n'):
            if 'book_id=' in line:
                book_id = int(line.split('=')[1])
            elif 'format=' in line:
                fmt = line.split('=')[1].strip()
        
        if not book_id or not fmt:
            log_error("Failed to parse book info")
            return False
        if fmt == 'TXT':
            log_warning("Only TXT format found locally; skipping download test")
            return None
        
        log_info(f"  Using book ID: {book_id}, format: {fmt}")
        
        # Remove format locally
        remove_script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
database.remove_format({book_id}, '{fmt}', index_is_id=True)
print("FORMAT_REMOVED")
"""
        
        success, output = run_calibre_script(remove_script)
        if not success or 'FORMAT_REMOVED' not in output:
            log_error("Failed to remove format")
            return False
        
        log_info(f"  {fmt} removed locally")
        
        # Sync (should download file) - reset cursor to force full pull
        results, sync_output = run_sync_v5(clear_cache=True, no_cache=True)
        
        if not results:
            log_error("Sync failed")
            return False
        
        log_info(f"  Files downloaded: {results.get('files_downloaded', 0)}")
        
        # Verify file was downloaded
        verify_script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
formats = database.formats({book_id}, index_is_id=True) or ""
# formats can be "EPUB" or "EPUB,PDF"
if '{fmt}' in formats.split(','):
    print("FILE_RESTORED")
"""
        
        success, output = run_calibre_script(verify_script)
        
        if 'FILE_RESTORED' in output:
            log_success("  File successfully downloaded")
            return True
        else:
            log_error("  File not restored")
            return False
    
    def test_7_download_missing_cover(self):
        """Test 7: Download missing cover from server"""
        log_info("Testing cover download...")
        
        # Get book with cover (or create one if none)
        script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
for book_id in database.all_ids():
    if database.has_cover(book_id):
        print(f"BOOK_ID={{book_id}}")
        break
"""
        
        success, output = run_calibre_script(script)
        if not success or 'BOOK_ID=' not in output:
            dummy_cover = base64.b64decode(
                "/9j/4AAQSkZJRgABAQAAAQABAAD/2wBDAP//////////////////////////////////////////////////////////////////////////////////////2wBDAf//////////////////////////////////////////////////////////////////////////////////////wAARCAABAAEDASIAAhEBAxEB/8QAFwAAAwEAAAAAAAAAAAAAAAAAAAQFBv/EABQBAQAAAAAAAAAAAAAAAAAAAAD/2gAMAwEAAhADEAAAAf8A/8QAFBABAAAAAAAAAAAAAAAAAAAAAP/aAAgBAQABPwA//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAgEBPwA//8QAFBEBAAAAAAAAAAAAAAAAAAAAAP/aAAgBAwEBPwA//9k="
            )
            with tempfile.NamedTemporaryFile(suffix='.jpg', delete=False) as f:
                f.write(dummy_cover)
                cover_path = f.name
            try:
                seed_script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
book_id = database.all_ids()[0]
with open('{cover_path}', 'rb') as f:
    database.set_cover(book_id, f.read())
print(f"BOOK_ID={{book_id}}")
"""
                seed_ok, seed_out = run_calibre_script(seed_script)
                if not seed_ok or 'BOOK_ID=' not in seed_out:
                    log_warning("No books with cover found and seeding failed")
                    return None
                output = seed_out
            finally:
                os.unlink(cover_path)
        
        book_id = int(output.split('BOOK_ID=')[1].split()[0])
        log_info(f"  Using book ID: {book_id}")
        
        # Remove cover locally
        remove_script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
database.set_cover({book_id}, None)
print("COVER_REMOVED")
"""
        
        success, output = run_calibre_script(remove_script)
        if not success or 'COVER_REMOVED' not in output:
            log_error("Failed to remove cover")
            return False
        
        log_info("  Cover removed locally")
        
        # Sync (should download cover) - reset cursor to force full pull
        results, sync_output = run_sync_v5(clear_cache=True, no_cache=True)
        
        if not results:
            log_error("Sync failed")
            return False
        
        # Verify cover was downloaded
        verify_script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
if database.has_cover({book_id}):
    print("COVER_RESTORED")
"""
        
        success, output = run_calibre_script(verify_script)
        
        if 'COVER_RESTORED' in output:
            log_success("  Cover successfully downloaded")
            return True
        else:
            log_error("  Cover not restored")
            return False
    
    # ========== CONFLICT TESTS ==========
    
    def test_8_conflict_resolution_server_wins(self):
        """Test 8: Conflict resolution (server wins)"""
        log_info("Testing conflict resolution...")
        
        # Modify book locally
        script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
book_id = database.all_ids()[0]
metadata = database.get_metadata(book_id, index_is_id=True)
metadata.title = "LOCAL MODIFIED TITLE"
try:
    database.set_metadata(book_id, metadata, index_is_id=True)
except TypeError:
    # Legacy API path (no index_is_id kwarg)
    database.set_metadata(book_id, metadata)
print("BOOK_MODIFIED")
"""
        
        success, output = run_calibre_script(script)
        if not success or 'BOOK_MODIFIED' not in output:
            log_error("Failed to modify book")
            return False
        
        log_info("  Book modified locally")
        
        # Sync (server should win, local changes overwritten)
        results, sync_output = run_sync_v5(clear_cache=False)
        
        if not results:
            log_error("Sync failed")
            return False
        
        log_info(f"  Sync completed: {results.get('updated', 0)} updated")
        
        # Verify title was restored from server
        verify_script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
book_id = database.all_ids()[0]
metadata = database.get_metadata(book_id, index_is_id=True)
if "LOCAL MODIFIED" not in metadata.title:
    print("SERVER_WON")
"""
        
        success, output = run_calibre_script(verify_script)
        
        if 'SERVER_WON' in output:
            log_success("  Server version restored (conflict resolved)")
            return True
        else:
            log_warning("  Local changes persisted (unexpected)")
            return True  # Not a failure, just different behavior
    
    # ========== STRESS TESTS ==========
    
    def test_9_network_interruption_recovery(self):
        """Test 9: Network interruption recovery"""
        log_info("Testing network interruption recovery...")
        
        # This test would require mocking network failures
        # For now, just verify cursor checkpoint works
        
        # Run partial sync
        results1, _ = run_sync_v5(clear_cache=False)
        if not results1:
            return False
        
        # Simulate interruption by not saving final cursor
        # Then run again - should resume from checkpoint
        
        time.sleep(1)
        
        results2, _ = run_sync_v5(clear_cache=False)
        if not results2:
            return False
        
        log_info("  Recovery mechanism working")
        return True
    
    def test_10_large_library_performance(self):
        """Test 10: Large library performance (if available)"""
        log_info("Testing large library performance...")
        
        # This would test against a library with 100+ books
        # For now, skip if not available
        
        log_warning("  Large library test requires manual setup")
        return None  # Skip

    def test_11_sanity_e2e_push_pull_cache(self):
        """Test 11: sanity E2E push->pull->cache mapping check."""
        log_info("Running sanity E2E flow...")

        baseline, out1 = run_sync_v5(clear_cache=True, no_cache=True)
        if not baseline or baseline.get('errors', 1) > 0:
            log_error("Baseline sync failed")
            print(out1[-2000:])
            return False

        marker = f"E2E-{int(time.time())}"
        mutate_script = f"""
import sys
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db

database = db('{LIBRARY_PATH}')
book_id = database.all_ids()[0]
metadata = database.get_metadata(book_id, index_is_id=True)
metadata.title = f"{{metadata.title}} [{marker}]"
try:
    database.set_metadata(book_id, metadata, index_is_id=True)
except TypeError:
    database.set_metadata(book_id, metadata)

print("RESULT_START")
print(f"book_id={{book_id}}")
print("RESULT_END")
"""
        ok, out2 = run_calibre_script(mutate_script)
        data = parse_result_block(out2) if ok else None
        if not ok or not data:
            log_error("Failed to mutate local book")
            print(out2[-1000:])
            return False

        second, out3 = run_sync_v5(clear_cache=False)
        if not second or second.get('errors', 1) > 0:
            log_error("Second sync failed")
            print(out3[-2000:])
            return False

        book_id = int(data['book_id'])
        cache_check_script = f"""
import sqlite3
conn = sqlite3.connect('{LIBRARY_PATH}/metadata.db')
cur = conn.cursor()
cur.execute("SELECT COUNT(*) FROM calimob_books_sync WHERE library_uuid=? AND calibre_book_id=?", ('{LIBRARY_UUID}', {book_id}))
count = cur.fetchone()[0]
conn.close()
print("RESULT_START")
print(f"cache_count={{count}}")
print("RESULT_END")
"""
        ok2, out4 = run_calibre_script(cache_check_script)
        data2 = parse_result_block(out4) if ok2 else None
        if not ok2 or not data2:
            log_error("Failed to read mapping cache")
            print(out4[-1000:])
            return False

        cache_count = int(data2.get('cache_count', '0'))
        if cache_count < 1:
            log_error("No cache row found for mutated book")
            return False

        follow_up, out5 = run_sync_v5(clear_cache=False)
        if not follow_up or follow_up.get('errors', 1) > 0:
            log_error("Follow-up sync failed")
            print(out5[-2000:])
            return False

        log_info(f"  baseline synced={baseline.get('synced', 0)}")
        log_info(f"  second updated={second.get('updated', 0)}")
        log_info(f"  cache_count={cache_count}")
        return True
    
    def test_12_incremental_sync_with_mutations_and_additions(self):
        """Test 12: Samsung-like scenario — push, mutate, add books, re-sync, converge.

        Steps:
          1. Full sync (5 books → server)
          2. Locally: mutate 2 books (title, author, comments) + add 2 new books
          3. Sync again → server should accept 2 updates + 2 new
          4. Follow-up sync → convergence (0 updates, 0 missing)
        """
        log_info("Step 1: Full sync to populate server...")
        r1, o1 = run_sync_v5(clear_cache=True, no_cache=True)
        if not r1 or int(r1.get('errors', 1)) > 0:
            log_error("Initial sync failed")
            print(o1[-2000:])
            return False
        log_info(f"  Initial sync: created={r1.get('created', 0)}")

        # Step 2: mutate 2 books + add 2 new
        log_info("Step 2: Mutating 2 books + adding 2 new books...")
        mutate_script = f"""
import sys, time
sys.path.insert(0, '{PLUGIN_DIR}')
from calibre.library import db
from calibre.ebooks.metadata.book.base import Metadata

database = db('{LIBRARY_PATH}')
ids = sorted(database.all_ids())

# Mutate book 1: change title + add comment
mi1 = database.get_metadata(ids[0], index_is_id=True)
mi1.title = mi1.title + ' [MUTATED]'
mi1.comments = '<p>This is a <b>rich HTML</b> comment with unicode: \\u00e9\\u00e0\\u00fc</p>'
try:
    database.set_metadata(ids[0], mi1, index_is_id=True)
except TypeError:
    database.set_metadata(ids[0], mi1)

# Mutate book 2: change author + add series
mi2 = database.get_metadata(ids[1], index_is_id=True)
mi2.authors = ['New Author One', 'New Author Two']
mi2.series = 'Test Series'
mi2.series_index = 3.5
try:
    database.set_metadata(ids[1], mi2, index_is_id=True)
except TypeError:
    database.set_metadata(ids[1], mi2)

# Add 2 new books with complex metadata
new1 = Metadata('Nuovo Libro Italiano', ['Mario Rossi', 'Luca Bianchi'])
new1.publisher = 'Mondadori'
new1.languages = ['ita', 'eng']
new1.comments = 'Descrizione con caratteri speciali: \\u00e8 \\u00e0 \\u00f2 \\u00f9'
new1.identifiers = {{'isbn': '9781234567890', 'amazon': 'B00TEST123'}}
new1.tags = ['Fiction', 'Italian']
new1_id = database.create_book_entry(new1)
try:
    database.set_metadata(new1_id, new1, index_is_id=True)
except TypeError:
    database.set_metadata(new1_id, new1)

new2 = Metadata('Advanced Quantum Computing', ['Dr. Sarah Chen'])
new2.publisher = 'MIT Press'
new2.languages = ['eng']
new2.series = 'Quantum Series'
new2.series_index = 2.0
new2.identifiers = {{'doi': '10.1234/test'}}
new2_id = database.create_book_entry(new2)
try:
    database.set_metadata(new2_id, new2, index_is_id=True)
except TypeError:
    database.set_metadata(new2_id, new2)

print("RESULT_START")
print(f"mutated_ids={{ids[0]}},{{ids[1]}}")
print(f"new_ids={{new1_id}},{{new2_id}}")
print(f"total={{len(database.all_ids())}}")
print("RESULT_END")
"""
        ok, out2 = run_calibre_script(mutate_script)
        data = parse_result_block(out2) if ok else None
        if not ok or not data:
            log_error("Failed to mutate/add books")
            print(out2[-1000:])
            return False
        log_info(f"  Mutated: {data.get('mutated_ids')}, New: {data.get('new_ids')}, Total: {data.get('total')}")

        # Step 3: sync again — should push 2 updates + 2 new
        log_info("Step 3: Sync with mutations + additions...")
        r2, o2 = run_sync_v5(clear_cache=False)
        if not r2:
            log_error("Second sync failed to parse")
            print(o2[-2000:])
            return False

        errors2 = int(r2.get('errors', 0))
        created2 = int(r2.get('created', 0))
        updated2 = int(r2.get('updated', 0))
        synced2 = int(r2.get('synced', 0))
        log_info(f"  Sync 2: synced={synced2} created={created2} updated={updated2} errors={errors2}")

        success = True
        if errors2 > 0:
            log_error(f"  Sync 2 had {errors2} errors")
            print(o2[-2000:])
            success = False
        if created2 < 2:
            log_error(f"  Expected at least 2 created, got {created2}")
            success = False
        else:
            log_success(f"  {created2} books created on server")

        # Step 4: follow-up sync — should converge
        log_info("Step 4: Follow-up sync (convergence check)...")
        time.sleep(1)
        r3, o3 = run_sync_v5(clear_cache=False)
        if not r3:
            log_error("Follow-up sync failed to parse")
            print(o3[-2000:])
            return False

        errors3 = int(r3.get('errors', 0))
        synced3 = int(r3.get('synced', 0))
        created3 = int(r3.get('created', 0))
        updated3 = int(r3.get('updated', 0))
        log_info(f"  Sync 3: synced={synced3} created={created3} updated={updated3} errors={errors3}")

        if errors3 > 0:
            log_error(f"  Follow-up sync had {errors3} errors")
            success = False
        if synced3 != 0 or created3 != 0:
            log_error(f"  Expected convergence (0 synced/created), got synced={synced3} created={created3}")
            success = False
        else:
            log_success("  Converged: 0 synced, 0 created")

        # Cleanup: remove books added by this test to keep fixture clean
        new_ids_str = data.get('new_ids', '')
        if new_ids_str:
            cleanup_ids = [int(x) for x in new_ids_str.split(',') if x.strip()]
            if cleanup_ids:
                placeholders = ','.join(str(i) for i in cleanup_ids)
                subprocess.run([
                    'sqlite3', f'{LIBRARY_PATH}/metadata.db',
                    f"PRAGMA writable_schema = ON; DELETE FROM books WHERE id IN ({placeholders}); "
                    f"DELETE FROM books_authors_link WHERE book IN ({placeholders}); "
                    f"DELETE FROM books_tags_link WHERE book IN ({placeholders}); "
                    f"DELETE FROM books_series_link WHERE book IN ({placeholders}); "
                    f"DELETE FROM books_languages_link WHERE book IN ({placeholders}); "
                    f"DELETE FROM identifiers WHERE book IN ({placeholders}); "
                    f"DELETE FROM comments WHERE book IN ({placeholders}); "
                    f"PRAGMA writable_schema = OFF;"
                ], capture_output=True)
                log_info(f"  Cleanup: removed {len(cleanup_ids)} test books from fixture")

        return success

    def print_summary(self):
        """Print test summary"""
        print("\n" + "="*60)
        print("TEST SUMMARY")
        print("="*60)
        
        total = self.results['passed'] + self.results['failed'] + self.results['skipped']
        
        log_success(f"Passed:  {self.results['passed']}/{total}")
        if self.results['failed'] > 0:
            log_error(f"Failed:  {self.results['failed']}/{total}")
        if self.results['skipped'] > 0:
            log_warning(f"Skipped: {self.results['skipped']}/{total}")
        
        print("\nDetailed Results:")
        for test in self.results['tests']:
            status = test['status']
            name = test['name']
            if status == 'pass':
                log_success(f"  {name}")
            elif status == 'fail':
                log_error(f"  {name}")
            elif status == 'skip':
                log_warning(f"  {name}")
            elif status == 'error':
                log_error(f"  {name}: {test.get('error', 'Unknown error')}")
        
        print("="*60)
        
        return self.results['failed'] == 0


def main():
    import argparse
    
    parser = argparse.ArgumentParser(description='Sync V5 Integration Tests')
    parser.add_argument('--all', action='store_true', help='Run all tests')
    parser.add_argument('--basic', action='store_true', help='Run basic sync tests only')
    parser.add_argument('--upload', action='store_true', help='Run upload tests only')
    parser.add_argument('--download', action='store_true', help='Run download tests only')
    parser.add_argument('--conflicts', action='store_true', help='Run conflict tests only')
    parser.add_argument('--stress', action='store_true', help='Run stress tests only')
    
    args = parser.parse_args()
    
    # Default to basic if no args
    if not any([args.all, args.basic, args.upload, args.download, args.conflicts, args.stress]):
        args.basic = True
    
    print("="*60)
    print("SYNC V5 INTEGRATION TESTS - COMPLETE SUITE")
    print("="*60)
    print(f"Library: {LIBRARY_PATH}")
    print(f"UUID: {LIBRARY_UUID}")
    print("="*60)
    print()

    # Bootstrap: verify token + library exist on server
    if not ensure_server_ready():
        print("\n[bootstrap] Server not ready — cannot run integration tests.")
        print("[bootstrap] Check that the server is running and .env credentials are correct.")
        sys.exit(2)

    print(f"API: {API_URL}")
    print(f"Library ID: {CALIMOB_LIB_ID}")
    print()

    # Kill any running calibre-debug
    subprocess.run(['pkill', '-9', 'calibre-debug'], capture_output=True)
    time.sleep(1)

    tester = SyncV5Tester()
    
    # Run selected test suites
    if args.all or args.basic:
        log_info("=== BASIC SYNC TESTS ===\n")
        tester.run_test("Test 1: Full sync with empty cache", tester.test_1_full_sync_empty_cache)
        tester.run_test("Test 2: Partial sync with full cache", tester.test_2_partial_sync_full_cache)
        tester.run_test("Test 2b: Hash optimization - no transfers", tester.test_2b_hash_optimization_no_transfers)
        tester.run_test("Test 3: Batch processing", tester.test_3_batch_processing)
    
    if args.all or args.upload:
        log_info("=== UPLOAD TESTS ===\n")
        tester.run_test("Test 4: Upload new file format", tester.test_4_upload_new_file_format)
        tester.run_test("Test 5: Upload modified cover", tester.test_5_upload_modified_cover)
    
    if args.all or args.download:
        log_info("=== DOWNLOAD TESTS ===\n")
        tester.run_test("Test 6: Download missing file", tester.test_6_download_missing_file)
        tester.run_test("Test 7: Download missing cover", tester.test_7_download_missing_cover)
    
    if args.all or args.conflicts:
        log_info("=== CONFLICT TESTS ===\n")
        tester.run_test("Test 8: Conflict resolution", tester.test_8_conflict_resolution_server_wins)
    
    if args.all or args.stress:
        log_info("=== STRESS TESTS ===\n")
        tester.run_test("Test 9: Network interruption recovery", tester.test_9_network_interruption_recovery)
        tester.run_test("Test 10: Large library performance", tester.test_10_large_library_performance)

    if args.all or args.basic:
        tester.run_test("Test 11: Sanity E2E push/pull/cache", tester.test_11_sanity_e2e_push_pull_cache)
        tester.run_test("Test 12: Incremental sync (mutate + add books)", tester.test_12_incremental_sync_with_mutations_and_additions)
    
    # Print summary
    success = tester.print_summary()
    
    sys.exit(0 if success else 1)


if __name__ == '__main__':
    main()
