#!/usr/bin/env python3
"""
Centralized sync runner for tests.

Runs sync_v5 in one of two ways:
- In-process: when the test is already run under calibre-debug -e, sync runs in the
  same process so you can set breakpoints in sync_worker.py.
- Subprocess: when run with plain python3, sync is executed via calibre-debug -e script;
  same (results, output) shape is returned after parsing stdout.

All "how we run sync" logic lives here; test_sync_v5_advanced.py just calls run_sync_v5().
"""

from __future__ import print_function

import os
import subprocess
import sys
import tempfile


def _can_use_calibre():
    """True if we are running inside calibre (e.g. calibre-debug -e)."""
    try:
        from calibre.library import db
        return True
    except Exception:
        return False


def _run_in_process(library_path, library_uuid, calimob_lib_id, plugin_dir, clear_cache):
    """Run sync in current process. Requires calibre environment (run test with calibre-debug -e)."""
    sys.path.insert(0, plugin_dir)
    from sync_worker import SyncWorker
    from calibre.library import db
    if clear_cache:
        subprocess.run([
            'sqlite3', os.path.join(library_path, 'metadata.db'),
            "DELETE FROM calimob_books_sync WHERE library_uuid='%s'" % library_uuid
        ], capture_output=True)
    database = db(library_path)
    worker = SyncWorker(None, database, library_uuid, calimob_lib_id)
    if clear_cache:
        worker.reset_cursor()
    summary = worker.sync_v5()
    results = {
        'synced': summary['books_synced'],
        'created': summary['books_created'],
        'updated': summary['books_updated'],
        'skipped': summary['books_skipped'],
        'skipped_hash': summary['books_skipped_hash'],
        'errors': len(summary['errors']),
        'deleted_books_sent': summary.get('deleted_books_sent', 0),
    }
    return results, "(in-process sync)"


def _run_subprocess(library_path, library_uuid, calimob_lib_id, plugin_dir, calibre_debug_path, clear_cache, debug_show_stderr):
    """Run sync via calibre-debug -e script; parse stdout and return (results, output)."""
    if clear_cache:
        subprocess.run([
            'sqlite3', os.path.join(library_path, 'metadata.db'),
            "DELETE FROM calimob_books_sync WHERE library_uuid='%s'" % library_uuid
        ], capture_output=True)
        reset_script = (
            "import sys\nsys.path.insert(0, %r)\n"
            "from sync_worker import SyncWorker\nfrom calibre.library import db\n"
            "db_obj = db(%r)\nworker = SyncWorker(None, db_obj, %r, %r)\n"
            "worker.reset_cursor()\nprint('CURSOR_RESET_OK')\n"
        ) % (plugin_dir, library_path, library_uuid, calimob_lib_id)
        with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
            f.write(reset_script)
            rpath = f.name
        try:
            subprocess.run([calibre_debug_path, '-e', rpath], capture_output=True, text=True, timeout=30)
        finally:
            try:
                os.unlink(rpath)
            except OSError:
                pass

    script = (
        "import sys\nsys.path.insert(0, %r)\n"
        "from sync_worker import SyncWorker\nfrom calibre.library import db\n"
        "database = db(%r)\nworker = SyncWorker(None, database, %r, %r)\n"
        "summary = worker.sync_v5()\n"
        "print('RESULT_START')\n"
        "print('synced=', summary['books_synced'])\n"
        "print('created=', summary['books_created'])\n"
        "print('updated=', summary['books_updated'])\n"
        "print('skipped=', summary['books_skipped'])\n"
        "print('skipped_hash=', summary['books_skipped_hash'])\n"
        "print('errors=', len(summary['errors']))\n"
        "print('deleted_books_sent=', summary.get('deleted_books_sent', 0))\n"
        "print('RESULT_END')\n"
    ) % (plugin_dir, library_path, library_uuid, calimob_lib_id)

    with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
        f.write(script)
        script_path = f.name
    try:
        result = subprocess.run(
            [calibre_debug_path, '-e', script_path],
            capture_output=True,
            text=True,
            timeout=120
        )
        if result.returncode != 0 or debug_show_stderr:
            if result.stderr:
                print("=== CALIBRE-DEBUG STDERR ===", file=sys.stderr)
                print(result.stderr, file=sys.stderr)
                print("=== END STDERR ===", file=sys.stderr)
        output = (result.stdout or "") + "\n" + (result.stderr or "")
        if 'RESULT_START' in output and 'RESULT_END' in output:
            start = output.index('RESULT_START') + len('RESULT_START')
            end = output.index('RESULT_END')
            result_text = output[start:end].strip()
            results = {}
            for line in result_text.split('\n'):
                if '=' in line:
                    key, value = line.split('=', 1)
                    key, value = key.strip(), value.strip()
                    results[key] = int(value) if value.isdigit() else value
            return results, output
        return None, output
    finally:
        try:
            os.unlink(script_path)
        except OSError:
            pass


def run_sync_v5(
    library_path,
    library_uuid,
    calimob_lib_id,
    plugin_dir,
    calibre_debug_path,
    clear_cache=False,
    in_process=None,
    debug_show_stderr=False,
):
    """
    Run sync_v5 and return (results_dict, output_string).

    - library_path, library_uuid, calimob_lib_id, plugin_dir, calibre_debug_path: config.
    - clear_cache: if True, clear calimob_books_sync and reset cursor before sync.
    - in_process: True = run in current process (for debugging); False = subprocess.
      If None, auto-detect: in_process when already running under calibre (e.g. calibre-debug -e).
    - debug_show_stderr: if True, print subprocess stderr even on success.

    Returns:
      (results, output) where results is dict with synced, created, updated, skipped, skipped_hash, errors, deleted_books_sent;
      or (None, output) if subprocess output could not be parsed.
    """
    if in_process is None:
        in_process = _can_use_calibre()
    if in_process:
        return _run_in_process(library_path, library_uuid, calimob_lib_id, plugin_dir, clear_cache)
    return _run_subprocess(
        library_path, library_uuid, calimob_lib_id, plugin_dir,
        calibre_debug_path, clear_cache, debug_show_stderr
    )
