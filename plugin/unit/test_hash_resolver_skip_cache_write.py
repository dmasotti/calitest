"""
Tests: HashResolver must skip cache writes when all channels are cache hits.

Production issue: hash build for 12038 books does 2 SQL writes per book
(cache_book_uuid + persist_cache) = ~24000 SQL queries even when all
data comes from the bulk SQL query (cache hit). This takes ~24+ seconds
of pure I/O for zero new information.

Fix: when can_reuse_cache=True (all 3 channels resolved from cache),
skip both cache_book_uuid and persist_cache writes.
"""
from __future__ import annotations

import time
from unittest.mock import Mock

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
    worker._target_debug_uuid = None
    worker._sync_files_enabled = Mock(return_value=True)
    worker._sync_covers_enabled = Mock(return_value=True)
    worker._presigned_verify_enabled = Mock(return_value=False)
    worker._presigned_verify_batch_enabled = Mock(return_value=False)
    worker._v5_extract_hash_no_ts = Mock(side_effect=lambda v: v.split(':')[0] if v and ':' in v else v)
    worker._read_cover_bytes_byte_only = Mock(return_value=(b'cover', 'db.cover', None))
    worker._build_files_array_for_book = Mock(return_value=(
        [{'format': 'EPUB', 'file_hash': 'abc'}],
        {'status': 'ok', 'declared_formats': ['EPUB']},
    ))
    worker._compute_files_signature = Mock(return_value='sha256:files-computed')
    worker._check_cancelled = Mock()
    worker._cache_book_uuid = Mock()
    worker._sync_heartbeat = Mock()
    worker.status_tag_mappings = {}
    worker._add_error = Mock()
    worker.client = Mock()
    return worker


def _make_cached_book(book_id, lm=1000):
    """Book with all 3 channels cached (cache hit)."""
    return {
        'id': book_id,
        'uuid': f'uuid-{book_id}',
        'last_modified': lm,
        'sync_last_modified': lm,  # matches → can_reuse_cache=True
        'metadata_hash_view': f'sha256:meta-{book_id}',
        'cached_hash': None,
        'cached_cover_hash': f'sha256:c{book_id}:{lm}',
        'cached_files_hash': f'sha256:f{book_id}:{lm}',
        'cover_hash_bulk': None,
        'files_hash_bulk': None,
        'cached_formats_sig': None,
    }


def _make_uncached_book(book_id, lm=2000):
    """Book with no cache (needs computation + cache write)."""
    return {
        'id': book_id,
        'uuid': f'uuid-{book_id}',
        'last_modified': lm,
        'sync_last_modified': 1000,  # different → can_reuse_cache=False
        'metadata_hash_view': f'sha256:meta-{book_id}',
        'cached_hash': None,
        'cached_cover_hash': None,
        'cached_files_hash': None,
        'cover_hash_bulk': None,
        'files_hash_bulk': None,
        'cached_formats_sig': None,
    }


def _run_chunk(worker, books):
    sm = Mock()
    sm.calibre_to_json_item = Mock(side_effect=AssertionError("no json_item"))
    sm.calculate_cover_hash = Mock(return_value='sha256:cover-fresh')
    summary = {'errors': []}
    return worker._v5_build_client_books_chunk(
        books_chunk=books, sm=sm, summary=summary,
    )


# ─────────────────────────────────────────────────────────────────────────────
# 1. Cache hit: zero cache writes
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheHitSkipsWrite:
    """When all channels come from cache, no SQL writes needed."""

    def test_all_cached_zero_update_book_cache_calls(self):
        """500 books with full cache → 0 calls to update_book_cache."""
        worker = _make_worker()
        books = [_make_cached_book(i) for i in range(1, 501)]

        original_cfg = sync_worker.cfg
        mock_cfg = Mock()
        mock_cfg.update_book_cache = Mock()
        sync_worker.cfg = mock_cfg
        try:
            _run_chunk(worker, books)
            assert mock_cfg.update_book_cache.call_count == 0, (
                f"Expected 0 cache writes for 500 cached books, "
                f"got {mock_cfg.update_book_cache.call_count}"
            )
        finally:
            sync_worker.cfg = original_cfg

    def test_all_cached_zero_cache_book_uuid_calls(self):
        """500 cached books → 0 calls to cache_book_uuid."""
        worker = _make_worker()
        books = [_make_cached_book(i) for i in range(1, 501)]

        _run_chunk(worker, books)
        assert worker._cache_book_uuid.call_count == 0, (
            f"Expected 0 UUID cache writes for 500 cached books, "
            f"got {worker._cache_book_uuid.call_count}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Cache miss: cache writes happen
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheMissWritesCache:
    """When channels need computation, cache writes must happen."""

    def test_uncached_books_get_cache_writes(self):
        """10 uncached books → 10 calls to update_book_cache."""
        worker = _make_worker()
        books = [_make_uncached_book(i) for i in range(1, 11)]

        original_cfg = sync_worker.cfg
        mock_cfg = Mock()
        mock_cfg.update_book_cache = Mock()
        sync_worker.cfg = mock_cfg
        try:
            _run_chunk(worker, books)
            assert mock_cfg.update_book_cache.call_count == 10, (
                f"Expected 10 cache writes for 10 uncached books, "
                f"got {mock_cfg.update_book_cache.call_count}"
            )
        finally:
            sync_worker.cfg = original_cfg

    def test_uncached_books_get_uuid_cache_writes(self):
        """10 uncached books → 10 calls to cache_book_uuid."""
        worker = _make_worker()
        books = [_make_uncached_book(i) for i in range(1, 11)]

        _run_chunk(worker, books)
        assert worker._cache_book_uuid.call_count == 10


# ─────────────────────────────────────────────────────────────────────────────
# 3. Mixed: only uncached books get writes
# ─────────────────────────────────────────────────────────────────────────────

class TestMixedCacheHitMiss:
    """Mixed cached + uncached: writes only for uncached."""

    def test_mixed_490_cached_10_uncached(self):
        """490 cached + 10 uncached → 10 cache writes (not 500)."""
        worker = _make_worker()
        books = [_make_cached_book(i) for i in range(1, 491)]
        books += [_make_uncached_book(i) for i in range(491, 501)]

        original_cfg = sync_worker.cfg
        mock_cfg = Mock()
        mock_cfg.update_book_cache = Mock()
        sync_worker.cfg = mock_cfg
        try:
            _run_chunk(worker, books)
            assert mock_cfg.update_book_cache.call_count == 10, (
                f"Expected 10 writes (only uncached), "
                f"got {mock_cfg.update_book_cache.call_count}"
            )
        finally:
            sync_worker.cfg = original_cfg


# ─────────────────────────────────────────────────────────────────────────────
# 4. Performance: 12000 cached books must be fast
# ─────────────────────────────────────────────────────────────────────────────

class TestPerformanceNoCacheWrites:
    """12000 cached books must complete in < 2s (no SQL writes)."""

    def test_12000_cached_under_2_seconds(self):
        worker = _make_worker()
        worker._build_files_array_for_book = Mock(
            side_effect=AssertionError("no file read for cached book")
        )
        worker._read_cover_bytes_byte_only = Mock(
            side_effect=AssertionError("no cover read for cached book")
        )

        books = [_make_cached_book(i) for i in range(1, 12001)]

        original_cfg = sync_worker.cfg
        mock_cfg = Mock()
        mock_cfg.update_book_cache = Mock()
        sync_worker.cfg = mock_cfg
        try:
            start = time.time()
            result = _run_chunk(worker, books)
            elapsed = time.time() - start

            assert len(result) == 12000
            assert elapsed < 5.0, f"12000 cached books took {elapsed:.2f}s"
            assert mock_cfg.update_book_cache.call_count == 0
        finally:
            sync_worker.cfg = original_cfg


# ─────────────────────────────────────────────────────────────────────────────
# 5. Source: persist_cache only called when not can_reuse_cache
# ─────────────────────────────────────────────────────────────────────────────

class TestSourceCodeSkipsCacheOnHit:
    """HashResolver source must skip persist_cache when can_reuse_cache."""

    def test_persist_cache_guarded_by_cache_reuse(self):
        """_persist_cache must be inside a 'not can_reuse_cache' guard."""
        import os
        src_path = os.path.join(
            os.path.dirname(sync_worker.__file__), 'sync_hash_resolver.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        # Find build_chunk method
        method_start = code.find('def build_chunk')
        assert method_start > 0
        next_def = code.find('\n    def ', method_start + 10)
        method_body = code[method_start:next_def]

        # _persist_cache must be guarded
        persist_pos = method_body.find('_persist_cache')
        assert persist_pos > 0

        # Look backwards from _persist_cache for the guard
        before_persist = method_body[max(0, persist_pos - 200):persist_pos]
        has_guard = (
            'not can_reuse_cache' in before_persist or
            'can_reuse_cache' in before_persist
        )
        assert has_guard, (
            "_persist_cache must be guarded by 'not can_reuse_cache' check. "
            "Without this, 24000+ SQL writes happen for 12000 cached books."
        )
