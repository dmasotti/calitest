"""
Edge-case test matrix for sync_worker decomposition guardrails.

Tests added BEFORE extraction (test-first) to verify:
1. E2E sync_v5 flow call-site integrity
2. No duplicate _upload_file call sites outside _upload_files_for_batch
3. _v5_push_missing_items with file upload targets (deferred path)
4. Cover hash sentinel: db.cover() returns None → next sync fast path skips
5. Cross-channel graceful degradation (metadata VIEW absent + cover cached + files bulk)
6. Dropbox library: file temporarily unavailable → doesn't block other channels
7. Performance guard: 12000 books with full cache → completes in < 2s
"""
from __future__ import annotations

import ast
import inspect
import os
import sys
import time
import threading
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch, call

import pytest

from calibre_plugins.sync_calimob import sync_worker
from calibre_plugins.sync_calimob import sync_mapper


# ─────────────────────────────────────────────────────────────────────────────
# Shared helpers (reuse conventions from test_hash_channel_independence)
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
    worker.db.format = Mock(return_value=b'fake-epub-bytes')
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
    worker.client = Mock()
    worker.client.verify_upload_sessions_batch = Mock(return_value={})
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
        'books_synced': 0,
        'books_from_server': 0,
        'books_missing_from_server': 0,
        'books_updated': 0,
        'books_created': 0,
        'books_skipped': 0,
        'deleted_books_sent': 0,
        'books_skipped_hash': 0,
        'books_skipped_hash_items': [],
        'books_skipped_unavailable_files': [],
        'files_deleted_local': 0,
        'covers_missing_real': 0,
        'covers_unavailable_runtime': 0,
        'covers_read_errors': 0,
        'files_missing_real': 0,
        'files_unavailable_runtime': 0,
        'files_read_errors': 0,
        'files_uploaded': 0,
        'files_failed': 0,
        'file_results': [],
        'errors': [],
        'sync_version': 'v5',
        'no_cache': False,
        'fast_path_used': False,
    }


def _wait_for_uploads(summary, expected_total, timeout=5):
    deadline = time.time() + timeout
    while time.time() < deadline:
        done = len(summary.get('file_results', []))
        if done >= expected_total:
            return
        time.sleep(0.05)


# ─────────────────────────────────────────────────────────────────────────────
# 1. E2E: sync_v5 flow (preflight → hash build → POST → upload)
#    Verify the actual call sites in the production code path.
# ─────────────────────────────────────────────────────────────────────────────

class TestSyncV5FlowE2E:
    """Verify the sync_v5 orchestration calls the correct methods in order."""

    def test_sync_v5_calls_hash_build_then_post_then_upload(self):
        """sync_v5 must follow: preflight → hash build → POST → push missing → upload."""
        worker = _make_worker()
        call_order = []

        # Stub bootstrap
        worker._v5_bootstrap_sync_state = Mock(return_value={
            'sm': Mock(),
            'sync_library_path': '/tmp/test-lib',
            'conn': Mock(),
        })

        # Stub preflight: not done, no merkle
        worker._v5_fast_path_preflight = Mock(return_value={'done': False, 'merkle_candidates': None})

        # Stub cursor
        worker._v5_get_initial_cursor_state = Mock(return_value={
            'cursor': None, 'cursor_timestamp': None,
        })

        # Stub candidates: 2 books
        worker._v5_collect_and_filter_candidates = Mock(return_value={
            'deleted_books_from_sql': [],
            'uuid_to_id': {'uuid-1': 1, 'uuid-2': 2},
            'books_to_sync': [
                (1, _make_book_info(1, cached_cover_hash='sha256:c1:1000', cached_files_hash='sha256:f1:1000')),
                (2, _make_book_info(2, cached_cover_hash='sha256:c2:1000', cached_files_hash='sha256:f2:1000')),
            ],
            'merkle_candidate_uuids': None,
        })

        worker._v5_prepare_client_inventory_state = Mock(return_value={
            'client_cursor': 0,
            'client_done': False,
            'client_entries': [
                (1, _make_book_info(1, cached_cover_hash='sha256:c1:1000', cached_files_hash='sha256:f1:1000')),
                (2, _make_book_info(2, cached_cover_hash='sha256:c2:1000', cached_files_hash='sha256:f2:1000')),
            ],
            'client_total': 2,
            'resume_sig': None,
            'cursor': None,
        })

        # Track call order via _v5_build_client_books_chunk
        original_build = worker._v5_build_client_books_chunk

        def _track_build(*args, **kwargs):
            call_order.append('hash_build')
            return {'uuid-1': {'m': 'h1', 'c': 'c1', 'f': 'f1', 'lm': 1000},
                    'uuid-2': {'m': 'h2', 'c': 'c2', 'f': 'f2', 'lm': 1000}}

        worker._v5_build_client_books_chunk = Mock(side_effect=_track_build)

        # Track POST
        def _track_post(**kwargs):
            call_order.append('sync_v5_post')
            return {
                'updates_for_client': [],
                'missing_from_server': [
                    {'uuid': 'uuid-1', 'needs_metadata': True, 'needs_cover': False,
                     'needs_files': [{'format': 'EPUB'}]},
                ],
                'deleted_on_server': [],
                'cursor': 'cursor-1',
                'has_more': False,
            }

        worker.client.sync_v5 = Mock(side_effect=_track_post)

        # Track push_missing
        def _track_push(*args, **kwargs):
            call_order.append('push_missing')
            return False

        worker._v5_push_missing_items = Mock(side_effect=_track_push)

        # Stub remaining
        worker._v5_resolve_missing_id_map = Mock(return_value=({'uuid-1': 1}, False))
        worker._v5_apply_updates_batch = Mock(return_value=([], False))
        worker._v5_checkpoint_batch_state = Mock(return_value={
            'has_more': False, 'client_done': True, 'client_cursor': 2,
            'cursor': 'cursor-1', 'logged_server_commit': False, 'fatal_stop': False,
        })
        worker._v5_finalize_sync_cursor_state = Mock()
        worker._debug_sync_toggle_snapshot = Mock()
        worker._is_sqlite_malformed_error = Mock(return_value=False)

        summary = worker.sync_v5()

        assert call_order == ['hash_build', 'sync_v5_post', 'push_missing'], \
            f"Expected [hash_build, sync_v5_post, push_missing], got {call_order}"

    def test_sync_v5_fast_path_skips_hash_build_and_post(self):
        """When preflight says done=True, no hash build or POST should happen."""
        worker = _make_worker()
        worker._v5_bootstrap_sync_state = Mock(return_value={
            'sm': Mock(), 'sync_library_path': '/tmp/test-lib', 'conn': Mock(),
        })

        # The real _v5_fast_path_preflight sets summary['fast_path_used'] = True
        # before returning done=True.  Our mock must do the same.
        def _fake_preflight(**kwargs):
            kwargs.get('summary', {})['fast_path_used'] = True
            return {'done': True}

        worker._v5_fast_path_preflight = Mock(side_effect=_fake_preflight)
        worker._v5_build_client_books_chunk = Mock(side_effect=AssertionError("should not build hashes"))
        worker.client.sync_v5 = Mock(side_effect=AssertionError("should not POST"))
        worker._debug_sync_toggle_snapshot = Mock()
        worker._is_sqlite_malformed_error = Mock(return_value=False)

        summary = worker.sync_v5()

        assert summary['fast_path_used'] is True
        worker._v5_build_client_books_chunk.assert_not_called()
        worker.client.sync_v5.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 2. No duplicate _upload_file call sites outside _upload_files_for_batch
# ─────────────────────────────────────────────────────────────────────────────

class TestNoDuplicateUploadCallSites:
    """Static analysis: _upload_file must only be called from _upload_files_for_batch."""

    def test_upload_file_only_called_from_upload_files_for_batch(self):
        """Parse sync_worker.py AST and verify _upload_file is only called
        inside _upload_files_for_batch (or its nested functions)."""
        src_path = os.path.join(os.path.dirname(sync_worker.__file__), 'sync_worker.py')
        with open(src_path, 'r') as f:
            source = f.read()
        tree = ast.parse(source)

        call_sites = []  # (method_name, lineno)

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                method_name = node.name
                for child in ast.walk(node):
                    if isinstance(child, ast.Call):
                        func = child.func
                        # Match self._upload_file(...)
                        if (isinstance(func, ast.Attribute)
                                and func.attr == '_upload_file'
                                and isinstance(func.value, ast.Name)
                                and func.value.id == 'self'):
                            call_sites.append((method_name, child.lineno))

        # Filter: only the definition itself is excluded
        external_calls = [
            (m, ln) for m, ln in call_sites
            if m != '_upload_file'  # exclude def itself
        ]

        # All external calls must be within _upload_files_for_batch or its nested functions
        allowed_parents = {'_upload_files_for_batch', '_safe_upload', '_background_upload'}
        violations = [(m, ln) for m, ln in external_calls if m not in allowed_parents]

        assert not violations, (
            f"_upload_file called from unexpected locations: {violations}. "
            f"It should only be called from _upload_files_for_batch."
        )
        # Must have at least 1 legitimate call site
        assert len(external_calls) >= 1, "No call sites found for _upload_file — test is broken"


# ─────────────────────────────────────────────────────────────────────────────
# 3. _v5_push_missing_items with file upload targets (deferred path)
# ─────────────────────────────────────────────────────────────────────────────

class TestPushMissingItemsFileUpload:
    """Verify _v5_push_missing_items correctly defers file uploads."""

    def test_push_missing_defers_file_uploads_to_batch(self):
        """When server requests files, _v5_push_missing_items must collect them
        and fire _upload_files_for_batch at flush time."""
        worker = _make_worker()
        summary = _make_summary()
        sm = Mock()
        sm.calibre_to_json_item = Mock(return_value={
            'uuid': 'uuid-1', 'title': 'Test Book', 'authors': ['Author'],
        })
        sm.calculate_cover_hash = Mock(return_value=None)

        # Server says: uuid-1 needs metadata + files
        to_upload = [{
            'uuid': 'uuid-1',
            'needs_metadata': True,
            'needs_cover': False,
            'needs_files': [{'format': 'EPUB', 'file_hash': 'sha256:abc'}],
        }]
        missing_id_map = {'uuid-1': 1}

        # SQL payload — no bulk cover/files so it falls through to per-book path
        worker._v5_get_missing_sql_payload_map = Mock(return_value={})

        # db.get_metadata for the push path (different from hash build path)
        mi = Mock()
        mi.title = 'Test Book'
        mi.has_cover = False
        mi.last_modified = None
        worker.db.get_metadata = Mock(return_value=mi)

        # _build_files_array_for_book returns files (so local_files_payload_available=True)
        worker._build_files_array_for_book = Mock(return_value=(
            [{'format': 'EPUB', 'file_hash': 'abc123'}],
            {'status': 'ok', 'declared_formats': ['EPUB'], 'files_payload_count': 1,
             'missing_formats': [], 'error_formats': [], 'unavailable_formats': []},
        ))
        worker._compute_metadata_signature = Mock(return_value='sha256:meta-sig')
        worker._record_unavailable_missing_formats = Mock()

        # POST sync response: server returns file_uploads with upload URLs
        worker.client.post_sync = Mock(return_value={
            'results': [{
                'client_change_id': None,
                'status': 'created',
                'server_item': {
                    'uuid': 'uuid-1',
                    'files': [{
                        'format': 'EPUB',
                        'upload_url': 'https://server/upload/1/epub',
                        'file_hash': 'sha256:abc123',
                    }],
                },
            }],
        })

        upload_batch_calls = []

        def _track_upload_batch(files, summary_arg, cache):
            upload_batch_calls.append(list(files))

        worker._upload_files_for_batch = Mock(side_effect=_track_upload_batch)
        worker._pending_verify_policy = Mock(return_value='batch')
        worker._is_fatal_server_error_message = Mock(return_value=False)
        worker._v5_add_error = Mock()

        worker._v5_push_missing_items(
            to_upload=to_upload,
            missing_id_map=missing_id_map,
            uuids_deleted_locally=set(),
            sync_library_path='/tmp/test-lib',
            sm=sm,
            summary=summary,
        )

        # _upload_files_for_batch should have been called with the deferred files
        assert len(upload_batch_calls) >= 1, \
            f"Expected _upload_files_for_batch to be called, got {len(upload_batch_calls)} calls"
        # Verify the deferred file has the right upload URL
        deferred = upload_batch_calls[0]
        assert len(deferred) >= 1
        assert deferred[0]['upload_url'] == 'https://server/upload/1/epub'

    def test_push_missing_no_files_no_upload_batch(self):
        """When server doesn't request files, _upload_files_for_batch should NOT be called."""
        worker = _make_worker()
        summary = _make_summary()
        sm = Mock()

        to_upload = [{
            'uuid': 'uuid-1',
            'needs_metadata': True,
            'needs_cover': False,
            'needs_files': [],  # no files needed
        }]
        missing_id_map = {'uuid-1': 1}

        worker._v5_get_missing_sql_payload_map = Mock(return_value={
            1: {'id': 1, 'uuid': 'uuid-1', 'title': 'Test', 'authors': 'Auth'},
        })
        worker.client.post_sync = Mock(return_value={
            'results': [{'uuid': 'uuid-1', 'server_item_id': 100, 'status': 'created'}],
        })
        worker._upload_files_for_batch = Mock()
        worker._pending_verify_policy = Mock(return_value='batch')

        worker._v5_push_missing_items(
            to_upload=to_upload,
            missing_id_map=missing_id_map,
            uuids_deleted_locally=set(),
            sync_library_path='/tmp/test-lib',
            sm=sm,
            summary=summary,
        )

        worker._upload_files_for_batch.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 4. Cover hash sentinel: db.cover() returns None → sentinel → fast path skip
# ─────────────────────────────────────────────────────────────────────────────

class TestCoverHashSentinel:
    """When a book has no cover, the hash path should produce a deterministic
    value (or None) and NOT retry on every sync."""

    def test_cover_none_produces_deterministic_result(self):
        """db.cover() returns None → cover hash resolved to None/sentinel,
        and the result is deterministic across calls."""
        worker = _make_worker()
        worker._read_cover_bytes_byte_only = Mock(return_value=(None, 'none', 'none'))

        sm = Mock()
        sm.calibre_to_json_item = Mock(side_effect=AssertionError("no json_item"))
        sm.calculate_cover_hash = Mock(return_value=None)

        books = [_make_book_info(1, cached_files_hash='sha256:f:1000')]
        summary = {'errors': []}

        result1 = worker._v5_build_client_books_chunk(books_chunk=books, sm=sm, summary=summary)
        result2 = worker._v5_build_client_books_chunk(books_chunk=books, sm=sm, summary=summary)

        # Both calls must produce same cover hash
        assert result1['uuid-1']['c'] == result2['uuid-1']['c'], \
            "Cover hash for None cover is not deterministic"

    def test_cover_cached_none_uses_cache_not_retry(self):
        """If cover hash was already cached (from previous sync where cover was None),
        the system should use the cached value, not re-read cover bytes."""
        worker = _make_worker()
        # Cover hash is cached (could be sentinel or empty)
        books = [_make_book_info(1,
                                cached_cover_hash='__no_cover__:1000',
                                cached_files_hash='sha256:f:1000')]

        # _read_cover_bytes should NOT be called — cache hit
        worker._read_cover_bytes_byte_only = Mock(side_effect=AssertionError(
            "Should not re-read cover bytes when cached"
        ))

        result = _run_chunk(worker, books)

        assert 'uuid-1' in result
        worker.db.get_metadata.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Cross-channel graceful degradation
# ─────────────────────────────────────────────────────────────────────────────

class TestCrossChannelGracefulDegradation:
    """Verify that partial channel failures degrade gracefully."""

    def test_metadata_view_absent_cover_cached_files_bulk(self):
        """metadata_hash_view is None → metadata='None', but cover and files
        should still resolve normally from their sources."""
        worker = _make_worker()
        books = [_make_book_info(1,
                                metadata_hash_view=None,  # VIEW absent
                                cached_cover_hash='sha256:cover-cached:1000',
                                files_hash_bulk='sha256:files-bulk')]

        # Cover should NOT be recalculated (cached)
        worker._read_cover_bytes_byte_only = Mock(side_effect=AssertionError(
            "Cover should come from cache, not per-book read"
        ))
        # Files should NOT be recalculated (bulk)
        worker._build_files_array_for_book = Mock(side_effect=AssertionError(
            "Files should come from bulk, not per-book read"
        ))

        result = _run_chunk(worker, books)

        assert 'uuid-1' in result
        # Metadata is None (VIEW absent)
        assert result['uuid-1']['m'] is None
        # Cover from cache (extracted hash without timestamp)
        assert result['uuid-1']['c'] is not None
        # Files from bulk
        assert result['uuid-1']['f'] == 'sha256:files-bulk'
        worker.db.get_metadata.assert_not_called()

    def test_all_three_degrade_independently(self):
        """Each channel failing independently should not affect the others."""
        worker = _make_worker()
        # Metadata: None from VIEW
        # Cover: fallback will fail
        # Files: bulk present
        worker._read_cover_bytes_byte_only = Mock(side_effect=Exception("Dropbox offline"))

        sm = Mock()
        sm.calibre_to_json_item = Mock(side_effect=AssertionError("no json_item"))
        sm.calculate_cover_hash = Mock(return_value=None)

        books = [_make_book_info(1,
                                metadata_hash_view=None,
                                files_hash_bulk='sha256:files-ok')]
        summary = {'errors': []}

        result = worker._v5_build_client_books_chunk(
            books_chunk=books, sm=sm, summary=summary,
        )

        assert 'uuid-1' in result
        # Metadata: None (VIEW absent)
        assert result['uuid-1']['m'] is None
        # Cover: None (read failed, but gracefully)
        assert result['uuid-1']['c'] is None
        # Files: from bulk (unaffected by cover failure)
        assert result['uuid-1']['f'] == 'sha256:files-ok'


# ─────────────────────────────────────────────────────────────────────────────
# 6. Dropbox library: file temporarily unavailable → other channels unaffected
# ─────────────────────────────────────────────────────────────────────────────

class TestDropboxUnavailableFiles:
    """Simulate Dropbox smart-sync: file exists in DB but bytes temporarily
    unavailable. Must NOT block cover/metadata channels."""

    def test_files_unavailable_skips_book_but_cover_metadata_unaffected(self):
        """When _build_files_array_for_book returns unavailable status,
        the book is skipped but previous books' cover/metadata are fine."""
        worker = _make_worker()

        # Book 1: all good (cached)
        # Book 2: files unavailable (Dropbox smart-sync)
        # Book 3: all good (cached)
        books = [
            _make_book_info(1, cached_cover_hash='sha256:c1:1000', cached_files_hash='sha256:f1:1000'),
            _make_book_info(2, cached_cover_hash='sha256:c2:1000'),  # files not cached
            _make_book_info(3, cached_cover_hash='sha256:c3:1000', cached_files_hash='sha256:f3:1000'),
        ]

        # Book 2's files are unavailable
        def _build_files_for_book(book_id, include_diag=False):
            if book_id == 2:
                return (
                    [],  # no files array
                    {'status': 'unavailable', 'declared_formats': ['EPUB'],
                     'missing_formats': [], 'error_formats': [],
                     'unavailable_formats': ['EPUB']},
                )
            return (
                [{'format': 'EPUB', 'file_hash': 'abc'}],
                {'status': 'ok', 'declared_formats': ['EPUB']},
            )

        worker._build_files_array_for_book = Mock(side_effect=_build_files_for_book)

        summary = {'errors': [], 'files_unavailable_runtime': 0,
                   'books_skipped_unavailable_files': []}
        sm = Mock()
        sm.calibre_to_json_item = Mock(side_effect=AssertionError("no json_item"))

        result = worker._v5_build_client_books_chunk(
            books_chunk=books, sm=sm, summary=summary,
        )

        # Book 1 and 3 should be in result
        assert 'uuid-1' in result
        assert 'uuid-3' in result
        # Book 2 skipped due to unavailable files
        assert 'uuid-2' not in result
        # Summary tracks the skip
        assert summary['files_unavailable_runtime'] == 1
        assert len(summary['books_skipped_unavailable_files']) == 1
        assert summary['books_skipped_unavailable_files'][0]['book_id'] == 2

    def test_unavailable_file_does_not_trigger_cover_reread(self):
        """Even when files are unavailable for book N, cover for book N+1
        must not be re-read if cached."""
        worker = _make_worker()

        books = [
            _make_book_info(1),  # nothing cached, will hit fallbacks
            _make_book_info(2, cached_cover_hash='sha256:c2:1000', cached_files_hash='sha256:f2:1000'),
        ]

        # Book 1 files unavailable
        worker._build_files_array_for_book = Mock(return_value=(
            [],
            {'status': 'unavailable', 'declared_formats': ['EPUB'],
             'unavailable_formats': ['EPUB']},
        ))

        # Book 2 should NOT trigger any per-book reads
        read_cover_calls = []
        original_read = worker._read_cover_bytes_byte_only

        def _track_read(book_id):
            read_cover_calls.append(book_id)
            return (b'cover', 'db.cover', None)

        worker._read_cover_bytes_byte_only = Mock(side_effect=_track_read)

        summary = {'errors': [], 'files_unavailable_runtime': 0,
                   'books_skipped_unavailable_files': []}
        sm = Mock()
        sm.calibre_to_json_item = Mock(side_effect=AssertionError("no json_item"))
        sm.calculate_cover_hash = Mock(return_value='sha256:cover-1')

        result = worker._v5_build_client_books_chunk(
            books_chunk=books, sm=sm, summary=summary,
        )

        # Book 2 must be in result
        assert 'uuid-2' in result
        # Cover read should NOT have been called for book 2
        assert 2 not in read_cover_calls, \
            f"Cover re-read triggered for book 2 despite cache hit: {read_cover_calls}"


# ─────────────────────────────────────────────────────────────────────────────
# 7. Performance guard: 12000 books with full cache → < 2s
# ─────────────────────────────────────────────────────────────────────────────

class TestPerformanceGuard12k:
    """Realistic performance guard: 12000 books with all channels cached."""

    def test_12000_books_all_cached_under_2_seconds(self):
        """12000 books with all 3 channels cached must complete in < 2s."""
        worker = _make_worker()
        books = [_make_book_info(i,
                                cached_cover_hash=f'sha256:c{i}:1000',
                                cached_files_hash=f'sha256:f{i}:1000')
                 for i in range(1, 12001)]

        # With all cached, these should NEVER be called
        worker._build_files_array_for_book = Mock(side_effect=AssertionError("no file read"))
        worker.db.cover = Mock(side_effect=AssertionError("no cover read"))
        worker._read_cover_bytes_byte_only = Mock(side_effect=AssertionError("no cover read"))

        start = time.time()
        result = _run_chunk(worker, books)
        elapsed = time.time() - start

        assert len(result) == 12000
        assert elapsed < 2.0, f"12000 cached books took {elapsed:.2f}s — expected < 2s"
        worker.db.get_metadata.assert_not_called()

    def test_12000_books_mixed_cache_under_5_seconds(self):
        """12000 books: 11000 cached, 1000 need fallback → < 5s."""
        worker = _make_worker()
        books = []
        for i in range(1, 12001):
            if i <= 11000:
                books.append(_make_book_info(i,
                                            cached_cover_hash=f'sha256:c{i}:1000',
                                            cached_files_hash=f'sha256:f{i}:1000'))
            else:
                books.append(_make_book_info(i))  # no cache, needs fallback

        start = time.time()
        result = _run_chunk(worker, books)
        elapsed = time.time() - start

        assert len(result) == 12000
        assert elapsed < 5.0, f"12000 mixed books took {elapsed:.2f}s — expected < 5s"
        worker.db.get_metadata.assert_not_called()
