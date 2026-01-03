from __future__ import annotations

import uuid
from datetime import datetime, timezone
from unittest.mock import Mock
from types import SimpleNamespace

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
    worker._record_book_mapping(10, {'uuid': 'UUID-A', 'title': 'T', 'version': 'v1', 'cover': {'cover_hash': 'h'}})
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


def test_format_last_modified_normalizes_values():
    worker = _make_worker()
    assert worker._format_last_modified(datetime(2025, 1, 1, 12, 0)) == '2025-01-01T12:00:00Z'
    assert worker._format_last_modified(123456) == '123456'
    assert worker._format_last_modified(None) is None


def test_update_book_cache_records_formats(monkeypatch):
    snapshot = {'notes': {'existing': True}}
    def fake_get(library_id, book_id, db=None):
        return snapshot

    captured = {}
    def fake_update(library_id, book_id, updates, db=None):
        captured.update(updates)

    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', fake_get)
    monkeypatch.setattr(sync_worker.cfg, 'update_book_mapping', fake_update)

    formats = {
        'EPUB': {'hash': 'sha256:abc', 'mtime': 123, 'size': 999},
        'PDF': {'hash': 'sha256:def', 'mtime': 999, 'size': 111}
    }
    sync_worker.cfg.update_book_cache('lib-123', 1, formats, 'sha256:cover', 'ts-1', db=None)

    assert 'notes' in captured
    book_cache = captured['notes']['book_cache']
    assert book_cache['last_modified'] == 'ts-1'
    assert book_cache['files']['EPUB']['hash'] == 'sha256:abc'


def test_update_book_cache_records_cover_only(monkeypatch):
    snapshot = {'notes': {}}
    captured = {}

    def fake_get(library_id, book_id, db=None):
        return snapshot

    def fake_update(library_id, book_id, updates, db=None):
        captured.update(updates)

    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', fake_get)
    monkeypatch.setattr(sync_worker.cfg, 'update_book_mapping', fake_update)

    sync_worker.cfg.update_book_cache('lib-123', 1, {}, 'sha256:cover', 'ts-2', db=None)
    assert captured['notes']['book_cache']['cover']['hash'] == 'sha256:cover'
    assert captured['notes']['book_cache']['last_modified'] == 'ts-2'


def test_apply_update_skips_metadata_save_when_no_change(monkeypatch):
    worker = _make_worker()

    worker.progress_percent_column = None
    worker.favorite_column = None

    class MetadataHolder(SimpleNamespace):
        pass

    now_ts = 1767442000
    metadata = MetadataHolder(
        title='Book Title',
        sort='Book Title Sort',
        author_sort='Author Lastname',
        series='Series Name',
        publisher='Publisher',
        comments='Notes',
        authors=['Author'],
        languages=['eng'],
        tags=['fiction'],
        series_index=1.0,
        rating=6.0,
        last_modified=datetime.fromtimestamp(now_ts, tz=timezone.utc),
    )

    class TrackingDb:
        def __init__(self, metadata_obj):
            self.metadata_obj = metadata_obj
            self.data = Mock()
            self.data.has_id = lambda book_id: True
            self.set_metadata = Mock()

        def get_metadata(self, book_id, index_is_id=True):
            return self.metadata_obj

        def cover(self, book_id, index_is_id=True):
            return None

    test_db = TrackingDb(metadata)
    worker.db = test_db
    worker._resolve_local_book_id = lambda item: 42

    item = {
        'title': 'Book Title',
        'title_sort': 'Book Title Sort',
        'author_sort': 'Author Lastname',
        'series': {'name': 'Series Name', 'series_index': 1.0},
        'publisher': 'Publisher',
        'comments': 'Notes',
        'authors': [{'name': 'Author'}],
        'languages': ['eng'],
        'tags': ['fiction'],
        'rating': 3,
        'last_modified': now_ts,
    }

    worker._apply_update(item, skip_cover=True)
    test_db.set_metadata.assert_not_called()


def test_item_matches_metadata_considers_last_modified():
    worker = _make_worker()

    metadata = SimpleNamespace(
        title='Book Title',
        sort='Book Title Sort',
        author_sort='Author Lastname',
        series=None,
        publisher=None,
        comments=None,
        authors=[],
        languages=[],
        tags=[],
        series_index=1.0,
        rating=3.0,
        last_modified=datetime(2024, 11, 14, tzinfo=timezone.utc),
    )

    item = {
        'title': 'Book Title',
        'title_sort': 'Book Title Sort',
        'author_sort': 'Author Lastname',
        'series': None,
        'publisher': None,
        'comments': None,
        'authors': [],
        'languages': [],
        'tags': [],
        'series_index': 1.0,
        'rating': 3.0,
        'last_modified': '2024-11-14T00:00:00Z',
    }

    metadata_dict = {
        'title': 'Book Title',
        'title_sort': 'Book Title Sort',
        'author_sort': 'Author Lastname',
        'authors': [],
        'languages': [],
        'tags': [],
        'series_index': 1.0,
        'rating': 3.0,
        'last_modified': '2024-11-14T00:00:00Z',
    }

    assert worker._item_matches_metadata(metadata, item, metadata_dict=metadata_dict)

    metadata_dict['last_modified'] = '2024-11-14T00:00:01Z'
    item['last_modified'] = '2024-11-14T00:00:01Z'
    assert not worker._item_matches_metadata(metadata, item, metadata_dict=metadata_dict)


def test_write_custom_columns_skips_when_values_equal(monkeypatch):
    worker = _make_worker()
    worker.progress_percent_column = 'progress_pct'
    worker.favorite_column = 'favorite_flag'

    class FieldMetadata:
        def key_to_label(self, key):
            return key

    worker.db.field_metadata = FieldMetadata()
    worker.db.get_custom = Mock(side_effect=lambda book_id, label, index_is_id=True: (
        42.0 if label == 'progress_pct' else True if label == 'favorite_flag' else None
    ))
    worker.db.set_custom = Mock()

    worker._write_custom_columns(1, {'progress_percent': 42, 'favorite': True})

    worker.db.set_custom.assert_not_called()

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


def test_push_sync_saves_progress_cursor(monkeypatch):
    worker = _make_worker()
    worker.mapping = {}
    worker.client = Mock()
    worker.client.post_sync = Mock(return_value={
        'results': [{'status': 'applied', 'client_change_id': 'c1'}],
        'progress_cursor': 'progress-123',
        'new_cursor': None,
    })
    worker._process_batch_results = Mock()
    worker._collect_local_changes_progressive = Mock(return_value=[(
        [{'op': 'update', 'item': {'id': 1, 'uuid': 'u1', 'title': 'T', 'last_modified': 1}, 'idempotency_key': 'c1'}],
        {},
        {},
    )])
    saved = {}

    def save_cursor(cursor):
        saved['cursor'] = cursor

    worker.save_cursor = save_cursor

    summary = worker.push_sync(progress_callback=None, full_sync=False)
    assert saved.get('cursor') == 'progress-123'


def test_push_sync_saves_progress_cursor_each_batch():
    worker = _make_worker()
    worker.mapping = {}
    worker.client = Mock()
    worker.client.post_sync = Mock(side_effect=[
        {
            'results': [{'status': 'applied', 'client_change_id': 'c1'}],
            'progress_cursor': 'progress-1',
            'new_cursor': 'new-1',
        },
        {
            'results': [{'status': 'applied', 'client_change_id': 'c2'}],
            'progress_cursor': 'progress-2',
            'new_cursor': 'new-2',
        },
    ])
    worker._process_batch_results = Mock()
    worker._collect_local_changes_progressive = Mock(return_value=[
        ([{'op': 'update', 'item': {'id': 1, 'uuid': 'u1', 'title': 'T1', 'last_modified': 1}, 'idempotency_key': 'c1'}], {}, {}),
        ([{'op': 'update', 'item': {'id': 2, 'uuid': 'u2', 'title': 'T2', 'last_modified': 2}, 'idempotency_key': 'c2'}], {}, {}),
    ])

    saved = []

    def save_cursor(cursor):
        saved.append(cursor)

    worker.save_cursor = save_cursor

    worker.push_sync(progress_callback=None, full_sync=False)
    assert saved == ['progress-1', 'progress-2']
