"""
Tests for fire-and-forget file/cover uploads.

Upload operations must NOT block the sync main thread.
_upload_files_for_batch and _upload_covers_batch should launch work
in a background thread and return immediately.
"""
from __future__ import annotations

import time
import threading
from unittest.mock import Mock, MagicMock

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
    worker.db.format = Mock(return_value=b'fake-bytes')
    worker.db.format_abspath = Mock(return_value=None)
    worker.db.cover = Mock(return_value=b'cover-bytes')
    worker._cancelled = False
    worker._progress_callback = None
    worker._presigned_verify_enabled = Mock(return_value=True)
    worker._presigned_verify_batch_enabled = Mock(return_value=False)
    worker._add_error = Mock()
    worker.client = Mock()
    worker.client.verify_upload_sessions_batch = Mock(return_value={})
    return worker


def _make_file_info(book_id, fmt='EPUB'):
    return {
        'calibre_book_id': book_id,
        'format': fmt,
        'book_title': f'Book {book_id}',
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
# Fire-and-forget: _upload_files_for_batch returns immediately
# ─────────────────────────────────────────────────────────────────────────────

class TestFileUploadFireAndForget:

    def test_returns_immediately_while_uploads_continue(self):
        """_upload_files_for_batch must return in < 1s even if uploads are slow."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 11)]  # 10 files
        summary = _make_summary()

        upload_started = threading.Event()
        upload_gate = threading.Event()

        def _slow_upload(file_info, fc):
            upload_started.set()
            upload_gate.wait(timeout=10)  # block until test releases
            return {'success': True, 'step': 'success',
                    'book_id': file_info['calibre_book_id'], 'format': 'EPUB',
                    'upload_size': 100, 'file_hash': 'h',
                    'response': {'session_id': f'sess-{file_info["calibre_book_id"]}',
                                 'status': 'uploaded_unverified'}}

        worker._upload_file = Mock(side_effect=_slow_upload)

        start = time.time()
        worker._upload_files_for_batch(files, summary, {})
        elapsed = time.time() - start

        # Must return immediately (< 1s), not wait for slow uploads
        assert elapsed < 1.0, f"Took {elapsed:.2f}s — should return immediately"

        # Uploads should still be running in background
        assert upload_started.wait(timeout=5), "Upload thread never started"

        # Release the gate so background threads can finish
        upload_gate.set()
        # Give background time to clean up
        time.sleep(0.2)

    def test_background_uploads_complete_eventually(self):
        """Uploads launched in background must eventually complete."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 4)]
        summary = _make_summary()

        completed = []

        def _track_upload(file_info, fc):
            time.sleep(0.05)
            completed.append(file_info['calibre_book_id'])
            return {'success': True, 'step': 'success',
                    'book_id': file_info['calibre_book_id'], 'format': 'EPUB',
                    'upload_size': 100, 'file_hash': 'h',
                    'response': {'session_id': f'sess-{file_info["calibre_book_id"]}',
                                 'status': 'uploaded_unverified'}}

        worker._upload_file = Mock(side_effect=_track_upload)

        worker._upload_files_for_batch(files, summary, {})

        # Wait for background to finish
        deadline = time.time() + 5
        while len(completed) < 3 and time.time() < deadline:
            time.sleep(0.1)

        assert len(completed) == 3, f"Only {len(completed)}/3 uploads completed"

    def test_empty_list_returns_immediately(self):
        """Empty file list must return instantly, no background thread."""
        worker = _make_worker()
        summary = _make_summary()

        start = time.time()
        worker._upload_files_for_batch([], summary, {})
        elapsed = time.time() - start

        assert elapsed < 0.1


# ─────────────────────────────────────────────────────────────────────────────
# Fire-and-forget: _upload_covers_batch returns immediately
# ─────────────────────────────────────────────────────────────────────────────

class TestCoverUploadFireAndForget:

    def test_returns_immediately_while_covers_upload(self):
        """_upload_covers_batch must return in < 1s even if uploads are slow."""
        worker = _make_worker()

        cover_started = threading.Event()
        cover_gate = threading.Event()

        original_upload = getattr(worker, '_upload_single_batch', None)

        def _slow_cover_upload(*args, **kwargs):
            cover_started.set()
            cover_gate.wait(timeout=10)

        worker._upload_single_batch = Mock(side_effect=_slow_cover_upload)

        covers = [{'data': b'png-bytes', 'book_id': i, 'uuid': f'uuid-{i}'}
                  for i in range(1, 6)]
        summary = _make_summary()

        start = time.time()
        worker._upload_covers_batch(covers, summary)
        elapsed = time.time() - start

        assert elapsed < 1.0, f"Took {elapsed:.2f}s — should return immediately"

        cover_gate.set()
        time.sleep(0.2)


# ─────────────────────────────────────────────────────────────────────────────
# Sync flow doesn't wait for uploads
# ─────────────────────────────────────────────────────────────────────────────

class TestSyncFlowNonBlocking:

    def test_caller_continues_after_upload_launch(self):
        """The code after _upload_files_for_batch must execute immediately."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 6)]
        summary = _make_summary()

        upload_gate = threading.Event()

        def _blocking_upload(file_info, fc):
            upload_gate.wait(timeout=10)
            return {'success': True, 'step': 'success',
                    'book_id': file_info['calibre_book_id'], 'format': 'EPUB',
                    'upload_size': 100, 'file_hash': 'h',
                    'response': {'session_id': 'sess-1', 'status': 'uploaded_unverified'}}

        worker._upload_file = Mock(side_effect=_blocking_upload)

        # Simulate the caller pattern: upload then do more work
        timeline = []

        start = time.time()
        worker._upload_files_for_batch(files, summary, {})
        timeline.append(('after_upload_call', time.time() - start))

        # This represents "save cursor" or other post-upload work
        time.sleep(0.01)
        timeline.append(('after_post_work', time.time() - start))

        # after_upload_call should be < 1s (not waiting for uploads)
        assert timeline[0][1] < 1.0, f"Upload call blocked for {timeline[0][1]:.2f}s"

        upload_gate.set()
        time.sleep(0.2)

    def test_progress_callback_shows_background_status(self):
        """After returning, progress should indicate uploads are in background."""
        worker = _make_worker()
        files = [_make_file_info(i) for i in range(1, 4)]
        summary = _make_summary()

        progress_msgs = []
        worker._progress_callback = lambda msg, cur, tot: progress_msgs.append(msg)

        worker._upload_file = Mock(return_value={
            'success': True, 'step': 'success', 'book_id': 1,
            'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
            'response': {'session_id': 'sess-1', 'status': 'uploaded_unverified'}})

        worker._upload_files_for_batch(files, summary, {})

        # Should have an initial message about background uploads
        assert any('upload' in m.lower() or 'background' in m.lower()
                    for m in progress_msgs), \
            f"No upload/background message in progress: {progress_msgs}"


# ─────────────────────────────────────────────────────────────────────────────
# Error isolation: background upload failure doesn't crash sync
# ─────────────────────────────────────────────────────────────────────────────

class TestBackgroundErrorIsolation:

    def test_upload_crash_does_not_propagate_to_caller(self):
        """If all uploads crash in background, the caller must not see the exception."""
        worker = _make_worker()
        files = [_make_file_info(1)]
        summary = _make_summary()

        worker._upload_file = Mock(side_effect=RuntimeError("catastrophic failure"))

        # Must not raise
        worker._upload_files_for_batch(files, summary, {})

        # Give background time to fail
        time.sleep(0.5)
        # Caller is fine — no exception propagated
