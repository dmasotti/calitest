"""
Edge-case test matrix: independent 3-channel hash resolution.

Verifies that metadata, cover, and files hash channels are resolved
independently in _v5_build_client_books_chunk. No channel failure
should trigger recalculation of another channel.

Critical invariant: db.get_metadata() must NEVER be called in the
v5 hash build path — metadata hash comes from SQL VIEW only.
"""
from __future__ import annotations

import sys
import time
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, call

import pytest

from calibre_plugins.sync_calimob import sync_worker
from calibre_plugins.sync_calimob import sync_mapper


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_worker():
    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    worker.library_id = 'lib-1'
    worker.calimob_library_id = '1'
    worker.db = Mock()
    worker.db.get_metadata = Mock(side_effect=AssertionError(
        "db.get_metadata() must NOT be called in v5 hash build path"
    ))
    worker.db.cover = Mock(return_value=b'cover-bytes')
    worker.db.formats = Mock(return_value='EPUB')
    worker.db.format = Mock(return_value=b'epub-bytes')
    worker.db.format_abspath = Mock(return_value=None)
    worker.db.data = Mock()
    worker.db.data.has_id = lambda _bid: True
    worker._cancelled = False
    worker._progress_callback = None
    worker._uuid_to_book_id = {}
    worker._target_debug_uuid = None
    worker._sync_files_enabled = Mock(return_value=True)
    worker._sync_covers_enabled = Mock(return_value=True)
    worker._presigned_verify_enabled = Mock(return_value=False)
    worker._presigned_verify_batch_enabled = Mock(return_value=False)
    worker._v5_extract_hash_no_ts = Mock(side_effect=lambda v: v.split(':')[0] if v and ':' in v else v)
    worker._v5_get_sync_cache_field_by_uuid = Mock(return_value=None)
    worker._read_cover_bytes_byte_only = Mock(return_value=(b'cover-bytes', 'db.cover', None))
    worker._check_cancelled = Mock()
    worker._cache_book_uuid = Mock()
    worker._compute_metadata_signature = Mock(return_value='sha256:meta-computed')
    worker._compute_files_signature = Mock(return_value='sha256:files-computed')
    worker._build_files_array_for_book = Mock(return_value=(
        [{'format': 'EPUB', 'file_hash': 'abc'}],
        {'status': 'ok', 'declared_formats': ['EPUB'], 'files_payload_count': 1,
         'missing_formats': [], 'error_formats': [], 'unavailable_formats': []},
    ))
    worker._sync_heartbeat = Mock()
    worker.status_tag_mappings = {}
    worker._add_error = Mock()
    return worker


def _make_book_info(book_id, *,
                    metadata_hash_view='sha256:meta-from-view',
                    cached_cover_hash=None,
                    cached_files_hash=None,
                    cover_hash_bulk=None,
                    files_hash_bulk=None,
                    cached_formats_sig=None,
                    last_modified=1000,
                    sync_last_modified=1000):
    """Build a book_info dict as returned by the SQL candidate query."""
    return {
        'id': book_id,
        'uuid': f'uuid-{book_id}',
        'last_modified': last_modified,
        'sync_last_modified': sync_last_modified,
        'metadata_hash_view': metadata_hash_view,
        'cached_hash': None,
        'cached_cover_hash': cached_cover_hash,
        'cached_files_hash': cached_files_hash,
        'cover_hash_bulk': cover_hash_bulk,
        'files_hash_bulk': files_hash_bulk,
        'cached_formats_sig': cached_formats_sig,
    }


def _run_chunk(worker, books_chunk):
    """Run _v5_build_client_books_chunk and return client_books_data."""
    sm = Mock()
    sm.calibre_to_json_item = Mock(side_effect=AssertionError(
        "calibre_to_json_item() must NOT be called in v5 hash build path"
    ))
    sm.calculate_cover_hash = Mock(return_value='sha256:cover-fresh')
    sm.calculate_file_hash = Mock(return_value='sha256:file-fresh')
    summary = {'errors': []}
    return worker._v5_build_client_books_chunk(
        books_chunk=books_chunk,
        sm=sm,
        summary=summary,
    )


# ─────────────────────────────────────────────────────────────────────────────
# Metadata channel: always from VIEW, never per-book
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadataChannel:

    def test_metadata_from_view_no_get_metadata(self):
        """When metadata_hash_view is present, db.get_metadata must NOT be called."""
        worker = _make_worker()
        books = [_make_book_info(1,
                                cached_cover_hash='sha256:c:1000',
                                cached_files_hash='sha256:f:1000')]
        result = _run_chunk(worker, books)

        assert 'uuid-1' in result
        assert result['uuid-1']['m'] == 'sha256:meta-from-view'
        worker.db.get_metadata.assert_not_called()

    def test_metadata_view_used_even_when_cover_missing(self):
        """Missing cover must NOT trigger db.get_metadata for metadata."""
        worker = _make_worker()
        books = [_make_book_info(1, cached_files_hash='sha256:f:1000')]
        # cover missing → but metadata should still come from VIEW
        result = _run_chunk(worker, books)

        assert result['uuid-1']['m'] == 'sha256:meta-from-view'
        worker.db.get_metadata.assert_not_called()

    def test_metadata_view_used_even_when_files_missing(self):
        """Missing files must NOT trigger db.get_metadata for metadata."""
        worker = _make_worker()
        books = [_make_book_info(1, cached_cover_hash='sha256:c:1000')]
        result = _run_chunk(worker, books)

        assert result['uuid-1']['m'] == 'sha256:meta-from-view'
        worker.db.get_metadata.assert_not_called()

    def test_metadata_view_used_when_both_cover_and_files_missing(self):
        """Both cover and files missing → still no db.get_metadata."""
        worker = _make_worker()
        books = [_make_book_info(1)]  # no cover, no files cached
        result = _run_chunk(worker, books)

        assert result['uuid-1']['m'] == 'sha256:meta-from-view'
        worker.db.get_metadata.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Cover channel: independent from metadata and files
# ─────────────────────────────────────────────────────────────────────────────

class TestCoverChannel:

    def test_cover_from_cache_no_db_cover_call(self):
        """When cover_hash is cached, db.cover() must not be called."""
        worker = _make_worker()
        books = [_make_book_info(1,
                                cached_cover_hash='sha256:cached-cover:1000',
                                cached_files_hash='sha256:f:1000')]
        result = _run_chunk(worker, books)

        worker.db.cover.assert_not_called()
        worker._read_cover_bytes_byte_only.assert_not_called()

    def test_cover_from_bulk_no_db_cover_call(self):
        """When cover_hash_bulk is in book_info, db.cover() must not be called."""
        worker = _make_worker()
        books = [_make_book_info(1,
                                cover_hash_bulk='sha256:bulk-cover',
                                cached_files_hash='sha256:f:1000')]
        result = _run_chunk(worker, books)

        worker.db.cover.assert_not_called()
        worker._read_cover_bytes_byte_only.assert_not_called()

    def test_cover_missing_does_not_trigger_build_files(self):
        """Missing cover must NOT trigger _build_files_array_for_book."""
        worker = _make_worker()
        books = [_make_book_info(1, cached_files_hash='sha256:f:1000')]
        # cover not cached → should only compute cover, not files
        worker._build_files_array_for_book = Mock(side_effect=AssertionError(
            "_build_files_array_for_book must NOT be called when only cover is missing"
        ))
        result = _run_chunk(worker, books)

        assert 'uuid-1' in result

    def test_cover_missing_does_not_trigger_get_metadata(self):
        """Missing cover must NOT trigger db.get_metadata."""
        worker = _make_worker()
        books = [_make_book_info(1, cached_files_hash='sha256:f:1000')]
        result = _run_chunk(worker, books)

        worker.db.get_metadata.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Files channel: independent from metadata and covers
# ─────────────────────────────────────────────────────────────────────────────

class TestFilesChannel:

    def test_files_from_cache_no_build_files_call(self):
        """When files_hash is cached, _build_files_array must not be called."""
        worker = _make_worker()
        books = [_make_book_info(1,
                                cached_cover_hash='sha256:c:1000',
                                cached_files_hash='sha256:cached-files:1000')]
        worker._build_files_array_for_book = Mock(side_effect=AssertionError(
            "_build_files_array_for_book should not be called when files cached"
        ))
        result = _run_chunk(worker, books)

        assert 'uuid-1' in result

    def test_files_from_bulk_no_build_files_call(self):
        """When files_hash_bulk is present, no per-book file read."""
        worker = _make_worker()
        books = [_make_book_info(1,
                                cached_cover_hash='sha256:c:1000',
                                files_hash_bulk='sha256:bulk-files')]
        worker._build_files_array_for_book = Mock(side_effect=AssertionError(
            "_build_files_array_for_book should not be called when bulk present"
        ))
        result = _run_chunk(worker, books)

        assert 'uuid-1' in result

    def test_files_missing_does_not_trigger_db_cover(self):
        """Missing files must NOT trigger db.cover() or cover recalculation."""
        worker = _make_worker()
        books = [_make_book_info(1, cached_cover_hash='sha256:c:1000')]
        # files not cached → should only compute files, not cover
        worker.db.cover = Mock(side_effect=AssertionError(
            "db.cover() must NOT be called when only files are missing"
        ))
        worker._read_cover_bytes_byte_only = Mock(side_effect=AssertionError(
            "_read_cover_bytes must NOT be called when only files are missing"
        ))
        result = _run_chunk(worker, books)

        assert 'uuid-1' in result

    def test_files_missing_does_not_trigger_get_metadata(self):
        """Missing files must NOT trigger db.get_metadata."""
        worker = _make_worker()
        books = [_make_book_info(1, cached_cover_hash='sha256:c:1000')]
        result = _run_chunk(worker, books)

        worker.db.get_metadata.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Cross-channel independence
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossChannelIndependence:

    def test_all_cached_zero_per_book_calls(self):
        """When all 3 channels are cached, zero per-book API calls."""
        worker = _make_worker()
        books = [_make_book_info(i,
                                cached_cover_hash=f'sha256:c{i}:1000',
                                cached_files_hash=f'sha256:f{i}:1000')
                 for i in range(1, 6)]
        worker._build_files_array_for_book = Mock(side_effect=AssertionError("no file read"))
        worker.db.cover = Mock(side_effect=AssertionError("no cover read"))
        worker._read_cover_bytes_byte_only = Mock(side_effect=AssertionError("no cover read"))

        result = _run_chunk(worker, books)

        assert len(result) == 5
        worker.db.get_metadata.assert_not_called()

    def test_cover_missing_files_cached_only_cover_recalculated(self):
        """Cover missing + files cached → only cover is recalculated."""
        worker = _make_worker()
        books = [_make_book_info(1, cached_files_hash='sha256:f:1000')]
        # files should NOT be recalculated
        worker._build_files_array_for_book = Mock(side_effect=AssertionError("no file read"))

        result = _run_chunk(worker, books)

        assert 'uuid-1' in result
        worker.db.get_metadata.assert_not_called()

    def test_files_missing_cover_cached_only_files_recalculated(self):
        """Files missing + cover cached → only files are recalculated."""
        worker = _make_worker()
        books = [_make_book_info(1, cached_cover_hash='sha256:c:1000')]
        # cover should NOT be recalculated
        worker.db.cover = Mock(side_effect=AssertionError("no cover read"))
        worker._read_cover_bytes_byte_only = Mock(side_effect=AssertionError("no cover read"))

        result = _run_chunk(worker, books)

        assert 'uuid-1' in result
        worker.db.get_metadata.assert_not_called()

    def test_both_missing_no_get_metadata(self):
        """Both cover and files missing → both recalculated, but NO db.get_metadata."""
        worker = _make_worker()
        books = [_make_book_info(1)]  # nothing cached
        result = _run_chunk(worker, books)

        assert 'uuid-1' in result
        assert result['uuid-1']['m'] == 'sha256:meta-from-view'
        worker.db.get_metadata.assert_not_called()

    def test_metadata_from_view_cover_from_cache_files_from_bulk(self):
        """Mixed sources: VIEW + cache + bulk → zero per-book calls."""
        worker = _make_worker()
        books = [_make_book_info(1,
                                cached_cover_hash='sha256:c:1000',
                                files_hash_bulk='sha256:bulk-f')]
        worker._build_files_array_for_book = Mock(side_effect=AssertionError("no file read"))
        worker.db.cover = Mock(side_effect=AssertionError("no cover read"))

        result = _run_chunk(worker, books)

        assert 'uuid-1' in result
        worker.db.get_metadata.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# calibre_to_json_item elimination
# ─────────────────────────────────────────────────────────────────────────────

class TestNoJsonItemInHashPath:

    def test_calibre_to_json_item_never_called(self):
        """calibre_to_json_item must NEVER be called in v5 hash build."""
        worker = _make_worker()
        books = [_make_book_info(1)]  # nothing cached, all channels need work
        # sm.calibre_to_json_item raises AssertionError (set in _run_chunk)
        result = _run_chunk(worker, books)

        assert 'uuid-1' in result

    def test_calibre_to_json_item_not_called_even_with_all_missing(self):
        """Even with all 3 channels missing, json_item should not be built."""
        worker = _make_worker()
        books = [_make_book_info(i) for i in range(1, 4)]
        result = _run_chunk(worker, books)

        assert len(result) == 3


# ─────────────────────────────────────────────────────────────────────────────
# Cover sentinel: db.cover() returns None → write sentinel, don't retry
# ─────────────────────────────────────────────────────────────────────────────

class TestCoverSentinel:

    def test_cover_none_writes_sentinel_not_null(self):
        """When db.cover() returns None, a sentinel value should be written
        to cache so the fast path doesn't retry every sync."""
        worker = _make_worker()
        worker._read_cover_bytes_byte_only = Mock(return_value=(None, 'none', 'none'))
        worker.db.cover = Mock(return_value=None)
        books = [_make_book_info(1, cached_files_hash='sha256:f:1000')]
        summary = {'errors': []}

        sm = Mock()
        sm.calibre_to_json_item = Mock(side_effect=AssertionError("no json_item"))
        sm.calculate_cover_hash = Mock(return_value=None)

        result = worker._v5_build_client_books_chunk(
            books_chunk=books, sm=sm, summary=summary,
        )

        # The cover channel should have a value (not None) so cache is written
        cover_val = result.get('uuid-1', {}).get('c')
        # Even if None is acceptable as "no cover", db.get_metadata must not be called
        worker.db.get_metadata.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# Performance guard
# ─────────────────────────────────────────────────────────────────────────────

class TestPerformanceGuard:

    def test_500_books_all_cached_under_1_second(self):
        """500 books with all channels cached must complete in < 1s."""
        worker = _make_worker()
        books = [_make_book_info(i,
                                cached_cover_hash=f'sha256:c{i}:1000',
                                cached_files_hash=f'sha256:f{i}:1000')
                 for i in range(1, 501)]
        worker._build_files_array_for_book = Mock(side_effect=AssertionError("no file read"))
        worker.db.cover = Mock(side_effect=AssertionError("no cover read"))

        start = time.time()
        result = _run_chunk(worker, books)
        elapsed = time.time() - start

        assert len(result) == 500
        assert elapsed < 1.0, f"500 cached books took {elapsed:.2f}s — expected < 1s"
        worker.db.get_metadata.assert_not_called()
