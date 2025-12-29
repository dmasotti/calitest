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


def test_build_client_inventory_empty():
    worker = _make_worker([])
    assert worker._build_client_inventory() == {
        'min': None,
        'max': None,
        'active': [],
        'missing': []
    }


def test_build_client_inventory_ranges():
    worker = _make_worker([5, 1, 2, 4])
    inv = worker._build_client_inventory()
    assert inv['min'] == 1
    assert inv['max'] == 5
    assert inv['active'] == ['1-2', '4-5']


def test_compress_expand_ranges():
    worker = _make_worker()
    assert worker._compress_to_ranges([3, 4, 7, 8, 9]) == ['3-4', '7-9']
    assert worker._expand_ranges(['2-3', 5, 6]) == {2, 3, 5, 6}


def test_expand_range_format():
    worker = _make_worker()
    payload = {'min': 1, 'max': 5, 'active': ['1-3', 5], 'missing': ['2']}
    assert worker._expand_range_format(payload) == {1, 2, 3, 5}


def test_iso_now_format():
    worker = _make_worker()
    now = worker._iso_now()
    assert now.endswith('Z')
    assert 'T' in now


def test_cache_and_record_mapping(monkeypatch):
    worker = _make_worker()
    worker._iso_now = lambda: '2025-01-01T00:00:00Z'
    captured = {}

    def update(library_id, book_id, updates):
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

    def mark(library_id, book_id, deleted_at):
        called['args'] = (library_id, book_id, deleted_at)

    monkeypatch.setattr(sync_worker.cfg, 'mark_book_deleted', mark)
    worker._mark_book_deleted_in_mapping(5, datetime(2025, 1, 1))
    assert called['args'][0] == 'lib-123'
    assert called['args'][1] == 5
    assert called['args'][2] == '2025-01-01T00:00:00Z'


def test_cache_book_uuid(monkeypatch):
    worker = _make_worker()
    called = {}

    def cache(library_id, book_id, book_uuid):
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
