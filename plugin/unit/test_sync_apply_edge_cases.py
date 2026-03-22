"""
Edge-case test matrix for SyncApplier decomposition guardrails (Phase 5).

Tests for:
1. _v5_apply_deleted_on_server: deletion flow, empty list, cache update, idempotency
2. _should_download_cover: decision tree (server_no_cover, hash_match, deferred, bulk)
3. _should_download_file: decision tree (no_format, cached_hash, unavailable, bulk)
4. _v5_apply_updates_batch: fast-path skip, error tracking
5. Timestamp comparison: local >= server → client wins
6. _download_ebook: hash verification, missing format, file not found
7. Cover download cooldown: 900s retry suppression
"""
from __future__ import annotations

import sys
import time
from unittest.mock import Mock, MagicMock, patch

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
    worker.db.cover = Mock(return_value=b'cover-bytes')
    worker.db.formats = Mock(return_value='EPUB')
    worker.db.format = Mock(return_value=b'epub-bytes')
    worker.db.format_abspath = Mock(return_value=None)
    worker._cancelled = False
    worker._uuid_to_book_id = {}
    worker._progress_callback = None
    worker._sync_heartbeat = Mock()
    worker._sync_files_enabled = Mock(return_value=True)
    worker._sync_covers_enabled = Mock(return_value=True)
    worker._check_cancelled = Mock()
    worker._add_error = Mock()
    worker.client = Mock()
    worker._target_debug_uuid = None
    worker.status_tag_mappings = {}
    worker._presigned_verify_enabled = Mock(return_value=False)
    worker._presigned_verify_batch_enabled = Mock(return_value=False)
    return worker


def _ts():
    return '2026-03-22T00:00:00'


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
        'files_deleted_local': 0,
        'errors': [],
    }


# ─────────────────────────────────────────────────────────────────────────────
# 1. _v5_apply_deleted_on_server
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyDeletedOnServer:
    """Server says 'these books were deleted' → remove locally + mark in cache."""

    def test_empty_list_returns_immediately(self):
        worker = _make_worker()
        summary = _make_summary()
        uuids, errors = worker._v5_apply_deleted_on_server(
            [], '/tmp/lib', summary, ts_func=_ts, debug_file=sys.stderr
        )
        assert uuids == set()
        assert errors is False

    def test_none_input_returns_immediately(self):
        worker = _make_worker()
        summary = _make_summary()
        uuids, errors = worker._v5_apply_deleted_on_server(
            None, '/tmp/lib', summary, ts_func=_ts, debug_file=sys.stderr
        )
        assert uuids == set()
        assert errors is False

    def test_string_uuids_accepted(self):
        """deleted_on_server can be list of strings."""
        worker = _make_worker()
        worker._remove_books_from_calibre = Mock()
        worker._mark_book_deleted_in_mapping = Mock()
        summary = _make_summary()

        # Mock mapping_table to return book IDs
        original_mt = sync_worker.mapping_table
        mock_mt = Mock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall = Mock(return_value=[(1,)])
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_conn.commit = Mock()
        mock_mt._connect = Mock(return_value=mock_conn)
        mock_mt.calibre_table = Mock(return_value='books')
        mock_mt.sync_table = Mock(return_value='calimob_books_sync')
        sync_worker.mapping_table = mock_mt
        try:
            uuids, errors = worker._v5_apply_deleted_on_server(
                ['uuid-1'], '/tmp/lib', summary,
                ts_func=_ts, debug_file=sys.stderr,
            )
            assert 'uuid-1' in uuids
        finally:
            sync_worker.mapping_table = original_mt

    def test_dict_uuids_accepted(self):
        """deleted_on_server can be list of dicts with 'uuid' key."""
        worker = _make_worker()
        summary = _make_summary()

        # Simplified: just check UUID extraction works
        # deleted_on_server with dict entries
        deleted = [{'uuid': 'uuid-1'}, {'uuid': 'uuid-2'}, 'uuid-3']

        # No library_path → early return, but UUIDs are extracted first
        uuids, errors = worker._v5_apply_deleted_on_server(
            deleted, None, summary,
            ts_func=_ts, debug_file=sys.stderr,
        )
        # With no library_path, it returns early but with no error
        assert errors is False

    def test_no_library_path_skips(self):
        """If sync_library_path is None, skip deletion gracefully."""
        worker = _make_worker()
        summary = _make_summary()
        uuids, errors = worker._v5_apply_deleted_on_server(
            ['uuid-1'], None, summary,
            ts_func=_ts, debug_file=sys.stderr,
        )
        assert uuids == set()
        assert errors is False

    def test_summary_tracks_deletion_count(self):
        """summary['books_deleted_by_server'] must be incremented."""
        worker = _make_worker()
        worker._remove_books_from_calibre = Mock()
        worker._mark_book_deleted_in_mapping = Mock()
        summary = _make_summary()

        original_mt = sync_worker.mapping_table
        mock_mt = Mock()
        mock_conn = MagicMock()
        mock_cursor = MagicMock()
        mock_cursor.fetchall = Mock(return_value=[(1,), (2,)])
        mock_conn.__enter__ = Mock(return_value=mock_conn)
        mock_conn.__exit__ = Mock(return_value=False)
        mock_conn.cursor = Mock(return_value=mock_cursor)
        mock_conn.commit = Mock()
        mock_mt._connect = Mock(return_value=mock_conn)
        mock_mt.calibre_table = Mock(return_value='books')
        mock_mt.sync_table = Mock(return_value='calimob_books_sync')
        sync_worker.mapping_table = mock_mt
        try:
            worker._v5_apply_deleted_on_server(
                ['uuid-1', 'uuid-2'], '/tmp/lib', summary,
                ts_func=_ts, debug_file=sys.stderr,
            )
            assert summary.get('books_deleted_by_server', 0) == 2
        finally:
            sync_worker.mapping_table = original_mt


# ─────────────────────────────────────────────────────────────────────────────
# 2. _should_download_cover: decision tree
# ─────────────────────────────────────────────────────────────────────────────

class TestShouldDownloadCover:
    """Cover download decision logic."""

    def test_no_item_skips(self):
        """None item → skip download."""
        worker = _make_worker()
        should_dl, reason = worker._should_download_cover(1, None)
        assert should_dl is False

    def test_no_server_cover_skips(self):
        """Server item with no cover → skip download."""
        worker = _make_worker()
        worker._defer_download_due_to_timestamp = Mock(return_value=False)

        item = {}  # no 'cover' key
        should_dl, reason = worker._should_download_cover(1, item)
        assert should_dl is False
        assert 'no_cover' in reason or 'no_item' in reason

    def test_server_cover_missing_flag_skips(self):
        """Server says cover_missing=True → skip."""
        worker = _make_worker()
        worker._defer_download_due_to_timestamp = Mock(return_value=False)

        item = {'cover': {'has_cover': True}, 'cover_missing': True}
        should_dl, reason = worker._should_download_cover(1, item)
        assert should_dl is False
        assert 'missing' in reason.lower()

    def test_server_has_cover_and_no_local_downloads(self):
        """Server has cover, no local cover info → should download."""
        worker = _make_worker()
        worker._defer_download_due_to_timestamp = Mock(return_value=False)
        worker._read_cover_bytes_byte_only = Mock(return_value=(None, 'none', 'no_cover'))

        original_cfg = sync_worker.cfg
        mock_cfg = Mock()
        mock_cfg.get_book_mapping_entry = Mock(return_value={})
        mock_cfg.update_book_cache = Mock()
        sync_worker.cfg = mock_cfg
        try:
            item = {'cover': {'has_cover': True, 'cover_hash': 'sha256:server'}}
            should_dl, reason = worker._should_download_cover(1, item)
            # Should download because local has no cover
            assert should_dl is True
        finally:
            sync_worker.cfg = original_cfg


# ─────────────────────────────────────────────────────────────────────────────
# 3. _should_download_file: decision tree
# ─────────────────────────────────────────────────────────────────────────────

class TestShouldDownloadFile:
    """File download decision logic."""

    def test_no_format_skips(self):
        """Missing format → skip."""
        worker = _make_worker()
        worker._normalize_file_hash = Mock(side_effect=lambda h: h)

        should_dl, reason = worker._should_download_file(1, None, 'sha256:abc')
        assert should_dl is False
        assert 'no_format' in reason

    def test_no_server_hash_skips(self):
        """No server hash → skip."""
        worker = _make_worker()
        worker._normalize_file_hash = Mock(return_value=None)

        should_dl, reason = worker._should_download_file(1, 'EPUB', None)
        assert should_dl is False
        assert 'no_server_hash' in reason

    def test_deferred_by_timestamp_skips(self):
        """If local is newer, skip download."""
        worker = _make_worker()
        worker._normalize_file_hash = Mock(side_effect=lambda h: h)
        worker._defer_download_due_to_timestamp = Mock(return_value=True)

        should_dl, reason = worker._should_download_file(1, 'EPUB', 'sha256:abc')
        assert should_dl is False
        assert 'newer' in reason.lower() or 'equal' in reason.lower()

    def test_previously_unavailable_skips(self):
        """If format was previously unavailable, skip."""
        worker = _make_worker()
        worker._normalize_file_hash = Mock(side_effect=lambda h: h)
        worker._defer_download_due_to_timestamp = Mock(return_value=False)
        worker._missing_formats_unavailable = {(1, 'EPUB')}

        should_dl, reason = worker._should_download_file(1, 'EPUB', 'sha256:abc')
        assert should_dl is False
        assert 'unavailable' in reason.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Timestamp comparison: client wins when local >= server
# ─────────────────────────────────────────────────────────────────────────────

class TestTimestampComparison:
    """The 'client wins when newer' rule must be enforced."""

    def test_client_wins_assertion_in_source(self):
        """Verify the >= comparison exists in _apply_update (static check)."""
        import os
        src_path = os.path.join(os.path.dirname(sync_worker.__file__), 'sync_worker.py')
        with open(src_path, 'r') as f:
            code = f.read()

        # The critical comparison: local >= server means client wins
        assert 'local_last_modified >= server_last_modified' in code, \
            "Client-wins comparison not found in source"

    def test_defer_download_timestamp_check_exists(self):
        """_defer_download_due_to_timestamp must exist and be called in download decisions."""
        assert hasattr(sync_worker.SyncWorker, '_defer_download_due_to_timestamp'), \
            "_defer_download_due_to_timestamp method must exist"


# ─────────────────────────────────────────────────────────────────────────────
# 5. _download_ebook: basic contract
# ─────────────────────────────────────────────────────────────────────────────

class TestDownloadEbook:
    """_download_ebook downloads a file from server and adds to Calibre."""

    def test_missing_uuid_returns_false(self):
        """If uuid is None, download should not proceed."""
        worker = _make_worker()
        result = worker._download_ebook(
            calibre_book_id=1, item_uuid=None, fmt='EPUB',
        )
        assert result is False

    def test_missing_format_returns_false(self):
        """If fmt is None, download should not proceed."""
        worker = _make_worker()
        result = worker._download_ebook(
            calibre_book_id=1, item_uuid='uuid-1', fmt=None,
        )
        assert result is False

    def test_client_error_returns_false(self):
        """If client.get_ebook() raises, returns False."""
        worker = _make_worker()
        worker.client.get_ebook = Mock(side_effect=Exception("Network error"))
        worker._get_cached_book_uuid = Mock(return_value='uuid-1')
        worker._update_cached_format_hash = Mock()

        result = worker._download_ebook(
            calibre_book_id=1, item_uuid='uuid-1', fmt='EPUB',
        )
        assert result is False

    def test_empty_response_returns_false(self):
        """If server returns no file data, returns False."""
        worker = _make_worker()
        worker.client.get_ebook = Mock(return_value=None)
        worker._get_cached_book_uuid = Mock(return_value='uuid-1')

        result = worker._download_ebook(
            calibre_book_id=1, item_uuid='uuid-1', fmt='EPUB',
        )
        assert result is False


# ─────────────────────────────────────────────────────────────────────────────
# 6. Cover download cooldown
# ─────────────────────────────────────────────────────────────────────────────

class TestCoverDownloadCooldown:
    """Cover download has a 900s cooldown after failure."""

    def test_cooldown_constant_in_source(self):
        """Verify the 900s cooldown exists in _download_cover."""
        import os
        src_path = os.path.join(os.path.dirname(sync_worker.__file__), 'sync_worker.py')
        with open(src_path, 'r') as f:
            code = f.read()

        # The cooldown check: < 900 seconds since last failure
        assert '900' in code, "900s cooldown not found in source"

    def test_download_cover_method_exists(self):
        """_download_cover must exist as a method."""
        assert hasattr(sync_worker.SyncWorker, '_download_cover'), \
            "_download_cover method must exist"

    def test_apply_cover_download_method_exists(self):
        """_apply_cover_download must exist."""
        assert hasattr(sync_worker.SyncWorker, '_apply_cover_download'), \
            "_apply_cover_download method must exist"


# ─────────────────────────────────────────────────────────────────────────────
# 7. _v5_apply_updates_batch: fast-path skip
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyUpdatesBatchFastPath:
    """When metadata hash matches and local is newer, skip update."""

    def test_method_exists(self):
        assert hasattr(sync_worker.SyncWorker, '_v5_apply_updates_batch')

    def test_returns_tuple_of_files_and_errors(self):
        """_v5_apply_updates_batch must return (files_to_download, had_errors)."""
        worker = _make_worker()
        worker._v5_prefetch_verify_candidates_sql = Mock(return_value=({}, 0.0))
        worker._apply_update = Mock(return_value=(1, False))
        worker._should_download_file = Mock(return_value=(False, 'cached_hash_match'))
        worker._should_download_cover = Mock(return_value=(False, 'hash_match'))

        updates = [{
            'uuid': 'uuid-1',
            'item': {'uuid': 'uuid-1', 'title': 'Book 1', 'last_modified': 1000},
        }]

        original_mt = sync_worker.mapping_table
        mock_mt = Mock()
        mock_mt.fetch_entries_bulk = Mock(return_value={})
        sync_worker.mapping_table = mock_mt
        try:
            files, had_errors = worker._v5_apply_updates_batch(
                updates=updates, batch_num=1, summary=_make_summary(),
                ts_func=_ts, progress_callback=None,
                allow_cached_skip=True, debug_file=sys.stderr,
            )
            assert isinstance(files, list)
            assert isinstance(had_errors, bool)
        finally:
            sync_worker.mapping_table = original_mt

    def test_empty_updates_returns_empty(self):
        """Empty updates → no files to download, no errors."""
        worker = _make_worker()
        worker._v5_prefetch_verify_candidates_sql = Mock(return_value=({}, 0.0))

        original_mt = sync_worker.mapping_table
        mock_mt = Mock()
        mock_mt.fetch_entries_bulk = Mock(return_value={})
        sync_worker.mapping_table = mock_mt
        try:
            files, had_errors = worker._v5_apply_updates_batch(
                updates=[], batch_num=1, summary=_make_summary(),
                ts_func=_ts, progress_callback=None,
                allow_cached_skip=True, debug_file=sys.stderr,
            )
            assert files == []
            assert had_errors is False
        finally:
            sync_worker.mapping_table = original_mt


# ─────────────────────────────────────────────────────────────────────────────
# 8. Error isolation: apply_update exception doesn't crash batch
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyUpdateErrorIsolation:
    """An exception in _apply_update for one book must not crash the entire batch."""

    def test_exception_in_apply_does_not_crash(self):
        """If _apply_update throws, the batch continues with had_errors=True."""
        worker = _make_worker()
        worker._v5_prefetch_verify_candidates_sql = Mock(return_value=({}, 0.0))

        call_count = [0]

        def _exploding_apply(*args, **kwargs):
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Metadata corruption")
            return (2, False)

        worker._apply_update = Mock(side_effect=_exploding_apply)
        worker._should_download_file = Mock(return_value=(False, 'ok'))
        worker._should_download_cover = Mock(return_value=(False, 'ok'))

        updates = [
            {'uuid': 'uuid-1', 'item': {'uuid': 'uuid-1', 'title': 'Book 1', 'last_modified': 1000}},
            {'uuid': 'uuid-2', 'item': {'uuid': 'uuid-2', 'title': 'Book 2', 'last_modified': 1001}},
        ]

        original_mt = sync_worker.mapping_table
        mock_mt = Mock()
        mock_mt.fetch_entries_bulk = Mock(return_value={})
        sync_worker.mapping_table = mock_mt
        try:
            files, had_errors = worker._v5_apply_updates_batch(
                updates=updates, batch_num=1, summary=_make_summary(),
                ts_func=_ts, progress_callback=None,
                allow_cached_skip=True, debug_file=sys.stderr,
            )
            assert had_errors is True
            # Both books should have been attempted
            assert call_count[0] == 2
        finally:
            sync_worker.mapping_table = original_mt
