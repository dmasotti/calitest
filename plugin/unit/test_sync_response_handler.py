"""
Unit tests for sync_response_handler.py — response parsing and upload queue.

Covers:
  sr01: Parse response with updates + missing + deleted → correct split
  sr02: Missing item with needs_cover=true → queued with needs_cover
  sr03: Missing item with needs_files=true + file_upload_targets → queued with targets
  sr04: Missing item with needs_metadata → added to needs_metadata_push
  sr05: Empty response → all fields zero/empty
  sr06: skipped_hash count forwarded from response
  sr07: deleted_confirmed forwarded from response
  sr08: Missing item without uuid → skipped
  sr09: DeferredUploadQueue thread safety (add/pop/len)
  sr10: DeferredUploadQueue close signal
"""
from __future__ import annotations

import importlib.util
import sys
import threading
from pathlib import Path

import pytest

# Load sync_response_handler without calibre __init__
_plugin_root = Path(__file__).resolve().parents[3] / 'sync_calimob'
_srh_path = _plugin_root / 'sync_response_handler.py'
_srh_spec = importlib.util.spec_from_file_location('sync_response_handler', str(_srh_path))
sync_response_handler = importlib.util.module_from_spec(_srh_spec)
_srh_spec.loader.exec_module(sync_response_handler)

DeferredUploadQueue = sync_response_handler.DeferredUploadQueue
process_sync_response = sync_response_handler.process_sync_response


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_response(
    updates=None, missing=None, deleted=None,
    deleted_confirmed=None, skipped_hash=0,
):
    return {
        'updates_for_client': updates or [],
        'missing_from_server': missing or [],
        'deleted_on_server': deleted or [],
        'deleted_confirmed': deleted_confirmed or [],
        'skipped_hash': skipped_hash,
    }


# ── process_sync_response tests ─────────────────────────────────────────────

class TestProcessSyncResponse:

    def test_sr01_updates_missing_deleted_split(self):
        """Parse response with updates + missing + deleted → correct split."""
        updates = [{'uuid': 'u1', 'title': 'Book 1'}]
        missing = [{'uuid': 'm1', 'needs_metadata': True}]
        deleted = ['d1', 'd2']

        q = DeferredUploadQueue()
        result = process_sync_response(
            _make_response(updates=updates, missing=missing, deleted=deleted),
            q,
        )

        assert result['updates_for_client'] == updates
        assert result['deleted_on_server'] == deleted
        assert 'm1' in result['needs_metadata_push']

    def test_sr02_needs_cover_queued(self):
        """Missing item with needs_cover=true → queued in upload queue."""
        missing = [{'uuid': 'c1', 'needs_cover': True, 'needs_files': False}]
        q = DeferredUploadQueue()

        result = process_sync_response(_make_response(missing=missing), q)

        assert result['covers_queued'] == 1
        assert result['files_queued'] == 0
        items = q.items()
        assert len(items) == 1
        assert items[0]['uuid'] == 'c1'
        assert items[0]['needs_cover'] is True
        assert items[0]['needs_files'] is False

    def test_sr03_needs_files_with_targets_queued(self):
        """Missing item with needs_files=true + file_upload_targets → queued with targets."""
        targets = [
            {'format': 'EPUB', 'upload_url': 'https://s3/presigned/1'},
            {'format': 'PDF', 'upload_url': 'https://s3/presigned/2'},
        ]
        missing = [{
            'uuid': 'f1',
            'needs_cover': False,
            'needs_files': True,
            'file_upload_targets': targets,
        }]
        q = DeferredUploadQueue()

        result = process_sync_response(_make_response(missing=missing), q)

        assert result['files_queued'] == 1
        assert result['covers_queued'] == 0
        items = q.items()
        assert len(items) == 1
        assert items[0]['uuid'] == 'f1'
        assert items[0]['file_upload_targets'] == targets

    def test_sr04_needs_metadata_push(self):
        """Missing item with needs_metadata → UUID added to needs_metadata_push."""
        missing = [
            {'uuid': 'nm1', 'needs_metadata': True},
            {'uuid': 'nm2', 'needs_metadata': False},
            {'uuid': 'nm3', 'needs_metadata': True},
        ]
        q = DeferredUploadQueue()

        result = process_sync_response(_make_response(missing=missing), q)

        assert result['needs_metadata_push'] == ['nm1', 'nm3']

    def test_sr05_empty_response(self):
        """Empty response → all fields zero/empty."""
        q = DeferredUploadQueue()
        result = process_sync_response(_make_response(), q)

        assert result['updates_for_client'] == []
        assert result['needs_metadata_push'] == []
        assert result['deleted_on_server'] == []
        assert result['deleted_confirmed'] == []
        assert result['skipped_hash'] == 0
        assert result['covers_queued'] == 0
        assert result['files_queued'] == 0
        assert q.is_empty()

    def test_sr06_skipped_hash_forwarded(self):
        """skipped_hash count is forwarded from response."""
        q = DeferredUploadQueue()
        result = process_sync_response(_make_response(skipped_hash=42), q)
        assert result['skipped_hash'] == 42

    def test_sr07_deleted_confirmed_forwarded(self):
        """deleted_confirmed is forwarded from response."""
        confirmed = ['dc1', 'dc2']
        q = DeferredUploadQueue()
        result = process_sync_response(
            _make_response(deleted_confirmed=confirmed), q
        )
        assert result['deleted_confirmed'] == confirmed

    def test_sr08_missing_without_uuid_skipped(self):
        """Missing item without uuid field → skipped entirely."""
        missing = [
            {'needs_cover': True},  # no uuid
            {'uuid': 'valid', 'needs_cover': True},
        ]
        q = DeferredUploadQueue()
        result = process_sync_response(_make_response(missing=missing), q)

        assert result['covers_queued'] == 1
        items = q.items()
        assert len(items) == 1
        assert items[0]['uuid'] == 'valid'

    def test_sr_both_cover_and_files(self):
        """Item needing both cover and files counts in both."""
        missing = [{'uuid': 'both1', 'needs_cover': True, 'needs_files': True}]
        q = DeferredUploadQueue()
        result = process_sync_response(_make_response(missing=missing), q)

        assert result['covers_queued'] == 1
        assert result['files_queued'] == 1
        items = q.items()
        assert len(items) == 1
        assert items[0]['needs_cover'] is True
        assert items[0]['needs_files'] is True


# ── DeferredUploadQueue tests ────────────────────────────────────────────────

class TestDeferredUploadQueue:

    def test_sr09_add_pop_len(self):
        """Basic add/pop/len operations."""
        q = DeferredUploadQueue()
        assert len(q) == 0
        assert q.is_empty()

        q.add({'uuid': 'a'})
        q.add({'uuid': 'b'})
        assert len(q) == 2

        item = q.pop()
        assert item['uuid'] == 'a'
        assert len(q) == 1

        item = q.pop()
        assert item['uuid'] == 'b'
        assert q.is_empty()

        assert q.pop() is None

    def test_sr10_close_signal(self):
        """close() sets closed flag."""
        q = DeferredUploadQueue()
        assert q.closed is False
        q.close()
        assert q.closed is True

    def test_items_returns_copy(self):
        """items() returns a copy, not a reference to internal list."""
        q = DeferredUploadQueue()
        q.add({'uuid': 'x'})
        snapshot = q.items()
        q.add({'uuid': 'y'})
        assert len(snapshot) == 1  # snapshot not affected

    def test_thread_safety_concurrent_adds(self):
        """Multiple threads adding concurrently should not lose items."""
        q = DeferredUploadQueue()
        n_threads = 8
        items_per_thread = 100

        def adder(tid):
            for i in range(items_per_thread):
                q.add({'tid': tid, 'i': i})

        threads = [threading.Thread(target=adder, args=(t,)) for t in range(n_threads)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert len(q) == n_threads * items_per_thread
