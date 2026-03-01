#!/usr/bin/env python3
"""
Integration test: server-side file removal should delete local format on sync.

Requires env:
  CALIMOB_TEST_LIBRARY_PATH
  CALIMOB_TEST_LIBRARY_UUID
  CALIMOB_TEST_CALIMOB_LIB_ID
  CALIMOB_TEST_BOOK_ID
  CALIMOB_TEST_FORMAT

Optional:
  CALIMOB_TEST_PRECMD  (shell command to delete file on server before sync)

Usage:
  python3 tests/test_sync_v5_file_deletion.py
"""

import os
import subprocess
import sys
import tempfile

CALIBRE_DEBUG = "/Applications/calibre.app/Contents/MacOS/calibre-debug"


def fail(msg):
    print(msg, file=sys.stderr)
    sys.exit(1)


library_path = os.getenv("CALIMOB_TEST_LIBRARY_PATH")
library_uuid = os.getenv("CALIMOB_TEST_LIBRARY_UUID")
calimob_lib_id = os.getenv("CALIMOB_TEST_CALIMOB_LIB_ID")
book_id = os.getenv("CALIMOB_TEST_BOOK_ID")
fmt = os.getenv("CALIMOB_TEST_FORMAT")
precmd = os.getenv("CALIMOB_TEST_PRECMD")

if not all([library_path, library_uuid, calimob_lib_id, book_id, fmt]):
    print("Missing required env. See header.")
    sys.exit(0)

if precmd:
    result = subprocess.run(precmd, shell=True)
    if result.returncode != 0:
        fail("Pre-command failed")

script = f"""
import sys
sys.path.insert(0, '{os.path.dirname(os.path.dirname(os.path.abspath(__file__)))}')
from sync_worker import SyncWorker
from calibre.library import db

database = db('{library_path}')
worker = SyncWorker(None, database, '{library_uuid}', '{calimob_lib_id}')

before = database.formats(int({book_id}), index_is_id=True)
summary = worker.sync_v5()
after = database.formats(int({book_id}), index_is_id=True)

print('RESULT_START')
print(f"before={{before}}")
print(f"after={{after}}")
print('RESULT_END')
"""

with tempfile.NamedTemporaryFile(mode='w', suffix='.py', delete=False) as f:
    f.write(script)
    script_path = f.name

try:
    result = subprocess.run([CALIBRE_DEBUG, '-e', script_path], capture_output=True, text=True, timeout=180)
    output = result.stdout + result.stderr
    if 'RESULT_START' not in output or 'RESULT_END' not in output:
        fail("No result markers in output")
    block = output.split('RESULT_START', 1)[1].split('RESULT_END', 1)[0]
    before_line = [l for l in block.splitlines() if l.startswith('before=')]
    after_line = [l for l in block.splitlines() if l.startswith('after=')]
    if not before_line or not after_line:
        fail("Missing before/after")
    before_val = before_line[0].split('=', 1)[1]
    after_val = after_line[0].split('=', 1)[1]
    print(f"before={before_val}")
    print(f"after={after_val}")
    if fmt.upper() in before_val and fmt.upper() in after_val:
        fail("Format still present after sync")
finally:
    os.unlink(script_path)
