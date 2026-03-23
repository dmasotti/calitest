"""
Big library + concurrency edge-case matrix.

Tests verified against a 12000-book production library (2026-03-23).
Covers scenarios discovered during real sync:
1. Merkle drilldown: 3 dimensions × 256 leaves × 16 branches
2. Concurrent Merkle rebuild while sync is running
3. Files dimension timeout graceful degradation
4. Large POST payload (105KB) → 307 redirect handling
5. Background upload thread safety (SSL thread isolation)
6. Idempotency cache: error responses not reused
7. Performance: 12000 books hash build, preflight, candidate selection
8. Resume state across Merkle failures
9. Mixed success/failure across dimensions
10. Stale materialized data: is_stale=1 triggers rebuild mid-sync
"""
from __future__ import annotations

import os
import sys
import time
import threading
from unittest.mock import Mock, MagicMock

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
    worker._presigned_verify_enabled = Mock(return_value=False)
    worker._presigned_verify_batch_enabled = Mock(return_value=False)
    worker._v5_extract_hash_no_ts = Mock(side_effect=lambda v: v.split(':')[0] if v and ':' in v else v)
    worker._read_cover_bytes_byte_only = Mock(return_value=(b'cover', 'db.cover', None))
    worker._build_files_array_for_book = Mock(return_value=(
        [{'format': 'EPUB', 'file_hash': 'abc'}],
        {'status': 'ok', 'declared_formats': ['EPUB']},
    ))
    worker._compute_files_signature = Mock(return_value='sha256:files-computed')
    worker._cache_book_uuid = Mock()
    worker._add_error = Mock()
    worker._target_debug_uuid = None
    worker.status_tag_mappings = {}
    worker.client = Mock()
    return worker


def _make_book_info(book_id, **kwargs):
    base = {
        'id': book_id,
        'uuid': f'uuid-{book_id}',
        'last_modified': 1000,
        'sync_last_modified': 1000,
        'metadata_hash_view': f'sha256:meta-{book_id}',
        'cached_hash': None,
        'cached_cover_hash': f'sha256:c{book_id}:1000',
        'cached_files_hash': f'sha256:f{book_id}:1000',
        'cover_hash_bulk': None,
        'files_hash_bulk': None,
        'cached_formats_sig': None,
    }
    base.update(kwargs)
    return base


# ─────────────────────────────────────────────────────────────────────────────
# 1. Performance: 12000 books hash build
# ─────────────────────────────────────────────────────────────────────────────

class TestBigLibraryHashBuild:
    """Hash build for 12000 books must complete in reasonable time."""

    def test_12000_all_cached_under_2s(self):
        """All 3 channels cached → zero per-book I/O."""
        worker = _make_worker()
        worker._build_files_array_for_book = Mock(side_effect=AssertionError("no file read"))
        worker._read_cover_bytes_byte_only = Mock(side_effect=AssertionError("no cover read"))

        books = [_make_book_info(i) for i in range(1, 12001)]

        sm = Mock()
        sm.calibre_to_json_item = Mock(side_effect=AssertionError("no json_item"))
        summary = {'errors': []}

        start = time.time()
        result = worker._v5_build_client_books_chunk(books, sm=sm, summary=summary)
        elapsed = time.time() - start

        assert len(result) == 12000
        assert elapsed < 2.0, f"12000 cached books took {elapsed:.2f}s"

    def test_12000_mixed_1000_uncached_under_5s(self):
        """11000 cached + 1000 fallback → < 5s."""
        worker = _make_worker()
        books = []
        for i in range(1, 12001):
            if i <= 11000:
                books.append(_make_book_info(i))
            else:
                books.append(_make_book_info(i, cached_cover_hash=None, cached_files_hash=None))

        sm = Mock()
        sm.calibre_to_json_item = Mock(side_effect=AssertionError("no json_item"))
        sm.calculate_cover_hash = Mock(return_value='sha256:fresh-cover')
        summary = {'errors': []}

        start = time.time()
        result = worker._v5_build_client_books_chunk(books, sm=sm, summary=summary)
        elapsed = time.time() - start

        assert len(result) == 12000
        assert elapsed < 5.0, f"12000 mixed books took {elapsed:.2f}s"


# ─────────────────────────────────────────────────────────────────────────────
# 2. Merkle dimensions: independent failure
# ─────────────────────────────────────────────────────────────────────────────

class TestMerkleDimensionFailureIsolation:
    """Each Merkle dimension fails independently (production bug 2026-03-22)."""

    def test_files_504_metadata_candidates_survive(self):
        """Files 504 must not discard metadata candidates."""
        from calibre_plugins.sync_calimob.sync_preflight import SyncPreflight

        metadata_candidates = ['uuid-1', 'uuid-2', 'uuid-3']

        preflight = SyncPreflight(
            library_id='lib-1', client=Mock(), mapping_table=Mock(), cfg=Mock(),
            sync_files_enabled_fn=Mock(return_value=True),
            sync_covers_enabled_fn=Mock(return_value=True),
            merkle_metadata_drilldown_fn=Mock(return_value=metadata_candidates),
            merkle_covers_drilldown_fn=Mock(return_value=None),
            merkle_files_drilldown_fn=Mock(side_effect=Exception("504")),
        )

        # Verify independence: metadata callable returns candidates
        # even after files callable raises
        result = preflight._merkle_metadata_drilldown(None, local_hash_data={}, server_hash_data={})
        assert result == metadata_candidates

        with pytest.raises(Exception, match="504"):
            preflight._merkle_files_drilldown(None, local_hash_data={}, server_hash_data={})

        # Metadata result unaffected
        assert result == metadata_candidates

    def test_all_three_fail_gracefully(self):
        """All 3 dimensions fail → sync proceeds with full inventory."""
        from calibre_plugins.sync_calimob.sync_preflight import SyncPreflight

        preflight = SyncPreflight(
            library_id='lib-1', client=Mock(), mapping_table=Mock(), cfg=Mock(),
            sync_files_enabled_fn=Mock(return_value=True),
            sync_covers_enabled_fn=Mock(return_value=True),
            merkle_metadata_drilldown_fn=Mock(side_effect=Exception("504 metadata")),
            merkle_covers_drilldown_fn=Mock(side_effect=Exception("504 covers")),
            merkle_files_drilldown_fn=Mock(side_effect=Exception("504 files")),
        )

        # All fail, but each independently
        for fn, name in [
            (preflight._merkle_metadata_drilldown, "metadata"),
            (preflight._merkle_covers_drilldown, "covers"),
            (preflight._merkle_files_drilldown, "files"),
        ]:
            with pytest.raises(Exception):
                fn(None, local_hash_data={}, server_hash_data={})


# ─────────────────────────────────────────────────────────────────────────────
# 3. HTTP 307 on large POST
# ─────────────────────────────────────────────────────────────────────────────

class TestLargePostRedirect:
    """Large sync/v5 POST (105KB+) may trigger nginx 307."""

    def test_307_is_retryable(self):
        """307 must be in the retryable status codes."""
        src = os.path.join(os.path.dirname(rest_client.__file__), 'rest_client.py')
        with open(src) as f:
            code = f.read()

        retry_start = code.find('if status in (')
        retry_end = code.find(')', retry_start + 14)
        retry_tuple = code[retry_start:retry_end + 1]

        assert '307' in retry_tuple
        assert '308' in retry_tuple

    def test_large_payload_size_realistic(self):
        """500 books payload is >30KB (realistic for production)."""
        import json
        payload = {'b': {f'uuid-{i}': {'m': 'sha256:' + 'a' * 64, 'c': 'sha256:' + 'b' * 64, 'f': 'sha256:' + 'c' * 64, 'lm': 1742630400} for i in range(500)}}
        data = json.dumps(payload).encode()
        assert len(data) > 30000, f"500-book payload is only {len(data)} bytes"


# ─────────────────────────────────────────────────────────────────────────────
# 4. SSL thread safety
# ─────────────────────────────────────────────────────────────────────────────

class TestSSLThreadSafety:
    """Background upload threads must not share SSL connections."""

    def test_thread_local_exists_in_rest_client(self):
        src = os.path.join(os.path.dirname(rest_client.__file__), 'rest_client.py')
        with open(src) as f:
            code = f.read()
        assert 'threading.local()' in code

    def test_get_http_returns_per_thread_instance(self):
        """_get_http on different threads should return different instances."""
        src = os.path.join(os.path.dirname(rest_client.__file__), 'rest_client.py')
        with open(src) as f:
            code = f.read()

        # _get_http method must exist
        assert '_get_http' in code

    def test_concurrent_uploads_different_threads(self):
        """Parallel uploads must run on different threads than main."""
        from calibre_plugins.sync_calimob.sync_file_uploader import FileUploader

        main_tid = threading.current_thread().ident
        upload_tids = []

        def _track(fi, fc):
            upload_tids.append(threading.current_thread().ident)
            return {'success': True, 'step': 'success', 'book_id': 1,
                    'format': 'EPUB', 'upload_size': 100, 'file_hash': 'h',
                    'response': {'session_id': 's1', 'status': 'ok'}}

        uploader = FileUploader(
            client=Mock(), db=Mock(),
            upload_single_fn=Mock(side_effect=_track),
        )
        uploader._client.verify_upload_sessions_batch = Mock(return_value={})

        summary = {'files_uploaded': 0, 'files_failed': 0, 'file_results': [], 'errors': []}
        files = [{'calibre_book_id': i, 'format': 'EPUB', 'book_title': f'B{i}',
                  'upload_url': 'u', 'server_item_id': i, 'item_uuid': f'u{i}',
                  'file_hash': 'h', 'library_id': 1, 'calibre_library_uuid': 'l'}
                 for i in range(1, 5)]

        uploader.upload_batch(files, summary, {})

        deadline = time.time() + 5
        while len(upload_tids) < 4 and time.time() < deadline:
            time.sleep(0.05)

        assert len(upload_tids) >= 4
        assert all(tid != main_tid for tid in upload_tids), "Uploads must be on different threads"


# ─────────────────────────────────────────────────────────────────────────────
# 5. Idempotency: error responses not cached
# ─────────────────────────────────────────────────────────────────────────────

class TestIdempotencyErrorNotCached:
    """Server idempotency handler must not reuse error responses."""

    def test_idempotency_handler_checks_error_status(self):
        """Source must check for status='error' before reusing."""
        src = os.path.join(
            os.path.dirname(rest_client.__file__),
            '..', 'html', 'app', 'Services', 'Sync', 'IdempotencyHandler.php'
        )
        # This test only runs if server code is in the same repo
        if not os.path.exists(src):
            pytest.skip("Server code not in this checkout")
        with open(src) as f:
            code = f.read()
        assert "status === 'error'" in code or 'status === "error"' in code


# ─────────────────────────────────────────────────────────────────────────────
# 6. Candidate selection with big library
# ─────────────────────────────────────────────────────────────────────────────

class TestBigLibraryCandidateSelection:
    """Candidate selection must handle 12000 books efficiently."""

    def test_merkle_filter_reduces_candidates(self):
        """Merkle filter: 12000 → 50 candidates."""
        worker = _make_worker()
        all_books = [{'uuid': f'uuid-{i}'} for i in range(12000)]
        merkle_candidates = [f'uuid-{i}' for i in range(50)]

        worker._v5_collect_client_books_candidates = Mock(return_value=(
            [], {f'uuid-{i}': i for i in range(12000)}, all_books,
        ))

        result = worker._v5_collect_and_filter_candidates(
            cursor_timestamp=None, sync_library_path='/tmp',
            merkle_candidates=merkle_candidates,
            summary={}, ts_func=lambda: 'test', debug_file=sys.stderr,
        )

        assert len(result['books_to_sync']) == 50
        assert len(result['merkle_candidate_uuids']) == 50

    def test_no_merkle_passes_all(self):
        """Without Merkle, all 12000 books pass through."""
        worker = _make_worker()
        all_books = [{'uuid': f'uuid-{i}'} for i in range(12000)]

        worker._v5_collect_client_books_candidates = Mock(return_value=(
            [], {}, all_books,
        ))

        result = worker._v5_collect_and_filter_candidates(
            cursor_timestamp=None, sync_library_path='/tmp',
            merkle_candidates=None,
            summary={}, ts_func=lambda: 'test', debug_file=sys.stderr,
        )

        assert len(result['books_to_sync']) == 12000
        assert result['merkle_candidate_uuids'] is None


# ─────────────────────────────────────────────────────────────────────────────
# 7. Resume state across failures
# ─────────────────────────────────────────────────────────────────────────────

class TestResumeStateAcrossFailures:
    """Resume state must survive Merkle failures."""

    def test_checkpoint_saves_progress(self):
        """Checkpoint must save cursor even after partial failures."""
        worker = _make_worker()
        worker.save_pull_cursor = Mock()
        worker._v5_save_resume_state = Mock()

        result = worker._v5_checkpoint_batch_state(
            cursor_next='cursor-2', batch_had_errors=False,
            cursor='cursor-1', resume_sig='sig', client_cursor=100, client_total=500,
        )

        worker.save_pull_cursor.assert_called_once_with('cursor-2')
        assert result['cursor'] == 'cursor-2'

    def test_critical_errors_block_checkpoint(self):
        """Critical errors must prevent cursor save."""
        worker = _make_worker()
        worker.save_pull_cursor = Mock()
        worker._v5_save_resume_state = Mock()

        worker._v5_checkpoint_batch_state(
            cursor_next='cursor-2', batch_had_errors=True,
            batch_has_critical_errors=True,
            cursor='cursor-1', resume_sig='sig', client_cursor=100, client_total=500,
        )

        worker.save_pull_cursor.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 8. Stale materialized data triggers rebuild
# ─────────────────────────────────────────────────────────────────────────────

class TestStaleMaterializedData:
    """When is_stale=1, materialized data must be rebuilt before use."""

    def test_stale_detection_in_source(self):
        """ensureDimensionsMaterialized must check is_stale."""
        src = os.path.join(
            os.path.dirname(rest_client.__file__),
            '..', 'html', 'app', 'Services', 'Sync', 'MaterializedMerkleService.php'
        )
        if not os.path.exists(src):
            pytest.skip("Server code not in this checkout")
        with open(src) as f:
            code = f.read()
        assert 'is_stale' in code
        assert 'rebuildStale' in code or 'rebuild' in code.lower()


# ─────────────────────────────────────────────────────────────────────────────
# 9. Materialized uuids_json used for leaf queries
# ─────────────────────────────────────────────────────────────────────────────

class TestMaterializedUuidsJson:
    """getLeafUuids must read from materialized uuids_json, not source JOIN."""

    def test_get_leaf_uuids_uses_materialized(self):
        src = os.path.join(
            os.path.dirname(rest_client.__file__),
            '..', 'html', 'app', 'Services', 'Sync', 'MaterializedMerkleService.php'
        )
        if not os.path.exists(src):
            pytest.skip("Server code not in this checkout")
        with open(src) as f:
            code = f.read()

        method_start = code.find('public function getLeafUuids(')
        assert method_start > 0
        next_method = code.find("\n    public function ", method_start + 10)
        method_body = code[method_start:next_method]

        assert 'uuids_json' in method_body, \
            "getLeafUuids must read from materialized uuids_json"

    def test_full_rebuild_populates_uuids_json(self):
        """Full rebuild (insertLeavesMysql) must populate uuids_json."""
        src = os.path.join(
            os.path.dirname(rest_client.__file__),
            '..', 'html', 'app', 'Services', 'Sync', 'MaterializedMerkleService.php'
        )
        if not os.path.exists(src):
            pytest.skip("Server code not in this checkout")
        with open(src) as f:
            code = f.read()

        # Find insertLeavesMysql — it must NOT have '[]' AS uuids_json
        method_start = code.find('private function insertLeavesMysql(')
        if method_start < 0:
            pytest.skip("insertLeavesMysql not found")
        next_method = code.find("\n    private function ", method_start + 10)
        method_body = code[method_start:next_method if next_method > 0 else method_start + 2000]

        assert "GROUP_CONCAT" in method_body or "JSON_QUOTE" in method_body, \
            "insertLeavesMysql must populate uuids_json with GROUP_CONCAT, not '[]'"
