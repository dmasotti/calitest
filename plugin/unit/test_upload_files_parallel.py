"""
Edge-case test matrix for parallel file upload + skip verification polling.

Tests verify that _upload_files_for_batch:
  - Uploads files in parallel (ThreadPoolExecutor)
  - Does NOT poll verification status per-file
  - Fires a single verify-batch at the end (fire-and-forget)
  - Handles partial failures, cancellation, empty lists, progress reporting
"""
from __future__ import annotations

import sys
import time
import threading
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch, call

import pytest

from calibre_plugins.sync_calimob import sync_worker
from calibre_plugins.sync_calimob import rest_client


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_worker():
    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    worker.library_id = 'lib-1'
    worker.calimob_library_id = '1'
    worker.db = Mock()
    worker.db.format = Mock(return_value=b'fake-epub-bytes')
    worker.db.format_abspath = Mock(return_value=None)
    worker._cancelled = False
    worker._progress_callback = None
    worker._presigned_verify_enabled = Mock(return_value=True)
    worker._presigned_verify_batch_enabled = Mock(return_value=False)
    worker.client = Mock()
    return worker


def _make_file_info(book_id, fmt='EPUB', title=None):
    return {
        'calibre_book_id': book_id,
        'format': fmt,
        'book_title': title or f'Book {book_id}',
        'upload_url': f'https://server/api/items/uuid/uuid-{book_id}/files/{fmt.lower()}',
        'server_item_id': book_id * 100,
        'item_uuid': f'uuid-{book_id}',
        'file_hash': f'sha256:{"ab" * 32}',
        'library_id': 1,
        'calibre_library_uuid': 'lib-uuid',
    }


def _make_summary():
    return {
        'files_uploaded': 0,
        'files_failed': 0,
        'file_results': [],
        'errors': [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# Happy path: parallel upload
# ─────────────────────────────────────────────────────────────────────────────

class TestParallelUploadHappyPath:

    def test_multiple_files_uploaded_concurrently(self):
        """Files should be uploaded via ThreadPoolExecutor, not sequentially."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 6)]
        summary = _make_summary()
        file_cache = {}

        upload_thread_ids = []

        def _mock_upload_file(file_info, fc):
            upload_thread_ids.append(threading.current_thread().ident)
            time.sleep(0.05)  # simulate network latency
            return {'success': True, 'step': 'success', 'book_id': file_info['calibre_book_id'],
                    'format': file_info['format'], 'upload_size': 100, 'file_hash': 'h',
                    'response': {'session_id': f'sess-{file_info["calibre_book_id"]}', 'status': 'uploaded_unverified'}}

        worker._upload_file = Mock(side_effect=_mock_upload_file)

        start = time.time()
        worker._upload_files_for_batch(files, summary, file_cache)
        elapsed = time.time() - start

        assert summary['files_uploaded'] == 5
        assert summary['files_failed'] == 0
        # If truly parallel (4 workers), 5 files × 50ms should take ~100ms, not 250ms
        assert elapsed < 0.4, f"Upload took {elapsed:.2f}s — likely still sequential"
        # Must have used multiple threads
        unique_threads = set(upload_thread_ids)
        assert len(unique_threads) > 1, f"Only {len(unique_threads)} thread(s) used — not parallel"

    def test_all_results_collected(self):
        """Results from all parallel uploads must be collected in file_results."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 4)]
        summary = _make_summary()

        worker._upload_file = Mock(return_value={
            'success': True, 'step': 'success', 'book_id': 1,
            'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
            'response': {'session_id': 'sess-1', 'status': 'uploaded_unverified'}})

        worker._upload_files_for_batch(files, summary, {})

        assert len(summary['file_results']) == 3
        assert summary['files_uploaded'] == 3


# ─────────────────────────────────────────────────────────────────────────────
# Verification skip
# ─────────────────────────────────────────────────────────────────────────────

class TestVerificationSkip:

    def test_no_per_file_polling_after_upload(self):
        """After upload, there must be NO polling loop checking verification status."""
        worker = _make_worker()
        files = [_make_file_info(1)]
        summary = _make_summary()

        worker._upload_file = Mock(return_value={
            'success': True, 'step': 'success', 'book_id': 1,
            'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
            'response': {'session_id': 'sess-1', 'status': 'uploaded_unverified'}})

        start = time.time()
        worker._upload_files_for_batch(files, summary, {})
        elapsed = time.time() - start

        # If polling was happening (1s per poll, 120s max), it would take > 1s
        assert elapsed < 1.0, f"Upload took {elapsed:.2f}s — likely polling verification"

    def test_verify_batch_called_after_all_uploads(self):
        """A single verify-batch call should be made at the end with all session_ids."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 4)]
        summary = _make_summary()

        def _fake_upload(file_info, fc):
            return {'success': True, 'step': 'success',
                    'book_id': file_info['calibre_book_id'], 'format': 'EPUB',
                    'upload_size': 100, 'file_hash': 'h',
                    'response': {'session_id': f'sess-{file_info["calibre_book_id"]}',
                                 'status': 'uploaded_unverified'}}

        worker._upload_file = Mock(side_effect=_fake_upload)
        worker.client.verify_upload_sessions_batch = Mock(return_value={'results': [], 'total': 3})

        worker._upload_files_for_batch(files, summary, {})

        worker.client.verify_upload_sessions_batch.assert_called_once()
        call_args = worker.client.verify_upload_sessions_batch.call_args
        session_ids = call_args[0][0] if call_args[0] else call_args[1].get('session_ids', [])
        assert sorted(session_ids) == ['sess-1', 'sess-2', 'sess-3']

    def test_verify_batch_failure_does_not_crash_sync(self):
        """If verify-batch fails (e.g. 500), sync must continue — it's fire-and-forget."""
        worker = _make_worker()
        files = [_make_file_info(1)]
        summary = _make_summary()

        worker._upload_file = Mock(return_value={
            'success': True, 'step': 'success', 'book_id': 1,
            'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
            'response': {'session_id': 'sess-1', 'status': 'uploaded_unverified'}})
        worker.client.verify_upload_sessions_batch = Mock(side_effect=Exception("server 500"))

        # Must not raise
        worker._upload_files_for_batch(files, summary, {})

        assert summary['files_uploaded'] == 1

    def test_no_verify_batch_when_all_already_verified(self):
        """If all uploads return status='verified', no verify-batch is needed."""
        worker = _make_worker()
        files = [_make_file_info(1)]
        summary = _make_summary()

        worker._upload_file = Mock(return_value={
            'success': True, 'step': 'success', 'book_id': 1,
            'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
            'response': {'status': 'verified'}})
        worker.client.verify_upload_sessions_batch = Mock()

        worker._upload_files_for_batch(files, summary, {})

        worker.client.verify_upload_sessions_batch.assert_not_called()

    def test_no_verify_batch_when_no_successful_uploads(self):
        """If all uploads fail, don't call verify-batch."""
        worker = _make_worker()
        files = [_make_file_info(1)]
        summary = _make_summary()

        worker._upload_file = Mock(return_value={
            'success': False, 'step': 'upload', 'error': 'timeout',
            'book_id': 1, 'format': 'EPUB'})
        worker.client.verify_upload_sessions_batch = Mock()

        worker._upload_files_for_batch(files, summary, {})

        worker.client.verify_upload_sessions_batch.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Partial failures
# ─────────────────────────────────────────────────────────────────────────────

class TestPartialFailures:

    def test_one_fails_others_succeed(self):
        """One upload failure must not block or abort the others."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 5)]
        summary = _make_summary()

        def _upload(file_info, fc):
            if file_info['calibre_book_id'] == 3:
                return {'success': False, 'step': 'upload', 'error': 'timeout',
                        'book_id': 3, 'format': 'EPUB'}
            return {'success': True, 'step': 'success', 'book_id': file_info['calibre_book_id'],
                    'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
                    'response': {'session_id': f'sess-{file_info["calibre_book_id"]}',
                                 'status': 'uploaded_unverified'}}

        worker._upload_file = Mock(side_effect=_upload)
        worker.client.verify_upload_sessions_batch = Mock(return_value={})

        worker._upload_files_for_batch(files, summary, {})

        assert summary['files_uploaded'] == 3
        assert summary['files_failed'] == 1
        assert len(summary['file_results']) == 4

    def test_multiple_failures_collected(self):
        """All failures should be collected, not just the first one."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 4)]
        summary = _make_summary()

        worker._upload_file = Mock(return_value={
            'success': False, 'step': 'upload', 'error': 'R2 down',
            'book_id': 1, 'format': 'EPUB'})

        worker._upload_files_for_batch(files, summary, {})

        assert summary['files_failed'] == 3
        assert summary['files_uploaded'] == 0

    def test_exception_in_upload_does_not_crash_batch(self):
        """An unhandled exception in _upload_file must be caught per-file."""
        worker = _make_worker()
        files = [_make_file_info(1), _make_file_info(2)]
        summary = _make_summary()

        call_count = [0]

        def _upload(file_info, fc):
            call_count[0] += 1
            if file_info['calibre_book_id'] == 1:
                raise RuntimeError("unexpected crash")
            return {'success': True, 'step': 'success', 'book_id': 2,
                    'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
                    'response': {'session_id': 'sess-2', 'status': 'uploaded_unverified'}}

        worker._upload_file = Mock(side_effect=_upload)
        worker.client.verify_upload_sessions_batch = Mock(return_value={})

        worker._upload_files_for_batch(files, summary, {})

        # Both files should have been attempted
        assert call_count[0] == 2
        assert summary['files_uploaded'] >= 1
        assert summary['files_failed'] >= 1


# ─────────────────────────────────────────────────────────────────────────────
# Cancellation
# ─────────────────────────────────────────────────────────────────────────────

class TestCancellation:

    def test_cancel_stops_pending_uploads(self):
        """Setting _cancelled should prevent new uploads from starting."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 20)]
        summary = _make_summary()

        started = []

        def _slow_upload(file_info, fc):
            started.append(file_info['calibre_book_id'])
            if len(started) >= 3:
                worker._cancelled = True
            time.sleep(0.02)
            return {'success': True, 'step': 'success',
                    'book_id': file_info['calibre_book_id'], 'format': 'EPUB',
                    'upload_size': 100, 'file_hash': 'h',
                    'response': {'session_id': f'sess-{file_info["calibre_book_id"]}',
                                 'status': 'uploaded_unverified'}}

        worker._upload_file = Mock(side_effect=_slow_upload)
        worker.client.verify_upload_sessions_batch = Mock(return_value={})

        try:
            worker._upload_files_for_batch(files, summary, {})
        except Exception:
            pass

        # Should not have started all 19 uploads
        assert len(started) < 19, f"Started {len(started)} uploads — cancel not respected"


# ─────────────────────────────────────────────────────────────────────────────
# Empty list
# ─────────────────────────────────────────────────────────────────────────────

class TestEmptyList:

    def test_empty_file_list_no_error(self):
        """Empty file list should return immediately without error."""
        worker = _make_worker()
        summary = _make_summary()

        worker._upload_files_for_batch([], summary, {})

        assert summary['files_uploaded'] == 0
        assert summary['files_failed'] == 0
        assert summary['file_results'] == []

    def test_single_file_works(self):
        """Edge case: exactly one file."""
        worker = _make_worker()
        files = [_make_file_info(1)]
        summary = _make_summary()

        worker._upload_file = Mock(return_value={
            'success': True, 'step': 'success', 'book_id': 1,
            'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
            'response': {'session_id': 'sess-1', 'status': 'uploaded_unverified'}})
        worker.client.verify_upload_sessions_batch = Mock(return_value={})

        worker._upload_files_for_batch(files, summary, {})

        assert summary['files_uploaded'] == 1


# ─────────────────────────────────────────────────────────────────────────────
# Progress reporting
# ─────────────────────────────────────────────────────────────────────────────

class TestProgressReporting:

    def test_progress_callback_called_with_count(self):
        """Progress callback must be called as files complete."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 4)]
        summary = _make_summary()

        progress_calls = []
        worker._progress_callback = lambda msg, cur, tot: progress_calls.append((msg, cur, tot))

        worker._upload_file = Mock(return_value={
            'success': True, 'step': 'success', 'book_id': 1,
            'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
            'response': {'session_id': 'sess-1', 'status': 'uploaded_unverified'}})
        worker.client.verify_upload_sessions_batch = Mock(return_value={})

        worker._upload_files_for_batch(files, summary, {})

        assert len(progress_calls) >= 3, f"Expected at least 3 progress calls, got {len(progress_calls)}"
        # Last call should show total
        last_msg, last_cur, last_tot = progress_calls[-1]
        assert last_tot == 3

    def test_progress_includes_initial_message(self):
        """An initial 'Uploading N files...' message should be emitted."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 6)]
        summary = _make_summary()

        progress_calls = []
        worker._progress_callback = lambda msg, cur, tot: progress_calls.append(msg)

        worker._upload_file = Mock(return_value={
            'success': True, 'step': 'success', 'book_id': 1,
            'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
            'response': {'session_id': 'sess-1', 'status': 'uploaded_unverified'}})
        worker.client.verify_upload_sessions_batch = Mock(return_value={})

        worker._upload_files_for_batch(files, summary, {})

        assert any('5' in msg and 'upload' in msg.lower() for msg in progress_calls), \
            f"No initial message mentioning file count: {progress_calls}"
