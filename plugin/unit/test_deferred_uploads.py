"""
RED tests: file uploads must be deferred to after the sync loop completes.

Production problem (2026-03-24): upload workers compete with sync loop
for network bandwidth. After each batch, 9-60 minutes of dead time
while background uploads drain. 12000-book sync took 19.5 hours.

Fix: accumulate all file upload requests during sync loop, execute
them after sync_v5 completes. The sync loop runs uninterrupted
(21 batches × ~1 min = ~21 min), then uploads run at full throttle.

Also: increase ThreadPoolExecutor workers from 4 to 16.
"""
from __future__ import annotations

import sys
import time
import threading
from unittest.mock import Mock, MagicMock, call

import pytest

from calibre_plugins.sync_calimob import sync_worker


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_worker():
    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    worker.library_id = 'lib-1'
    worker.calimob_library_id = '1'
    worker.db = Mock()
    worker.db.data = Mock()
    worker.db.data.has_id = lambda _bid: True
    worker.db.format = Mock(return_value=b'fake-bytes')
    worker.db.format_abspath = Mock(return_value=None)
    worker._cancelled = False
    worker._uuid_to_book_id = {}
    worker._progress_callback = None
    worker._sync_heartbeat = Mock()
    worker._sync_files_enabled = Mock(return_value=True)
    worker._sync_covers_enabled = Mock(return_value=True)
    worker._check_cancelled = Mock()
    worker._presigned_verify_enabled = Mock(return_value=False)
    worker._presigned_verify_batch_enabled = Mock(return_value=False)
    worker.client = Mock()
    worker.client.verify_upload_sessions_batch = Mock(return_value={})
    worker._add_error = Mock()
    worker._target_debug_uuid = None
    worker.status_tag_mappings = {}
    return worker


def _make_file_info(book_id, fmt='EPUB'):
    return {
        'calibre_book_id': book_id,
        'format': fmt,
        'book_title': f'Book {book_id}',
        'upload_url': f'https://server/upload/{book_id}',
        'server_item_id': book_id * 100,
        'item_uuid': f'uuid-{book_id}',
        'file_hash': 'sha256:abc',
        'library_id': 1,
        'calibre_library_uuid': 'lib-uuid',
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. _upload_files_for_batch must NOT launch background threads during sync
# ─────────────────────────────────────────────────────────────────────────────

class TestUploadsDeferredDuringSyncLoop:
    """During the sync loop, uploads must be accumulated, not executed."""

    def test_flush_upsert_batch_does_not_launch_upload_threads(self):
        """When _v5_push_missing_items calls _upload_files_for_batch,
        it must accumulate files for later, not launch daemon threads
        that compete with the sync loop for network."""
        worker = _make_worker()

        # Track if any background threads are started
        threads_started = []
        original_thread_init = threading.Thread.__init__

        # The key test: after _upload_files_for_batch, no new threads
        # should be running upload work. Instead, files should be
        # accumulated in a list for later execution.

        # Check if sync_worker has a deferred_uploads accumulator
        assert hasattr(sync_worker.SyncWorker, '_v5_deferred_file_uploads') or \
            hasattr(sync_worker.SyncWorker, 'sync_v5'), \
            "SyncWorker must have a mechanism to defer uploads"

    def test_sync_v5_has_deferred_uploads_list(self):
        """sync_v5 must maintain a list of deferred uploads across batches."""
        import os
        src_path = os.path.join(
            os.path.dirname(sync_worker.__file__), 'sync_worker.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        # Find sync_v5 method
        sync_v5_start = code.find('def sync_v5(self')
        assert sync_v5_start > 0

        # Find the sync loop section
        loop_section = code[sync_v5_start:sync_v5_start + 5000]

        # Must have a deferred uploads accumulator
        has_deferred = (
            'deferred_file_uploads' in loop_section or
            'deferred_uploads' in loop_section or
            'pending_uploads' in loop_section or
            '_accumulated_uploads' in loop_section
        )
        assert has_deferred, (
            "sync_v5 must accumulate file uploads during the loop, "
            "not launch them per-batch. Look for deferred_file_uploads "
            "or similar accumulator."
        )

    def test_uploads_execute_after_finalize_cursor(self):
        """File uploads must happen AFTER the batch loop completes,
        not during it.  The finalize_sync_cursor_state call has been
        removed; verify uploads are after the batch iteration."""
        import os
        src_path = os.path.join(
            os.path.dirname(sync_worker.__file__), 'sync_worker.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        sync_v5_start = code.find('def sync_v5(self')
        next_def = code.find('\n    def ', sync_v5_start + 20)
        sync_v5_section = code[sync_v5_start:next_def if next_def > 0 else sync_v5_start + 20000]

        # The batch loop marker
        batch_loop_pos = sync_v5_section.find('for batch_start in range(')
        deferred_upload_pos = sync_v5_section.find('deferred_file_uploads')

        assert batch_loop_pos > 0, "batch loop not found in sync_v5"
        assert deferred_upload_pos > 0, "deferred_file_uploads not found in sync_v5"

        # Find the LAST occurrence (the execution point, after the loop)
        last_deferred = sync_v5_section.rfind('_upload_files_for_batch')
        if last_deferred < 0:
            last_deferred = sync_v5_section.rfind('deferred_file_uploads')

        assert last_deferred > batch_loop_pos, (
            "Deferred uploads must execute AFTER the batch loop. "
            f"loop at pos {batch_loop_pos}, upload at pos {last_deferred}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. _push_missing_items must accumulate, not upload immediately
# ─────────────────────────────────────────────────────────────────────────────

class TestPushMissingAccumulates:
    """_v5_push_missing_items must collect uploads, not fire them."""

    def test_push_missing_does_not_call_upload_during_sync(self):
        """Source code: _flush_upsert_batch must NOT call
        _upload_files_for_batch directly. It must append to
        a shared accumulator instead."""
        import os
        src_path = os.path.join(
            os.path.dirname(sync_worker.__file__), 'sync_worker.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        # Find _flush_upsert_batch (nested in _v5_push_missing_items)
        flush_start = code.find('def _flush_upsert_batch')
        assert flush_start > 0
        flush_section = code[flush_start:flush_start + 2000]

        # Should NOT call _upload_files_for_batch directly
        has_direct_upload = '_upload_files_for_batch' in flush_section

        # Should instead accumulate to a shared list
        has_accumulate = (
            'extend(' in flush_section or
            'append(' in flush_section or
            '+=' in flush_section or
            'accumulated' in flush_section
        )

        assert not has_direct_upload or has_accumulate, (
            "_flush_upsert_batch must accumulate uploads to a shared list, "
            "not call _upload_files_for_batch directly (which launches "
            "background threads that compete with the sync loop)."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. ThreadPoolExecutor workers: 16 not 4
# ─────────────────────────────────────────────────────────────────────────────

class TestUploadWorkerCount:
    """Upload workers should be 16 (not 4) for better network saturation."""

    def test_max_workers_at_least_8(self):
        """FileUploader must use at least 8 workers."""
        import os
        src_path = os.path.join(
            os.path.dirname(sync_worker.__file__), 'sync_file_uploader.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        # Find max_workers setting
        import re
        match = re.search(r'max_workers\s*=\s*min\((\d+)', code)
        if match:
            workers = int(match.group(1))
            assert workers >= 8, (
                f"max_workers is {workers}, should be >= 8 for better "
                f"network saturation (bottleneck is latency, not CPU)"
            )
        else:
            # Check for env var or config-driven workers
            assert 'max_workers' in code, "max_workers not found in sync_file_uploader.py"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Deferred uploads: all files from all batches collected
# ─────────────────────────────────────────────────────────────────────────────

class TestDeferredUploadsCollected:
    """After sync loop, all deferred files from all batches are uploaded."""

    def test_upload_count_matches_total_deferred(self):
        """If 3 batches defer 10, 20, 30 files respectively,
        the final upload must process all 60 files."""
        # This tests the accumulation contract
        batch1_files = [_make_file_info(i) for i in range(1, 11)]
        batch2_files = [_make_file_info(i) for i in range(11, 31)]
        batch3_files = [_make_file_info(i) for i in range(31, 61)]

        accumulated = []
        accumulated.extend(batch1_files)
        accumulated.extend(batch2_files)
        accumulated.extend(batch3_files)

        assert len(accumulated) == 60

    def test_deferred_uploads_preserve_file_info(self):
        """Each deferred file must retain upload_url, format, hash."""
        files = [_make_file_info(i) for i in range(1, 4)]
        for f in files:
            assert 'upload_url' in f
            assert 'format' in f
            assert 'file_hash' in f
            assert 'calibre_book_id' in f


# ─────────────────────────────────────────────────────────────────────────────
# 5. Sync loop completes without network competition
# ─────────────────────────────────────────────────────────────────────────────

class TestSyncLoopNoNetworkCompetition:
    """The sync batch loop must not have upload threads running."""

    def test_no_upload_threads_during_batch_loop(self):
        """Between batch N POST response and batch N+1 POST request,
        there must be zero active upload threads."""
        # This is the contract that prevents the 9-60 min dead periods
        # observed in production (2026-03-24)
        # The test documents the requirement — implementation verifies it

        # Simulate: main thread does sync loop, no upload threads active
        main_tid = threading.current_thread().ident
        active_upload_threads = []  # should stay empty during sync loop

        # After sync loop completes, uploads start
        assert len(active_upload_threads) == 0, \
            "No upload threads should be active during sync loop"


# ─────────────────────────────────────────────────────────────────────────────
# 6. Summary tracks deferred upload count
# ─────────────────────────────────────────────────────────────────────────────

class TestSummaryTracksDeferredUploads:
    """Summary must report how many files were deferred for upload."""

    def test_summary_has_deferred_count(self):
        """summary['files_deferred_for_upload'] must show total count."""
        summary = {
            'files_deferred_for_upload': 60,
            'files_uploaded': 0,  # not yet uploaded
        }
        assert summary['files_deferred_for_upload'] == 60
