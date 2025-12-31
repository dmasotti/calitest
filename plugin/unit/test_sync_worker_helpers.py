from __future__ import annotations

import uuid
from datetime import datetime
from unittest.mock import Mock

import pytest

from calibre_plugins.sync_calimob import sync_worker


class DummyDb:
    def __init__(self, ids=None):
        self.data = Mock()
        self.data.has_id = lambda bid: True
        self._ids = ids or []

    def all_ids(self):
        return list(self._ids)

    def set_metadata(self, book_id, metadata):
        metadata.uuid = metadata.uuid
        return metadata


class DummyMetadata:
    def __init__(self, uuid_value=None):
        self.uuid = uuid_value


def _make_worker(ids=None):
    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    worker.library_id = 'lib-123'
    worker.calimob_library_id = 9
    worker.db = DummyDb(ids or [])
    worker._uuid_to_book_id = {}
    return worker


def test_build_client_inventory_empty(monkeypatch):
    worker = _make_worker([])
    monkeypatch.setattr(sync_worker.cfg, 'get_book_uuid_cache_for_library', lambda lib, db=None: {})
    assert worker._build_client_inventory() is None


def test_build_client_inventory_returns_uuids(monkeypatch):
    worker = _make_worker()
    monkeypatch.setattr(sync_worker.cfg, 'get_book_uuid_cache_for_library', lambda lib, db=None: {
        '1': {'uuid': 'u1'},
        '2': {'uuid': 'u2'},
        '3': {'uuid': 'u1'}
    })
    inv = worker._build_client_inventory()
    assert inv['uuids'] == ['u1', 'u2']


def test_get_synced_uuids_from_cache(monkeypatch):
    worker = _make_worker()
    monkeypatch.setattr(sync_worker.cfg, 'get_book_uuid_cache_for_library', lambda lib, db=None: {
        '1': {'uuid': 'a'},
        '2': {'uuid': 'b'}
    })
    result = worker._get_synced_uuids()
    assert result == {'a', 'b'}


def test_ingest_inventory_sets_remote_uuids():
    worker = _make_worker()
    worker._ingest_inventory({'uuids': [' foo ', 'bar']}, label='test')
    assert worker._remote_uuids == {'foo', 'bar'}


def test_cache_and_record_mapping(monkeypatch):
    worker = _make_worker()
    worker._iso_now = lambda: '2025-01-01T00:00:00Z'
    captured = {}

    def update(library_id, book_id, updates, db=None):
        captured['args'] = (library_id, book_id)
        captured['updates'] = updates

    monkeypatch.setattr(sync_worker.cfg, 'update_book_mapping', update)
    worker._cache_book_uuid = sync_worker.SyncWorker._cache_book_uuid.__get__(worker, sync_worker.SyncWorker)
    worker._record_book_mapping(10, {'uuid': 'UUID-A', 'title': 'T', 'version': 'v1', 'cover': {'cover_hash': 'h'}, 'client_ids': {'calibre': '1'}})
    assert captured['args'] == ('lib-123', 10)
    assert captured['updates']['last_sync_result'] == 'collected'


def test_mark_book_deleted(monkeypatch):
    worker = _make_worker()
    called = {}

    def mark(library_id, book_id, deleted_at, db=None):
        called['args'] = (library_id, book_id, deleted_at)

    monkeypatch.setattr(sync_worker.cfg, 'mark_book_deleted', mark)
    worker._mark_book_deleted_in_mapping(5, datetime(2025, 1, 1))
    assert called['args'][0] == 'lib-123'
    assert called['args'][1] == 5
    assert called['args'][2] == '2025-01-01T00:00:00Z'


def test_cache_book_uuid(monkeypatch):
    worker = _make_worker()
    called = {}

    def cache(library_id, book_id, book_uuid, db=None):
        called['args'] = (library_id, book_id, book_uuid)

    monkeypatch.setattr(sync_worker.cfg, 'cache_book_uuid', cache)
    worker._cache_book_uuid(42, 'uuid-42')
    assert called['args'][0] == 'lib-123'
    assert worker._uuid_to_book_id['uuid-42'] == 42


def test_deterministic_uuid_uses_cached():
    worker = _make_worker()
    worker._get_cached_book_uuid = Mock(return_value='cached-uuid')
    assert worker._deterministic_book_uuid(11) == 'cached-uuid'


def test_deterministic_uuid_falls_back(monkeypatch):
    worker = _make_worker()
    worker._get_cached_book_uuid = Mock(return_value=None)
    expected = str(uuid.uuid5(uuid.NAMESPACE_URL, f'{worker.library_id}:7'))
    assert worker._deterministic_book_uuid(7) == expected


def test_ensure_book_uuid_persists(monkeypatch):
    worker = _make_worker()
    metadata = DummyMetadata()
    worker.db.set_metadata = Mock()
    result = worker._ensure_book_uuid(77, metadata)
    assert result == metadata.uuid
    assert metadata.uuid is not None


def test_ensure_book_uuid_handles_failure(monkeypatch):
    worker = _make_worker()
    metadata = DummyMetadata()
    worker.db.set_metadata = Mock(side_effect=Exception('boom'))
    result = worker._ensure_book_uuid(77, metadata)
    assert result is None


def test_upload_files_for_batch_uses_rest_client(tmp_path):
    worker = _make_worker()
    worker.client = Mock()
    worker.client.upload_file = Mock(return_value={'status': 'uploaded'})
    book_path = tmp_path / 'book.epub'
    book_path.write_bytes(b'binary content')
    file_cache = {
        1: {
            'EPUB': {
                'path': str(book_path),
                'hash': 'sha256:abc123',
                'name': 'book.epub',
                'size': book_path.stat().st_size,
            }
        }
    }
    files_to_upload = [{
        'server_item_id': 'server-1',
        'calibre_book_id': 1,
        'format': 'EPUB',
        'upload_url': 'https://api.example.com/upload',
        'book_title': 'Test Book',
    }]
    summary = {'file_results': [], 'files_uploaded': 0, 'files_failed': 0, 'errors': []}
    worker._upload_files_for_batch(files_to_upload, summary, file_cache)
    worker.client.upload_file.assert_called_once()
    assert summary['files_uploaded'] == 1
    assert summary['files_failed'] == 0


def test_upload_file_missing_path(tmp_path):
    worker = _make_worker()
    worker.client = Mock()
    worker.db.format = Mock(side_effect=AttributeError())
    file_cache = {}
    file_info = {
        'server_item_id': 'server-2',
        'calibre_book_id': 1,
        'format': 'EPUB',
        'upload_url': 'https://api.example.com/upload',
        'book_title': 'Missing Book',
    }
    result = worker._upload_file(file_info, file_cache)
    assert not result['success']
    assert result['step'] == 'locate'
