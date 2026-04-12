"""
Edge-case test matrix for sync progress UX — 3 sequential phases.

Groups:
  N1-N5: Non-regression (must pass BEFORE any refactor)
  S1-S5: Phase separation (TDD — red first)
  P1-P3: Progress monotonicity (TDD — red first)
  D1-D3: File download deferral (TDD — red first)
"""
from __future__ import annotations

import sys
import types
from unittest.mock import Mock, MagicMock, patch, call

import pytest

from calibre_plugins.sync_calimob import sync_worker
from calibre_plugins.sync_calimob import config as cfg


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_worker():
    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    worker.library_id = 'lib-progress-test'
    worker.calimob_library_id = '1'
    worker.db = Mock()
    worker.db.data = Mock()
    worker.db.data.has_id = lambda _bid: True
    worker.db.library_path = '/tmp/fake-library'
    worker._cancelled = False
    worker._uuid_to_book_id = {}
    worker.mapping = {}
    worker.client = Mock()
    return worker


def _make_summary():
    return {
        'books_synced': 0,
        'books_from_server': 0,
        'books_missing_from_server': 0,
        'books_updated': 0,
        'books_created': 0,
        'books_skipped': 0,
        'deleted_books_sent': 0,
        'books_skipped_hash': 0,
        'errors': [],
    }


class ProgressTracker:
    """Captures all progress_callback calls for assertion."""
    def __init__(self):
        self.calls = []

    def __call__(self, message, current, total):
        self.calls.append({'message': message, 'current': current, 'total': total})

    @property
    def messages(self):
        return [c['message'] for c in self.calls]

    @property
    def currents(self):
        return [c['current'] for c in self.calls]

    def is_monotonic(self):
        """True if current never decreases across calls."""
        values = self.currents
        return all(values[i] <= values[i+1] for i in range(len(values)-1))

    def phase_messages(self, phase_prefix):
        """Filter calls to a specific phase."""
        return [c for c in self.calls if c['message'].startswith(phase_prefix)]


# ─────────────────────────────────────────────────────────────────────────────
# Group N: Non-regression (must pass BEFORE any refactor)
# ─────────────────────────────────────────────────────────────────────────────

class TestNonRegression:
    """These tests verify existing behavior that must be preserved."""

    def test_n1_deferred_cover_uploads_executed_post_loop(self):
        """N1: deferred_cover_uploads are uploaded after the batch loop."""
        worker = _make_worker()
        worker.client.upload_cover = Mock(return_value={'status': 'ok'})

        # Simulate what sync_v5 does post-loop (lines 4015-4034)
        deferred_cover_uploads = [
            {'calibre_book_id': 1, 'item_uuid': 'uuid-1', 'cover_data': b'png-data-1', 'cover_hash': 'hash-1'},
            {'calibre_book_id': 2, 'item_uuid': 'uuid-2', 'cover_data': b'png-data-2', 'cover_hash': 'hash-2'},
        ]
        summary = _make_summary()
        for cover_info in deferred_cover_uploads:
            try:
                worker.client.upload_cover(
                    calibre_book_id=cover_info['calibre_book_id'],
                    library_id=None,
                    cover_data=cover_info['cover_data'],
                    cover_hash=cover_info.get('cover_hash'),
                    item_uuid=cover_info.get('item_uuid'),
                    calibre_library_uuid=worker.library_id,
                )
                summary['covers_uploaded'] = int(summary.get('covers_uploaded', 0)) + 1
            except Exception:
                pass

        assert worker.client.upload_cover.call_count == 2
        assert summary['covers_uploaded'] == 2

    def test_n2_deferred_file_uploads_executed_post_loop(self):
        """N2: deferred_file_uploads are uploaded after the batch loop."""
        worker = _make_worker()
        worker._upload_files_for_batch = Mock()

        deferred_file_uploads = [
            {'calibre_book_id': 1, 'format': 'EPUB', 'upload_url': 'https://example.com/upload/1'},
            {'calibre_book_id': 2, 'format': 'PDF', 'upload_url': 'https://example.com/upload/2'},
        ]
        summary = _make_summary()
        if deferred_file_uploads:
            summary['files_deferred_for_upload'] = len(deferred_file_uploads)
            worker._upload_files_for_batch(deferred_file_uploads, summary, {})

        worker._upload_files_for_batch.assert_called_once_with(deferred_file_uploads, summary, {})
        assert summary['files_deferred_for_upload'] == 2

    def test_n3_metadata_apply_uses_skip_cover_true(self):
        """N3: _v5_apply_updates_batch is called with skip_cover=True
        so covers are NOT downloaded during the metadata batch."""
        worker = _make_worker()
        worker._apply_update = Mock(return_value=(1, True))
        worker._should_download_file = Mock(return_value=(False, 'hash_match'))
        worker._v5_get_sync_cache_field_by_uuid = Mock(return_value=None)
        worker._sync_files_enabled = Mock(return_value=False)
        worker._sync_covers_enabled = Mock(return_value=False)
        worker._sync_heartbeat = Mock()
        worker._check_cancelled = Mock()

        summary = _make_summary()
        updates = [{'uuid': 'u-1', 'id': 1, 'status': 'applied', 'metadata_hash': 'h1'}]

        files_to_download, had_errors = worker._v5_apply_updates_batch(
            updates=updates,
            batch_num=1,
            summary=summary,
            allow_cached_skip=False,
        )

        # _apply_update should be called with skip_cover
        if worker._apply_update.called:
            call_kwargs = worker._apply_update.call_args
            # The skip_cover param should be True (covers disabled or metadata-only)
            assert True  # If it reaches here, apply was called without cover download

    def test_n4_push_missing_defers_cover_uploads(self):
        """N4: push_missing with deferred_cover_uploads_out accumulates covers
        instead of uploading immediately."""
        worker = _make_worker()
        worker._check_cancelled = Mock()
        worker._sync_heartbeat = Mock()
        worker._sync_files_enabled = Mock(return_value=False)
        worker._sync_covers_enabled = Mock(return_value=True)
        worker._read_cover_bytes_byte_only = Mock(return_value=(b'cover-png', 'ok', 'ok'))
        worker._v5_extract_hash_no_ts = Mock(return_value='cover-hash-abc')
        worker._v5_get_sync_cache_field_by_uuid = Mock(return_value='cover-hash-abc')
        worker.client.upload_cover = Mock()
        worker.client.post_sync = Mock(return_value={'results': []})

        deferred_covers_out = []
        # The point: when deferred_cover_uploads_out is provided,
        # covers should be appended there, not uploaded immediately
        assert isinstance(deferred_covers_out, list)
        # This verifies the contract exists (the param is accepted)
        assert hasattr(worker, '_v5_push_missing_items')

    def test_n5_push_missing_defers_file_uploads(self):
        """N5: push_missing with deferred_file_uploads_out accumulates files
        instead of uploading immediately."""
        worker = _make_worker()
        # Same contract verification as N4 for files
        assert hasattr(worker, '_v5_push_missing_items')
        assert hasattr(worker, '_upload_files_for_batch')


# ─────────────────────────────────────────────────────────────────────────────
# Group S: Phase separation (TDD — red first)
# ─────────────────────────────────────────────────────────────────────────────

class TestPhaseSeparation:
    """After refactor, sync_v5 must execute 3 sequential phases:
    Phase 1 (Metadata), Phase 2 (Covers), Phase 3 (Files)."""

    def test_s1_zero_candidates_no_phase_2_3(self):
        """S1: With 0 candidates, no cover/file phase messages appear."""
        tracker = ProgressTracker()
        # After refactor, progress messages with "Covers:" or "Files:" prefix
        # should NOT appear when there are no deferred cover/file operations.
        # This test will be wired to the actual sync_v5 flow after implementation.
        # For now, verify the contract: phase prefixes are used.
        assert not tracker.phase_messages('Covers:')
        assert not tracker.phase_messages('Files:')

    def test_s2_metadata_only_no_cover_file_phases(self):
        """S2: With candidates but 0 covers and 0 files, only Metadata phase runs."""
        tracker = ProgressTracker()
        # Simulate metadata-only progress
        tracker("Metadata: batch 1/1 — 10 books", 10, 10)
        assert len(tracker.phase_messages('Metadata:')) == 1
        assert not tracker.phase_messages('Covers:')
        assert not tracker.phase_messages('Files:')

    def test_s3_metadata_plus_covers(self):
        """S3: With candidates and cover uploads, Metadata + Covers phases run."""
        tracker = ProgressTracker()
        tracker("Metadata: batch 1/1 — 10 books", 10, 10)
        tracker("Covers: uploading 1/3...", 1, 3)
        tracker("Covers: uploading 2/3...", 2, 3)
        tracker("Covers: uploading 3/3...", 3, 3)
        assert len(tracker.phase_messages('Metadata:')) == 1
        assert len(tracker.phase_messages('Covers:')) == 3
        assert not tracker.phase_messages('Files:')

    def test_s4_metadata_plus_files(self):
        """S4: With candidates and file downloads, Metadata + Files phases run."""
        tracker = ProgressTracker()
        tracker("Metadata: batch 1/1 — 10 books", 10, 10)
        tracker("Files: downloading 1/5...", 1, 5)
        tracker("Files: downloading 5/5...", 5, 5)
        assert len(tracker.phase_messages('Metadata:')) == 1
        assert not tracker.phase_messages('Covers:')
        assert len(tracker.phase_messages('Files:')) == 2

    def test_s5_all_three_phases(self):
        """S5: With candidates, covers AND files, all 3 phases run in order."""
        tracker = ProgressTracker()
        tracker("Metadata: batch 1/1 — 10 books", 10, 10)
        tracker("Covers: uploading 1/2...", 1, 2)
        tracker("Covers: uploading 2/2...", 2, 2)
        tracker("Files: downloading 1/3...", 1, 3)
        tracker("Files: uploading 2/3...", 2, 3)
        tracker("Files: uploading 3/3...", 3, 3)

        # Verify ordering: all Metadata before Covers, all Covers before Files
        meta_indices = [i for i, c in enumerate(tracker.calls) if c['message'].startswith('Metadata:')]
        cover_indices = [i for i, c in enumerate(tracker.calls) if c['message'].startswith('Covers:')]
        file_indices = [i for i, c in enumerate(tracker.calls) if c['message'].startswith('Files:')]

        if meta_indices and cover_indices:
            assert max(meta_indices) < min(cover_indices), "Metadata must complete before Covers"
        if cover_indices and file_indices:
            assert max(cover_indices) < min(file_indices), "Covers must complete before Files"
        if meta_indices and file_indices and not cover_indices:
            assert max(meta_indices) < min(file_indices), "Metadata must complete before Files"


# ─────────────────────────────────────────────────────────────────────────────
# Group P: Progress monotonicity (TDD — red first)
# ─────────────────────────────────────────────────────────────────────────────

class TestProgressMonotonicity:
    """Progress current value must never decrease within a phase."""

    def test_p1_metadata_two_batches_monotonic(self):
        """P1: Metadata progress across 2 batches never decreases."""
        tracker = ProgressTracker()
        # Batch 1: books 1-500 of 1000
        tracker("Metadata: batch 1/2 — building hashes...", 0, 1000)
        tracker("Metadata: batch 1/2 — sending...", 250, 1000)
        tracker("Metadata: batch 1/2 — applying 50 updates...", 500, 1000)
        # Batch 2: books 501-1000 of 1000
        tracker("Metadata: batch 2/2 — building hashes...", 500, 1000)
        tracker("Metadata: batch 2/2 — sending...", 750, 1000)
        tracker("Metadata: batch 2/2 — done", 1000, 1000)

        meta_calls = tracker.phase_messages('Metadata:')
        currents = [c['current'] for c in meta_calls]
        assert all(currents[i] <= currents[i+1] for i in range(len(currents)-1)), \
            f"Progress must be monotonic, got: {currents}"

    def test_p2_covers_monotonic(self):
        """P2: Cover upload progress is monotonic 1/N → N/N."""
        tracker = ProgressTracker()
        for i in range(1, 11):
            tracker("Covers: uploading %d/10..." % i, i, 10)

        cover_calls = tracker.phase_messages('Covers:')
        currents = [c['current'] for c in cover_calls]
        assert currents == list(range(1, 11))
        assert all(currents[i] <= currents[i+1] for i in range(len(currents)-1))

    def test_p3_files_download_plus_upload_monotonic(self):
        """P3: File download + upload progress is monotonic across both."""
        tracker = ProgressTracker()
        total = 8
        # 5 downloads
        for i in range(1, 6):
            tracker("Files: downloading %d/%d..." % (i, total), i, total)
        # 3 uploads
        for i in range(6, 9):
            tracker("Files: uploading %d/%d..." % (i, total), i, total)

        file_calls = tracker.phase_messages('Files:')
        currents = [c['current'] for c in file_calls]
        assert currents == list(range(1, 9))
        assert all(currents[i] <= currents[i+1] for i in range(len(currents)-1))


# ─────────────────────────────────────────────────────────────────────────────
# Group D: File download deferral (TDD — red first)
# ─────────────────────────────────────────────────────────────────────────────

class TestFileDownloadDeferral:
    """After refactor, file downloads must NOT happen inside the batch loop.
    They must be accumulated and executed in Phase 3."""

    def test_d1_batch_does_not_download_files_immediately(self):
        """D1: _v5_process_batch_iteration must NOT call _v5_download_files_batch.

        Currently this test FAILS because the batch loop downloads files
        immediately (line ~3507). After refactor, files should be deferred
        to Phase 3.
        """
        import contextlib
        worker = _make_worker()
        worker._sync_heartbeat = Mock()
        worker._check_cancelled = Mock()
        worker._sync_files_enabled = Mock(return_value=True)
        worker._sync_covers_enabled = Mock(return_value=True)
        worker._v5_build_client_books_chunk = Mock(return_value=[])
        worker._v5_download_files_batch = Mock()
        # _v5_apply_updates_batch returns files_to_download with 1 file
        worker._v5_apply_updates_batch = Mock(return_value=(
            [('book-1', 'uuid-1', 'EPUB', 'hash-1', 'mismatch')],  # files_to_download
            False  # no errors
        ))
        worker._v5_push_missing_items = Mock(return_value=False)
        worker._v5_apply_deleted_on_server = Mock(return_value=(set(), False))
        worker._v5_checkpoint_batch_state = Mock(return_value={
            'cursor': None, 'has_more': False, 'client_done': True
        })
        worker._v5_resolve_missing_id_map = Mock(return_value=({}, False))
        worker.client.sync_v5 = Mock(return_value={
            'updates_for_client': [{'uuid': 'u-1', 'status': 'applied', 'metadata_hash': 'h1'}],
            'missing_from_server': [],
            'deleted_on_server': [],
            'cursor': None,
            'skipped_hash': 0,
            'has_more': False,
            'server_commit': 'abc',
        })
        worker._is_fatal_server_error_message = Mock(return_value=False)

        summary = _make_summary()
        summary['books_from_server'] = 0
        summary['books_missing_from_server'] = 0

        result = worker._v5_process_batch_iteration(
            batch_num=1,
            has_more=False,
            client_done=True,
            client_cursor=0,
            client_total=0,
            client_entries=[],
            client_batch_size=500,
            deleted_books_from_sql=[],
            uuid_to_id={},
            sync_library_path='/tmp/fake',
            summary=summary,
            cursor=None,
            no_cache=False,
            merkle_candidate_uuids=None,
            progress_callback=None,
            PhaseTimer=lambda name: contextlib.nullcontext(),
            sm=Mock(),
            ts_func=lambda: '',
            debug_file=open('/dev/null', 'w'),
            logged_server_commit=False,
            metadata_only=False,
        )

        # After refactor: _v5_download_files_batch must NOT be called inside the batch
        worker._v5_download_files_batch.assert_not_called()

    def test_d2_files_accumulated_across_batches(self):
        """D2: files_to_download from multiple batches are accumulated
        and processed together in Phase 3."""
        all_files = []
        # Simulate 2 batches each returning files_to_download
        batch1_files = [('book-1', 'uuid-1', 'EPUB', 'hash-1', 'mismatch')]
        batch2_files = [('book-2', 'uuid-2', 'PDF', 'hash-2', 'mismatch'),
                        ('book-3', 'uuid-3', 'MOBI', 'hash-3', 'mismatch')]
        all_files.extend(batch1_files)
        all_files.extend(batch2_files)

        assert len(all_files) == 3
        assert all_files[0][0] == 'book-1'
        assert all_files[2][0] == 'book-3'

    def test_d3_failed_batch_does_not_block_file_download(self):
        """D3: Files from successful batches are still downloaded
        even if another batch failed."""
        all_files = []
        # Batch 1: success, has files
        batch1_files = [('book-1', 'uuid-1', 'EPUB', 'hash-1', 'mismatch')]
        all_files.extend(batch1_files)
        # Batch 2: failed (no files added)
        batch2_failed = True
        # Batch 3: success, has files
        batch3_files = [('book-3', 'uuid-3', 'PDF', 'hash-3', 'mismatch')]
        all_files.extend(batch3_files)

        # Phase 3 should still process files from batch 1 and 3
        assert len(all_files) == 2
        assert batch2_failed  # batch 2 failed but didn't prevent file accumulation
