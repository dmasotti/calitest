from __future__ import annotations

import copy
import json
import os
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
    worker._target_debug_uuid = None  # Disable debug dumps in tests
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


def test_item_matches_metadata_ignores_last_modified():
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


def test_v5_push_missing_items_uploads_files_when_local_is_newer(monkeypatch):
    worker = _make_worker()
    worker.status_tag_mappings = {}
    worker.library_id = 'lib-123'
    worker.calimob_library_id = 9

    class DbForUpload:
        def __init__(self):
            self.data = Mock()
            self.data.has_id = lambda _: True
            self.remove_format = Mock()

        def get_metadata(self, book_id, index_is_id=True):
            return SimpleNamespace(
                title='Book',
                has_cover=False,
                last_modified=datetime(2026, 2, 22, 18, 0, tzinfo=timezone.utc),
            )

        def formats(self, book_id, index_is_id=True):
            return 'PDF'

    worker.db = DbForUpload()
    worker._build_files_array_for_book = lambda _book_id: [{'format': 'PDF', 'file_hash': 'abc'}]

    upload_calls = []
    worker._upload_file = lambda file_info, _cache: upload_calls.append(file_info) or {'success': True}
    worker.client = SimpleNamespace(post_sync=lambda **kwargs: {
        'results': [{
            'status': 'applied',
            'file_uploads': [{'format': 'PDF', 'upload_url': 'https://example.test/upload/pdf'}],
            'server_item': {'files': []},
        }]
    })

    sm = SimpleNamespace(
        calibre_to_json_item=lambda *args, **kwargs: {'uuid': 'u1', 'title': 'Book'},
        calculate_cover_hash=lambda *_: None,
    )

    summary = {'errors': [], 'books_created': 0, 'books_synced': 0}
    err = worker._v5_push_missing_items(
        to_upload=[{'uuid': 'u1', 'needs_files': True, 'needs_metadata': False, 'needs_cover': False}],
        missing_id_map={'u1': 1},
        uuids_deleted_locally=set(),
        sync_library_path='/tmp',
        sm=sm,
        summary=summary,
        updates_by_uuid={'u1': {'last_modified': int(datetime(2026, 2, 20, tzinfo=timezone.utc).timestamp())}},
    )

    assert err is False
    assert len(upload_calls) == 1
    assert summary.get('files_uploaded', 0) == 1
    worker.db.remove_format.assert_not_called()


def test_v5_push_missing_items_deletes_local_files_when_server_is_newer(monkeypatch):
    worker = _make_worker()
    worker.status_tag_mappings = {}
    worker.library_id = 'lib-123'
    worker.calimob_library_id = 9

    class DbForDelete:
        def __init__(self):
            self.data = Mock()
            self.data.has_id = lambda _: True
            self.remove_format = Mock()

        def get_metadata(self, book_id, index_is_id=True):
            return SimpleNamespace(
                title='Book',
                has_cover=False,
                last_modified=datetime(2026, 2, 20, 18, 0, tzinfo=timezone.utc),
            )

        def formats(self, book_id, index_is_id=True):
            return 'PDF'

    worker.db = DbForDelete()
    worker._build_files_array_for_book = lambda _book_id: [{'format': 'PDF', 'file_hash': 'abc'}]

    upload_calls = []
    worker._upload_file = lambda file_info, _cache: upload_calls.append(file_info) or {'success': True}
    worker.client = SimpleNamespace(post_sync=lambda **kwargs: {'results': [{'status': 'applied'}]})

    sm = SimpleNamespace(
        calibre_to_json_item=lambda *args, **kwargs: {'uuid': 'u1', 'title': 'Book'},
        calculate_cover_hash=lambda *_: None,
    )

    summary = {'errors': [], 'books_created': 0, 'books_updated': 0, 'books_synced': 0, 'files_deleted_local': 0}
    err = worker._v5_push_missing_items(
        to_upload=[{'uuid': 'u1', 'needs_files': True, 'needs_metadata': False, 'needs_cover': False}],
        missing_id_map={'u1': 1},
        uuids_deleted_locally=set(),
        sync_library_path='/tmp',
        sm=sm,
        summary=summary,
        updates_by_uuid={'u1': {'last_modified': int(datetime(2026, 2, 22, tzinfo=timezone.utc).timestamp())}},
    )

    assert err is False
    assert len(upload_calls) == 0
    assert worker._pending_local_format_deletes.get(1) == {'PDF'}


def test_v5_push_missing_items_warns_when_upload_urls_missing(monkeypatch):
    worker = _make_worker()
    worker.status_tag_mappings = {}
    worker.library_id = 'lib-123'
    worker.calimob_library_id = 9

    class DbForUpload:
        def __init__(self):
            self.data = Mock()
            self.data.has_id = lambda _: True
            self.remove_format = Mock()

        def get_metadata(self, book_id, index_is_id=True):
            return SimpleNamespace(
                title='Book',
                has_cover=False,
                last_modified=datetime(2026, 2, 22, 18, 0, tzinfo=timezone.utc),
            )

        def formats(self, book_id, index_is_id=True):
            return 'PDF'

    worker.db = DbForUpload()
    worker._build_files_array_for_book = lambda _book_id: [{'format': 'PDF', 'file_hash': 'abc'}]

    worker._upload_file = Mock(return_value={'success': True})
    worker.client = SimpleNamespace(post_sync=lambda **kwargs: {
        'results': [{'status': 'applied', 'file_uploads': [], 'server_item': {'files': []}}]
    })

    sm = SimpleNamespace(
        calibre_to_json_item=lambda *args, **kwargs: {'uuid': 'u1', 'title': 'Book'},
        calculate_cover_hash=lambda *_: None,
    )

    summary = {'errors': [], 'books_created': 0, 'books_synced': 0}
    err = worker._v5_push_missing_items(
        to_upload=[{'uuid': 'u1', 'needs_files': True, 'needs_metadata': False, 'needs_cover': False}],
        missing_id_map={'u1': 1},
        uuids_deleted_locally=set(),
        sync_library_path='/tmp',
        sm=sm,
        summary=summary,
        updates_by_uuid={'u1': {'last_modified': int(datetime(2026, 2, 20, tzinfo=timezone.utc).timestamp())}},
    )

    assert err is False
    assert worker._upload_file.call_count == 0
    warnings = summary.get('warnings', [])
    assert warnings
    assert warnings[0]['phase'] == 'push_missing_file_upload'

def test_metadata_signature_ignores_timestamp_and_extra_author_fields():
    worker = _make_worker()
    json_item = {
        'title': 'Book Title',
        'title_sort': 'Book Title Sort',
        'comments': 'Notes',
        'authors': [{'name': 'Author', 'role': 'author', 'position': 0}],
        'series': {'name': 'Series Name', 'series_index': 1.0},
        'identifiers': {'isbn': '123'},
        'publisher': 'Pub',
        'pubdate': 123,
        'languages': ['eng'],
        'tags': [],
        'cover': {'cover_hash': 'sha256:abc', 'has_cover': 'Yes', 'cover_url': 'http://example.com/c.jpg'},
        'source': {'client': 'calibre', 'client_library': 'lib-uuid'},
        'progress_percent': None,
        'favorite': False,
    }
    format_cache = {'CBR': {'hash': 'sha256:file', 'size': 42}}
    base_hash = worker._compute_metadata_signature(json_item, format_cache, 'sha256:cover')

    mutated = copy.deepcopy(json_item)
    mutated['last_modified'] = 999
    mutated['authors'][0]['id'] = -1
    mutated['authors'][0]['client_ids'] = ['a']
    mutated['authors'][0]['link'] = ''
    mutated['series']['client_ids'] = ['1']
    mutated['cover']['cover_url'] = 'https://example.org/c2.jpg'

    assert worker._compute_metadata_signature(mutated, format_cache, 'sha256:cover') == base_hash


def test_metadata_signature_changes_when_identifiers_change():
    worker = _make_worker()
    json_item = {
        'title': 'Book Title',
        'authors': [{'name': 'Author', 'role': 'author', 'position': 0}],
        'identifiers': {'isbn': '1111111111', 'amazon': 'A1'},
        'cover': {'cover_hash': 'sha256:abc', 'has_cover': True},
    }
    format_cache = {}
    base_hash = worker._compute_metadata_signature(json_item, format_cache, 'sha256:cover')

    mutated = copy.deepcopy(json_item)
    mutated['identifiers']['isbn'] = '2222222222'

    assert worker._compute_metadata_signature(mutated, format_cache, 'sha256:cover') != base_hash


def _load_metadata_hash_samples():
    fixture_path = os.path.join(os.path.dirname(__file__), '../fixtures/metadata_hash_samples.json')
    with open(fixture_path, encoding='utf-8') as fh:
        return json.load(fh)


def test_metadata_signature_matches_server_sample():
    worker = _make_worker()
    sample = _load_metadata_hash_samples()[0]
    computed = worker._compute_metadata_signature(sample['json_item'], sample['format_cache'], sample.get('cover_hash'))
    assert computed == sample['expected_hash']


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


def test_sync_v5_sends_client_inventory_in_chunks(monkeypatch):
    worker = _make_worker()
    worker.gui = None
    worker.calimob_library_id = 8
    worker.library_id = '1685fd4f-054e-4451-9df8-119c27fc1289'
    worker.status_tag_mappings = {}

    calls = []

    class FakeClient:
        def sync_v5(self, **kwargs):
            calls.append(kwargs)
            if kwargs.get('client_cursor', 0) == 0:
                return {
                    'updates_for_client': [],
                    'missing_from_server': [],
                    'deleted_on_server': [],
                    'cursor': '100:1',
                    'has_more': False,
                    'client_cursor_next': 2,
                    'client_done': False,
                    'skipped_hash': 0,
                }
            return {
                'updates_for_client': [],
                'missing_from_server': [],
                'deleted_on_server': [],
                'cursor': '100:1',
                'has_more': False,
                'client_cursor_next': 3,
                'client_done': True,
                'skipped_hash': 0,
            }

    worker.client = FakeClient()

    monkeypatch.setenv('CALIMOB_V5_CLIENT_BATCH_SIZE', '2')
    monkeypatch.setattr(worker, 'get_pull_cursor', lambda: None)
    monkeypatch.setattr(worker, 'save_pull_cursor', lambda c: None)
    monkeypatch.setattr(worker, 'save_cursor', lambda c: None)
    monkeypatch.setattr(worker, '_v5_get_resume_state', lambda: None)
    monkeypatch.setattr(worker, '_v5_save_resume_state', lambda state: None)
    monkeypatch.setattr(worker, '_v5_clear_resume_state', lambda: None)
    monkeypatch.setattr(
        worker,
        '_v5_collect_client_books_candidates',
        lambda **kwargs: (
            ['d1'],
            {'u1': 1, 'u2': 2, 'u3': 3},
            [
                {'id': 1, 'uuid': 'u1', 'last_modified': 10},
                {'id': 2, 'uuid': 'u2', 'last_modified': 20},
                {'id': 3, 'uuid': 'u3', 'last_modified': 30},
            ],
        ),
    )
    monkeypatch.setattr(
        worker,
        '_v5_build_client_books_chunk',
        lambda books_chunk, **kwargs: {
            b['uuid']: {'m': 'h-%s' % b['uuid'], 'c': None, 'f': None, 'lm': b['last_modified']}
            for b in books_chunk
        },
    )
    monkeypatch.setattr(worker, '_v5_apply_deleted_on_server', lambda **kwargs: (set(), False))
    monkeypatch.setattr(worker, '_v5_resolve_missing_id_map', lambda **kwargs: ({}, False))
    monkeypatch.setattr(worker, '_v5_push_missing_items', lambda **kwargs: False)
    monkeypatch.setattr(worker, '_v5_apply_updates_batch', lambda **kwargs: ([], False))
    monkeypatch.setattr(worker, '_v5_download_files_batch', lambda **kwargs: None)

    summary = worker.sync_v5()

    assert summary['sync_version'] == 'v5'
    assert len(calls) == 2
    assert calls[0]['client_cursor'] == 0
    assert calls[0]['client_batch_size'] == 2
    assert set(calls[0]['client_books']['b'].keys()) == {'u1', 'u2'}
    assert calls[0]['client_books']['d'] == ['d1']
    assert calls[1]['client_cursor'] == 2
    assert calls[1]['client_batch_size'] == 2
    assert set(calls[1]['client_books']['b'].keys()) == {'u3'}
    assert calls[1]['client_books']['d'] == []


def test_sync_v5_accumulates_skipped_hash_count_from_server(monkeypatch):
    worker = _make_worker()
    worker.gui = None
    worker.calimob_library_id = 8
    worker.library_id = '1685fd4f-054e-4451-9df8-119c27fc1289'
    worker.status_tag_mappings = {}

    class FakeClient:
        def __init__(self):
            self.calls = 0

        def sync_v5(self, **kwargs):
            self.calls += 1
            if self.calls == 1:
                return {
                    'updates_for_client': [],
                    'missing_from_server': [],
                    'deleted_on_server': [],
                    'cursor': '100:1',
                    'has_more': True,
                    'client_cursor_next': 1,
                    'client_done': False,
                    'skipped_hash': 3,
                }
            return {
                'updates_for_client': [],
                'missing_from_server': [],
                'deleted_on_server': [],
                'cursor': '100:2',
                'has_more': False,
                'client_cursor_next': 2,
                'client_done': True,
                'skipped_hash': 2,
            }

    worker.client = FakeClient()

    monkeypatch.setenv('CALIMOB_V5_CLIENT_BATCH_SIZE', '1')
    monkeypatch.setattr(worker, 'get_pull_cursor', lambda: None)
    monkeypatch.setattr(worker, 'save_pull_cursor', lambda c: None)
    monkeypatch.setattr(worker, 'save_cursor', lambda c: None)
    monkeypatch.setattr(worker, '_v5_get_resume_state', lambda: None)
    monkeypatch.setattr(worker, '_v5_save_resume_state', lambda state: None)
    monkeypatch.setattr(worker, '_v5_clear_resume_state', lambda: None)
    monkeypatch.setattr(
        worker,
        '_v5_collect_client_books_candidates',
        lambda **kwargs: (
            [],
            {'u1': 1, 'u2': 2},
            [
                {'id': 1, 'uuid': 'u1', 'last_modified': 10},
                {'id': 2, 'uuid': 'u2', 'last_modified': 20},
            ],
        ),
    )
    monkeypatch.setattr(
        worker,
        '_v5_build_client_books_chunk',
        lambda books_chunk, **kwargs: {
            b['uuid']: {'m': 'h-%s' % b['uuid'], 'c': None, 'f': None, 'lm': b['last_modified']}
            for b in books_chunk
        },
    )
    monkeypatch.setattr(worker, '_v5_apply_deleted_on_server', lambda **kwargs: (set(), False))
    monkeypatch.setattr(worker, '_v5_resolve_missing_id_map', lambda **kwargs: ({}, False))
    monkeypatch.setattr(worker, '_v5_push_missing_items', lambda **kwargs: False)
    monkeypatch.setattr(worker, '_v5_apply_updates_batch', lambda **kwargs: ([], False))
    monkeypatch.setattr(worker, '_v5_download_files_batch', lambda **kwargs: None)

    summary = worker.sync_v5()
    assert summary['books_skipped_hash'] == 5


def test_sync_v5_streaming_hash_build_is_chunked(monkeypatch):
    worker = _make_worker()
    worker.gui = None
    worker.calimob_library_id = 8
    worker.library_id = '1685fd4f-054e-4451-9df8-119c27fc1289'
    worker.status_tag_mappings = {}
    worker.client = Mock()
    worker.client.sync_v5 = Mock(side_effect=[
        {
            'updates_for_client': [],
            'missing_from_server': [],
            'deleted_on_server': [],
            'cursor': '100:1',
            'has_more': False,
            'client_cursor_next': 2,
            'client_done': False,
            'skipped_hash': 0,
        },
        {
            'updates_for_client': [],
            'missing_from_server': [],
            'deleted_on_server': [],
            'cursor': '100:1',
            'has_more': False,
            'client_cursor_next': 3,
            'client_done': True,
            'skipped_hash': 0,
        },
    ])

    monkeypatch.setenv('CALIMOB_V5_CLIENT_BATCH_SIZE', '2')
    monkeypatch.setattr(worker, 'get_pull_cursor', lambda: None)
    monkeypatch.setattr(worker, 'save_pull_cursor', lambda c: None)
    monkeypatch.setattr(worker, 'save_cursor', lambda c: None)
    monkeypatch.setattr(worker, '_v5_get_resume_state', lambda: None)
    monkeypatch.setattr(worker, '_v5_save_resume_state', lambda state: None)
    monkeypatch.setattr(worker, '_v5_clear_resume_state', lambda: None)
    monkeypatch.setattr(
        worker,
        '_v5_collect_client_books_candidates',
        lambda **kwargs: (
            [],
            {'u1': 1, 'u2': 2, 'u3': 3},
            [
                {'id': 1, 'uuid': 'u1', 'last_modified': 10},
                {'id': 2, 'uuid': 'u2', 'last_modified': 20},
                {'id': 3, 'uuid': 'u3', 'last_modified': 30},
            ],
        ),
    )

    chunk_calls = []
    def fake_build_chunk(books_chunk, **kwargs):
        chunk_calls.append([b['uuid'] for b in books_chunk])
        return {
            b['uuid']: {'m': 'h-%s' % b['uuid'], 'c': None, 'f': None, 'lm': b['last_modified']}
            for b in books_chunk
        }
    monkeypatch.setattr(worker, '_v5_build_client_books_chunk', fake_build_chunk)
    monkeypatch.setattr(worker, '_v5_apply_deleted_on_server', lambda **kwargs: (set(), False))
    monkeypatch.setattr(worker, '_v5_resolve_missing_id_map', lambda **kwargs: ({}, False))
    monkeypatch.setattr(worker, '_v5_push_missing_items', lambda **kwargs: False)
    monkeypatch.setattr(worker, '_v5_apply_updates_batch', lambda **kwargs: ([], False))
    monkeypatch.setattr(worker, '_v5_download_files_batch', lambda **kwargs: None)

    worker.sync_v5()

    assert chunk_calls == [['u1', 'u2'], ['u3']]
    assert worker.client.sync_v5.call_count == 2


def test_sync_v5_resume_state_restores_client_cursor(monkeypatch):
    worker = _make_worker()
    worker.gui = None
    worker.calimob_library_id = 8
    worker.library_id = '1685fd4f-054e-4451-9df8-119c27fc1289'
    worker.status_tag_mappings = {}

    calls = []
    class FakeClient:
        def sync_v5(self, **kwargs):
            calls.append(kwargs)
            return {
                'updates_for_client': [],
                'missing_from_server': [],
                'deleted_on_server': [],
                'cursor': '100:1',
                'has_more': False,
                'client_cursor_next': 3,
                'client_done': True,
                'skipped_hash': 0,
            }
    worker.client = FakeClient()

    monkeypatch.setenv('CALIMOB_V5_CLIENT_BATCH_SIZE', '2')
    monkeypatch.setattr(worker, 'get_pull_cursor', lambda: None)
    monkeypatch.setattr(worker, 'save_pull_cursor', lambda c: None)
    monkeypatch.setattr(worker, 'save_cursor', lambda c: None)
    monkeypatch.setattr(worker, '_v5_clear_resume_state', lambda: None)

    monkeypatch.setattr(
        worker,
        '_v5_collect_client_books_candidates',
        lambda **kwargs: (
            [],
            {'u1': 1, 'u2': 2, 'u3': 3},
            [
                {'id': 1, 'uuid': 'u1', 'last_modified': 10},
                {'id': 2, 'uuid': 'u2', 'last_modified': 20},
                {'id': 3, 'uuid': 'u3', 'last_modified': 30},
            ],
        ),
    )
    monkeypatch.setattr(
        worker,
        '_v5_build_client_books_chunk',
        lambda books_chunk, **kwargs: {
            b['uuid']: {'m': 'h-%s' % b['uuid'], 'c': None, 'f': None, 'lm': b['last_modified']}
            for b in books_chunk
        },
    )
    monkeypatch.setattr(worker, '_v5_apply_deleted_on_server', lambda **kwargs: (set(), False))
    monkeypatch.setattr(worker, '_v5_resolve_missing_id_map', lambda **kwargs: ({}, False))
    monkeypatch.setattr(worker, '_v5_push_missing_items', lambda **kwargs: False)
    monkeypatch.setattr(worker, '_v5_apply_updates_batch', lambda **kwargs: ([], False))
    monkeypatch.setattr(worker, '_v5_download_files_batch', lambda **kwargs: None)

    saved_resume = []
    monkeypatch.setattr(worker, '_v5_save_resume_state', lambda state: saved_resume.append(dict(state)))
    monkeypatch.setattr(worker, '_v5_get_resume_state', lambda: {
        'resume_sig': worker._v5_build_resume_signature(
            [('u1', {'id': 1}, 10), ('u2', {'id': 2}, 20), ('u3', {'id': 3}, 30)],
            None,
            False
        ),
        'client_cursor': 2,
        'client_total': 3,
        'server_cursor': '100:1',
    })

    worker.sync_v5()

    assert calls[0]['client_cursor'] == 2
    assert set(calls[0]['client_books']['b'].keys()) == {'u3'}
    assert saved_resume, "resume state should be persisted during run"


def test_v5_push_missing_items_uploads_cover_on_mismatch(monkeypatch):
    worker = _make_worker()
    worker.gui = object()  # force db.cover path (no direct sqlite access)
    worker.client = Mock()
    worker.client.upload_cover = Mock(return_value={'status': 'uploaded'})
    worker.db.cover = Mock(return_value=b'cover-bytes')
    worker._v5_get_sync_cache_field_by_uuid = Mock(return_value=None)

    summary = {
        'books_created': 0,
        'books_updated': 0,
        'books_synced': 0,
        'files_deleted_local': 0,
        'errors': [],
    }
    to_upload = [{'uuid': 'u1', 'needs_metadata': False, 'needs_cover': True, 'needs_files': False}]

    had_errors = worker._v5_push_missing_items(
        to_upload=to_upload,
        missing_id_map={'u1': 1},
        uuids_deleted_locally=set(),
        sync_library_path='/tmp/unused',
        sm=Mock(),
        summary=summary,
        updates_by_uuid={},
    )

    assert had_errors is False
    worker.client.upload_cover.assert_called_once()
    assert summary['books_updated'] == 1
    assert summary['books_synced'] == 1


def test_v5_push_missing_items_single_file_mismatch_deletes_local_formats_when_server_newer():
    worker = _make_worker()
    worker.gui = object()
    worker.client = Mock()
    worker.db.get_metadata = Mock(
        return_value=SimpleNamespace(last_modified=datetime(1970, 1, 1, 0, 1, 40, tzinfo=timezone.utc))
    )  # 100
    worker.db.formats = Mock(return_value='EPUB')
    worker.db.remove_format = Mock()

    summary = {
        'books_created': 0,
        'books_updated': 0,
        'books_synced': 0,
        'files_deleted_local': 0,
        'errors': [],
    }
    to_upload = [{'uuid': 'u1', 'needs_metadata': False, 'needs_cover': False, 'needs_files': True}]
    updates_by_uuid = {'u1': {'last_modified': 200}}  # server newer

    had_errors = worker._v5_push_missing_items(
        to_upload=to_upload,
        missing_id_map={'u1': 1},
        uuids_deleted_locally=set(),
        sync_library_path='/tmp/unused',
        sm=Mock(),
        summary=summary,
        updates_by_uuid=updates_by_uuid,
    )

    assert had_errors is False
    assert worker._pending_local_format_deletes.get(1) == {'EPUB'}
    assert summary['files_deleted_local'] == 1
    assert summary['books_updated'] == 1
    assert summary['books_synced'] == 1


def test_collect_local_changes_progressive_persists_all_hash_caches(tmp_path, monkeypatch):
    worker = _make_worker(ids=[1])
    worker.status_tag_mappings = {}
    worker.progress_percent_column = None
    worker.favorite_column = None
    worker._server_missing_book_ids = set()
    worker._target_debug_uuid = None
    worker._check_cancelled = lambda: None
    worker._get_remote_uuids = lambda: set()
    worker._record_book_mapping = lambda *args, **kwargs: None

    class DbWithFiles:
        def __init__(self, base_path):
            self.data = Mock()
            self.data.has_id = lambda _book_id: True
            self.library_path = None
            self._base = base_path
            self._epub = os.path.join(base_path, 'book.epub')
            self._pdf = os.path.join(base_path, 'book.pdf')
            self._cover = os.path.join(base_path, 'cover.jpg')
            with open(self._epub, 'wb') as f:
                f.write(b'epub-content')
            with open(self._pdf, 'wb') as f:
                f.write(b'pdf-content')
            with open(self._cover, 'wb') as f:
                f.write(b'cover-content')

        def all_ids(self):
            return [1]

        def get_metadata(self, book_id, index_is_id=True):
            return SimpleNamespace(
                title='Hash Cache Book',
                uuid='u-hash-1',
                last_modified=datetime(2026, 2, 22, 18, 30, tzinfo=timezone.utc),
            )

        def formats(self, book_id, index_is_id=True):
            return 'EPUB,PDF'

        def format_abspath(self, book_id, fmt):
            return self._epub if fmt == 'EPUB' else self._pdf if fmt == 'PDF' else None

        def format(self, book_id, fmt, as_path=False, index_is_id=True):
            if as_path:
                return None
            if fmt == 'EPUB':
                return b'epub-content'
            if fmt == 'PDF':
                return b'pdf-content'
            return None

        def cover(self, book_id, index_is_id=True):
            return self._cover

    worker.db = DbWithFiles(str(tmp_path))

    monkeypatch.setattr(worker, '_ensure_book_uuid', lambda book_id, metadata: metadata.uuid)
    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', lambda *args, **kwargs: {'notes': {}})
    monkeypatch.setattr(sync_worker.sync_mapper, 'calibre_to_json_item', lambda *args, **kwargs: {
        'uuid': 'u-hash-1',
        'title': 'Hash Cache Book',
        'cover': {},
        'files': [],
    })

    captured = {}

    def fake_update_book_cache(*args, **kwargs):
        captured['kwargs'] = kwargs

    monkeypatch.setattr(sync_worker.cfg, 'update_book_cache', fake_update_book_cache)

    batches = list(worker._collect_local_changes_progressive(full_sync=True, batch_size=10))
    assert len(batches) == 1
    assert len(batches[0][0]) == 1

    kwargs = captured['kwargs']
    assert kwargs.get('metadata_hash_cache')
    assert kwargs.get('cover_hash_cache')
    assert kwargs.get('files_hash_cache')
    assert ',' in kwargs['files_hash_cache']


def test_apply_update_does_not_download_cover_when_hash_matches(monkeypatch):
    worker = _make_worker()
    worker.progress_percent_column = None
    worker.favorite_column = None
    worker.status_tag_mappings = {}
    worker._cache_book_uuid = lambda *args, **kwargs: None
    worker._write_custom_columns = lambda *args, **kwargs: None
    worker._download_cover = Mock()
    worker._resolve_local_book_id = lambda item: 10

    metadata = SimpleNamespace(
        title='Book',
        sort='Book',
        author_sort='Author',
        series=None,
        publisher=None,
        comments=None,
        authors=[],
        languages=[],
        tags=[],
        series_index=1.0,
        rating=0.0,
        last_modified=datetime(2026, 2, 22, 18, 0, tzinfo=timezone.utc),
    )

    class CoverDb:
        def __init__(self, md):
            self.data = Mock()
            self.data.has_id = lambda _book_id: True
            self._md = md

        def get_metadata(self, book_id, index_is_id=True):
            return self._md

        def cover(self, book_id, index_is_id=True):
            return '/tmp/cover.jpg'

        def set_metadata(self, book_id, md):
            return None

    worker.db = CoverDb(metadata)

    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', lambda *args, **kwargs: {'notes': {}})
    monkeypatch.setattr(sync_worker.cfg, 'update_book_cache', lambda *args, **kwargs: None)
    monkeypatch.setattr(sync_worker.sync_mapper, 'json_item_to_calibre', lambda *args, **kwargs: {
        'title': 'Book',
        'title_sort': 'Book',
        'author_sort': 'Author',
        'authors': [],
        'languages': [],
        'tags': [],
        'series_index': 1.0,
        'rating': 0.0,
        'last_modified': '2026-02-22T18:00:00Z',
    })
    monkeypatch.setattr(sync_worker.sync_mapper, 'calculate_cover_hash', lambda *_: 'sha256:same')
    monkeypatch.setattr(sync_worker.sync_mapper, 'calibre_to_json_item', lambda *args, **kwargs: {
        'uuid': 'u-10',
        'title': 'Book',
        'cover': {},
        'files': [],
    })

    item = {
        'uuid': 'u-10',
        'title': 'Book',
        'title_sort': 'Book',
        'author_sort': 'Author',
        'authors': [],
        'languages': [],
        'tags': [],
        'series': None,
        'publisher': None,
        'comments': None,
        'series_index': 1.0,
        'rating': 0.0,
        'last_modified': int(datetime(2026, 2, 22, 18, 0, tzinfo=timezone.utc).timestamp()),
        'cover': {
            'has_cover': True,
            'cover_hash': 'sha256:same',
            'cover_hash_optimized': 'sha256:same',
        },
    }

    worker._apply_update(item, skip_cover=False)
    worker._download_cover.assert_not_called()


def test_should_download_file_uses_calibre_bytes_when_path_unavailable(monkeypatch):
    worker = _make_worker()
    worker.library_id = 'lib-123'

    class BytesDb:
        def __init__(self):
            self.data = Mock()
            self.data.has_id = lambda _book_id: True

        def format(self, book_id, fmt, as_path=False, index_is_id=True):
            if as_path:
                return None
            return b'pdf-bytes-content'

        def format_abspath(self, book_id, fmt):
            return None

    worker.db = BytesDb()

    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', lambda *args, **kwargs: {'notes': {}})
    expected = sync_worker.sync_mapper.calculate_file_hash(b'pdf-bytes-content')
    should_download, reason = worker._should_download_file(1, 'PDF', expected)

    assert should_download is False
    assert reason == 'local_hash_match'


def test_v5_apply_updates_batch_skips_download_for_server_missing_files(monkeypatch):
    worker = _make_worker()
    worker._apply_update = Mock(return_value=(42, True))
    worker._should_download_file = Mock(return_value=(True, 'hash_mismatch'))

    summary = {'books_updated': 0, 'books_skipped': 0, 'books_synced': 0, 'errors': []}
    updates = [{
        'uuid': 'u-1',
        'formats': [
            {'format': 'PDF', 'file_hash': 'sha256:a', 'needs_file_upload': True},
            {'format': 'EPUB', 'file_hash': 'sha256:b', 'file_missing': True},
            {'format': 'MOBI', 'file_hash': 'sha256:c'},
        ],
    }]

    files_to_download, had_errors = worker._v5_apply_updates_batch(updates, 1, summary)

    assert had_errors is False
    assert summary['books_updated'] == 1
    assert summary['books_synced'] == 1
    worker._should_download_file.assert_called_once_with(42, 'MOBI', 'sha256:c', item=updates[0])
    assert files_to_download == [(42, 'u-1', 'MOBI', 'sha256:c', 'hash_mismatch')]


def test_v5_push_missing_items_skips_file_upload_when_local_payload_unavailable():
    worker = _make_worker()
    worker.gui = object()
    worker.status_tag_mappings = {}
    worker.client = Mock()
    worker.client.post_sync = Mock(return_value={
        'results': [{
            'status': 'applied',
            'server_item': {
                'files': [{
                    'format': 'PDF',
                    'upload_url': 'https://example.test/upload',
                    'file_hash': 'sha256:x',
                }]
            },
            'file_uploads': [],
        }]
    })
    worker._build_files_array_for_book = Mock(return_value=([], {'status': 'unavailable', 'declared_formats': []}))
    worker._compute_metadata_signature = Mock(return_value=None)
    worker._upload_file = Mock(return_value={'success': True})

    worker.db.data.has_id = lambda _bid: True
    worker.db.get_metadata = Mock(return_value=SimpleNamespace(
        title='Book',
        has_cover=False,
        last_modified=datetime(2026, 2, 22, 20, 0, tzinfo=timezone.utc),
    ))
    worker.db.formats = Mock(return_value=[])

    sm = Mock()
    sm.calibre_to_json_item = Mock(return_value={'uuid': 'u-1', 'title': 'Book'})

    summary = {
        'books_created': 0,
        'books_updated': 0,
        'books_synced': 0,
        'files_deleted_local': 0,
        'files_unavailable_runtime': 0,
        'files_missing_real': 0,
        'files_read_errors': 0,
        'errors': [],
    }

    had_errors = worker._v5_push_missing_items(
        to_upload=[{'uuid': 'u-1', 'needs_metadata': False, 'needs_cover': False, 'needs_files': True}],
        missing_id_map={'u-1': 1},
        uuids_deleted_locally=set(),
        sync_library_path='/tmp/unused',
        sm=sm,
        updates_by_uuid={},
        summary=summary,
    )

    assert had_errors is False
    worker.client.post_sync.assert_called_once()
    worker._upload_file.assert_not_called()
    assert not any(err.get('phase') == 'push_missing_files_build' for err in summary['errors'])
    assert not any(err.get('phase') == 'push_missing_file_upload' for err in summary['errors'])
    assert summary.get('books_skipped_unavailable_files')
    assert summary['books_synced'] == 1


def test_v5_push_missing_items_forwards_no_cache_to_post_sync():
    worker = _make_worker()
    worker.gui = object()
    worker.status_tag_mappings = {}
    worker.client = Mock()
    worker.client.post_sync = Mock(return_value={
        'results': [{
            'status': 'applied',
            'server_item': {'files': []},
            'file_uploads': [],
        }]
    })
    worker._build_files_array_for_book = Mock(return_value=([{
        'format': 'PDF',
        'file_hash': 'a' * 64,
        'size': 123,
    }], {'status': 'ok', 'declared_formats': ['PDF']}))
    worker._compute_metadata_signature = Mock(return_value=None)

    worker.db.data.has_id = lambda _bid: True
    worker.db.get_metadata = Mock(return_value=SimpleNamespace(
        title='Book',
        has_cover=False,
        last_modified=datetime(2026, 2, 22, 20, 0, tzinfo=timezone.utc),
    ))
    worker.db.formats = Mock(return_value=['PDF'])

    sm = Mock()
    sm.calibre_to_json_item = Mock(return_value={'uuid': 'u-1', 'title': 'Book'})

    summary = {
        'books_created': 0,
        'books_updated': 0,
        'books_synced': 0,
        'files_deleted_local': 0,
        'files_unavailable_runtime': 0,
        'files_missing_real': 0,
        'files_read_errors': 0,
        'errors': [],
    }

    had_errors = worker._v5_push_missing_items(
        to_upload=[{'uuid': 'u-1', 'needs_metadata': True, 'needs_cover': False, 'needs_files': False}],
        missing_id_map={'u-1': 1},
        uuids_deleted_locally=set(),
        sync_library_path='/tmp/unused',
        sm=sm,
        updates_by_uuid={},
        summary=summary,
        no_cache=True,
    )

    assert had_errors is False
    worker.client.post_sync.assert_called_once()
    assert worker.client.post_sync.call_args.kwargs.get('no_cache') is True


def test_v5_push_missing_items_batches_metadata_only_upserts(monkeypatch):
    worker = _make_worker()
    worker.gui = object()
    worker.status_tag_mappings = {}
    monkeypatch.setenv('CALIMOB_V5_MISSING_METADATA_BATCH_SIZE', '500')

    captured_changes = []

    def _fake_post_sync(**kwargs):
        changes = kwargs.get('changes') or []
        captured_changes.append(changes)
        return {
            'results': [
                {'status': 'applied', 'client_change_id': ch.get('client_change_id')}
                for ch in changes
            ]
        }

    worker.client = Mock()
    worker.client.post_sync = Mock(side_effect=_fake_post_sync)

    worker.db.data.has_id = lambda _bid: True
    worker.db.get_metadata = Mock(return_value=SimpleNamespace(
        title='Book',
        has_cover=False,
        last_modified=datetime(2026, 2, 22, 20, 0, tzinfo=timezone.utc),
    ))
    worker.db.formats = Mock(return_value=[])
    worker._build_files_array_for_book = Mock(return_value=([], {'status': 'ok', 'declared_formats': []}))
    worker._compute_metadata_signature = Mock(return_value='meta-hash')

    sm = Mock()
    sm.calibre_to_json_item = Mock(side_effect=[
        {'uuid': 'u-1', 'title': 'Book 1'},
        {'uuid': 'u-2', 'title': 'Book 2'},
    ])

    summary = {
        'books_created': 0,
        'books_updated': 0,
        'books_synced': 0,
        'files_deleted_local': 0,
        'files_unavailable_runtime': 0,
        'files_missing_real': 0,
        'files_read_errors': 0,
        'errors': [],
    }

    had_errors = worker._v5_push_missing_items(
        to_upload=[
            {'uuid': 'u-1', 'needs_metadata': True, 'needs_cover': False, 'needs_files': False},
            {'uuid': 'u-2', 'needs_metadata': True, 'needs_cover': False, 'needs_files': False},
        ],
        missing_id_map={'u-1': 1, 'u-2': 2},
        uuids_deleted_locally=set(),
        sync_library_path='/tmp/unused',
        sm=sm,
        updates_by_uuid={},
        summary=summary,
    )

    assert had_errors is False
    worker.client.post_sync.assert_called_once()
    assert len(captured_changes) == 1
    assert len(captured_changes[0]) == 2
    assert summary['books_synced'] == 2


def test_v5_push_missing_items_batches_upserts_with_file_upload_targets(monkeypatch):
    worker = _make_worker()
    worker.status_tag_mappings = {}
    worker.library_id = 'lib-123'
    worker.calimob_library_id = 9
    monkeypatch.setenv('CALIMOB_V5_MISSING_METADATA_BATCH_SIZE', '500')

    class DbForUpload:
        def __init__(self):
            self.data = Mock()
            self.data.has_id = lambda _: True
            self.remove_format = Mock()

        def get_metadata(self, book_id, index_is_id=True):
            return SimpleNamespace(
                title='Book %s' % book_id,
                has_cover=False,
                last_modified=datetime(2026, 2, 22, 18, 0, tzinfo=timezone.utc),
            )

        def formats(self, book_id, index_is_id=True):
            return 'PDF'

    worker.db = DbForUpload()
    worker._build_files_array_for_book = lambda _book_id: [{'format': 'PDF', 'file_hash': 'abc'}]

    uploaded = []
    worker._upload_file = lambda file_info, _cache: uploaded.append(file_info) or {'success': True}

    def _fake_post_sync(**kwargs):
        changes = kwargs.get('changes') or []
        out = []
        for ch in changes:
            cid = ch.get('client_change_id')
            out.append({
                'client_change_id': cid,
                'status': 'applied',
                'file_uploads': [{'format': 'PDF', 'upload_url': 'https://example.test/upload/%s' % cid}],
                'server_item': {'uuid': ch.get('item', {}).get('uuid'), 'files': []},
            })
        return {'results': out}

    worker.client = SimpleNamespace(post_sync=_fake_post_sync)

    def _json_item_for_book(book_id, *_args, **_kwargs):
        uuid_map = {1: 'u1', 2: 'u2'}
        return {'uuid': uuid_map.get(book_id), 'title': 'Book %s' % book_id}

    sm = SimpleNamespace(
        calibre_to_json_item=_json_item_for_book,
        calculate_cover_hash=lambda *_: None,
    )

    summary = {'errors': [], 'books_created': 0, 'books_synced': 0}
    err = worker._v5_push_missing_items(
        to_upload=[
            {'uuid': 'u1', 'needs_files': True, 'needs_metadata': False, 'needs_cover': False},
            {'uuid': 'u2', 'needs_files': True, 'needs_metadata': False, 'needs_cover': False},
        ],
        missing_id_map={'u1': 1, 'u2': 2},
        uuids_deleted_locally=set(),
        sync_library_path='/tmp',
        sm=sm,
        summary=summary,
        updates_by_uuid={
            'u1': {'last_modified': int(datetime(2026, 2, 20, tzinfo=timezone.utc).timestamp())},
            'u2': {'last_modified': int(datetime(2026, 2, 20, tzinfo=timezone.utc).timestamp())},
        },
    )

    assert err is False
    assert len(uploaded) == 2
    assert summary.get('files_uploaded', 0) == 2
    assert summary.get('books_synced', 0) == 2


def test_should_download_cover_does_not_force_download_on_local_check_error(monkeypatch):
    worker = _make_worker()
    worker.library_id = 'lib-123'
    worker.db = SimpleNamespace(cover=Mock(return_value=None))

    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', lambda *args, **kwargs: (_ for _ in ()).throw(RuntimeError('mapping read failed')))

    should_download, reason = worker._should_download_cover(
        1,
        {'cover': {'has_cover': True, 'cover_hash': 'sha256:abc'}},
    )

    assert should_download is False
    assert reason == 'error_local_cover_check'


def test_should_download_file_defers_when_local_bytes_unavailable(monkeypatch):
    worker = _make_worker()
    worker.library_id = 'lib-123'

    class UnavailableDb:
        def __init__(self):
            self.data = Mock()
            self.data.has_id = lambda _book_id: True

        def format(self, *args, **kwargs):
            return None

        def format_abspath(self, *args, **kwargs):
            return None

        def get_metadata(self, *args, **kwargs):
            return SimpleNamespace(last_modified=datetime(2026, 2, 27, 10, 0, tzinfo=timezone.utc))

    worker.db = UnavailableDb()
    monkeypatch.setattr(sync_worker.time, 'sleep', lambda *_args, **_kwargs: None)
    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', lambda *args, **kwargs: {'notes': {}})

    should_download, reason = worker._should_download_file(
        1,
        'PDF',
        'sha256:abc',
        item={'last_modified': int(datetime(2026, 2, 27, 11, 0, tzinfo=timezone.utc).timestamp())},
    )

    assert should_download is False
    assert reason == 'local_bytes_unavailable_defer'


def test_should_download_cover_uses_effective_timestamp_arbitration(monkeypatch):
    worker = _make_worker()
    worker.library_id = 'lib-123'

    class CoverDb:
        def __init__(self):
            self.data = Mock()
            self.data.has_id = lambda _book_id: True

        def cover(self, *args, **kwargs):
            return b'local-cover-bytes'

    worker.db = CoverDb()

    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', lambda *args, **kwargs: {
        'notes': {
            'book_cache': {
                'last_modified': '100',
                'last_modified_server': '250',
            },
            'cover': {},
        }
    })

    should_download, reason = worker._should_download_cover(
        1,
        {
            'last_modified': 200,
            'cover': {
                'has_cover': True,
                'cover_hash': 'sha256:server',
            },
        },
        bulk_entry={'last_modified': 100},
    )

    assert should_download is False
    assert reason == 'local_effective_newer_or_equal'


def test_should_download_file_uses_effective_timestamp_arbitration_when_available(monkeypatch):
    worker = _make_worker()
    worker.library_id = 'lib-123'

    class FileDb:
        def __init__(self):
            self.data = Mock()
            self.data.has_id = lambda _book_id: True

        def format(self, *args, **kwargs):
            return b'local-file-content'

        def format_abspath(self, *args, **kwargs):
            return '/tmp/local.epub'

    worker.db = FileDb()
    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', lambda *args, **kwargs: {
        'notes': {
            'book_cache': {
                'last_modified': '100',
                'last_modified_server': '250',
            }
        }
    })

    should_download, reason = worker._should_download_file(
        1,
        'EPUB',
        'sha256:server-hash',
        item={'last_modified': 200},
        bulk_entry={'last_modified': 100, 'formats': {'EPUB'}},
    )

    assert should_download is False
    assert reason == 'local_effective_newer_or_equal'


def test_should_download_file_downloads_when_server_effective_is_newer(monkeypatch):
    worker = _make_worker()
    worker.library_id = 'lib-123'

    class FileDb:
        def __init__(self):
            self.data = Mock()
            self.data.has_id = lambda _book_id: True

        def format(self, *args, **kwargs):
            return b'local-file-content'

        def format_abspath(self, *args, **kwargs):
            return '/tmp/local.epub'

    worker.db = FileDb()
    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', lambda *args, **kwargs: {
        'notes': {
            'book_cache': {
                'last_modified': '100',
                'last_modified_server': '250',
                'files': {},
            }
        }
    })
    monkeypatch.setattr(sync_worker.cfg, 'update_book_cache', lambda *args, **kwargs: None)

    should_download, reason = worker._should_download_file(
        1,
        'EPUB',
        'sha256:server-hash',
        item={'last_modified': 300},
        bulk_entry={'last_modified': 100, 'formats': {'EPUB'}},
    )

    assert should_download is True
    assert reason == 'hash_mismatch'


def test_should_download_cover_downloads_when_server_effective_is_newer(monkeypatch):
    worker = _make_worker()
    worker.library_id = 'lib-123'

    class CoverDb:
        def __init__(self):
            self.data = Mock()
            self.data.has_id = lambda _book_id: True

        def cover(self, *args, **kwargs):
            return b'local-cover-bytes'

    worker.db = CoverDb()
    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', lambda *args, **kwargs: {
        'notes': {
            'book_cache': {
                'last_modified': '100',
                'last_modified_server': '250',
            },
            'cover': {},
        }
    })
    monkeypatch.setattr(sync_worker.cfg, 'update_book_cache', lambda *args, **kwargs: None)

    should_download, reason = worker._should_download_cover(
        1,
        {
            'last_modified': 300,
            'cover': {
                'has_cover': True,
                'cover_hash': 'sha256:server',
            },
        },
        bulk_entry={'last_modified': 100},
    )

    assert should_download is True
    assert reason == 'hash_mismatch_or_missing'


def test_apply_update_skips_cover_download_when_cover_unavailable(monkeypatch):
    worker = _make_worker()
    worker.progress_percent_column = None
    worker.favorite_column = None
    worker.status_tag_mappings = {}
    worker._cache_book_uuid = lambda *args, **kwargs: None
    worker._write_custom_columns = lambda *args, **kwargs: None
    worker._download_cover = Mock()
    worker._resolve_local_book_id = lambda item: 10
    worker._should_download_cover = Mock(return_value=(False, 'error_local_cover_check'))

    metadata = SimpleNamespace(
        title='Book',
        sort='Book',
        author_sort='Author',
        series=None,
        publisher=None,
        comments=None,
        authors=[],
        languages=[],
        tags=[],
        series_index=1.0,
        rating=0.0,
        last_modified=datetime(2026, 2, 22, 18, 0, tzinfo=timezone.utc),
    )

    class CoverDb:
        def __init__(self, md):
            self.data = Mock()
            self.data.has_id = lambda _book_id: True
            self._md = md

        def get_metadata(self, book_id, index_is_id=True):
            return self._md

        def set_metadata(self, book_id, md):
            return None

    worker.db = CoverDb(metadata)

    monkeypatch.setattr(sync_worker.cfg, 'get_book_mapping_entry', lambda *args, **kwargs: {'notes': {}})
    monkeypatch.setattr(sync_worker.cfg, 'update_book_cache', lambda *args, **kwargs: None)
    monkeypatch.setattr(sync_worker.sync_mapper, 'json_item_to_calibre', lambda *args, **kwargs: {
        'title': 'Book',
        'title_sort': 'Book',
        'author_sort': 'Author',
        'authors': [],
        'languages': [],
        'tags': [],
        'series_index': 1.0,
        'rating': 0.0,
        'last_modified': '2026-02-22T18:00:00Z',
    })
    monkeypatch.setattr(sync_worker.sync_mapper, 'calibre_to_json_item', lambda *args, **kwargs: {
        'uuid': 'u-10',
        'title': 'Book',
        'cover': {},
        'files': [],
    })

    item = {
        'uuid': 'u-10',
        'title': 'Book',
        'title_sort': 'Book',
        'author_sort': 'Author',
        'authors': [],
        'languages': [],
        'tags': [],
        'series': None,
        'publisher': None,
        'comments': None,
        'series_index': 1.0,
        'rating': 0.0,
        'metadata_hash': 'sha256:server-hash',
        'last_modified': int(datetime(2026, 2, 22, 18, 0, tzinfo=timezone.utc).timestamp()),
        'cover': {
            'has_cover': True,
            'cover_hash': 'sha256:server-cover',
        },
    }

    worker._apply_update(item, skip_cover=False)
    worker._should_download_cover.assert_called_once()
    worker._download_cover.assert_not_called()


def test_build_files_array_for_book_uses_lowercase_format_bytes_fallback():
    worker = _make_worker()
    worker.gui = object()

    class LowercaseFormatDb:
        def formats(self, book_id, index_is_id=True):
            return ['PDF']

        def format(self, book_id, fmt, as_path=False, index_is_id=True):
            if fmt == 'PDF':
                return None
            if fmt == 'pdf':
                return b'pdf-content'
            return None

        def format_abspath(self, book_id, fmt):
            return None

    worker.db = LowercaseFormatDb()
    files = worker._build_files_array_for_book(10)

    assert len(files) == 1
    assert files[0]['format'] == 'PDF'
    assert files[0]['file_hash']


def test_build_files_array_for_book_returns_empty_when_bytes_unavailable():
    worker = _make_worker()
    worker.gui = object()

    class NoBytesDb:
        def formats(self, book_id, index_is_id=True):
            return ['PDF']

        def format(self, book_id, fmt, as_path=False, index_is_id=True):
            return None

        def format_abspath(self, book_id, fmt):
            return None

    worker.db = NoBytesDb()
    files = worker._build_files_array_for_book(11)

    assert files == []


def test_build_files_array_for_book_reports_unavailable_when_formats_empty():
    worker = _make_worker()
    worker.gui = object()

    class EmptyFormatsDb:
        def formats(self, book_id, index_is_id=True):
            return []

    worker.db = EmptyFormatsDb()
    files, diag = worker._build_files_array_for_book(12, include_diag=True)

    assert files == []
    assert diag['status'] == 'unavailable'
    assert diag['declared_formats'] == []


def test_build_files_array_for_book_uses_backend_read_format_byte_only():
    worker = _make_worker()
    worker.gui = object()

    class Backend:
        def read_format(self, book_id, fmt):
            if fmt == 'EPUB':
                return b'epub-bytes'
            return None

    class BackendDb:
        backend = Backend()

        def formats(self, book_id, index_is_id=True):
            return ['EPUB']

        def format(self, book_id, fmt, as_path=False, index_is_id=True):
            return None

    worker.db = BackendDb()
    files, diag = worker._build_files_array_for_book(13, include_diag=True)

    assert len(files) == 1
    assert files[0]['format'] == 'EPUB'
    assert diag['status'] == 'ok'


def test_read_cover_bytes_byte_only_prefers_index_is_id():
    worker = _make_worker()
    worker.gui = object()

    class CoverDb:
        def cover(self, book_id, index_is_id=True):
            return b'cover-bytes'

    worker.db = CoverDb()
    data, method, status = worker._read_cover_bytes_byte_only(1)
    assert data == b'cover-bytes'
    assert method == 'db.cover.index_is_id'
    assert status is None


def test_read_cover_bytes_byte_only_reports_unavailable_for_non_bytes():
    worker = _make_worker()
    worker.gui = object()

    class CoverDb:
        def cover(self, book_id, index_is_id=True):
            return '/tmp/cover.jpg'

    worker.db = CoverDb()
    data, method, status = worker._read_cover_bytes_byte_only(1)
    assert data is None
    assert method == 'db.cover.index_is_id'
    assert status == 'unavailable'


def test_sync_v5_resume_incompatible_signature_starts_from_zero(monkeypatch):
    worker = _make_worker()
    worker.gui = None
    worker.calimob_library_id = 8
    worker.library_id = 'lib-123'
    worker.status_tag_mappings = {}

    calls = []
    class FakeClient:
        def sync_v5(self, **kwargs):
            calls.append(kwargs)
            return {
                'updates_for_client': [],
                'missing_from_server': [],
                'deleted_on_server': [],
                'cursor': '100:1',
                'has_more': False,
                'client_cursor_next': 2,
                'client_done': True,
                'skipped_hash': 0,
            }
    worker.client = FakeClient()

    monkeypatch.setenv('CALIMOB_V5_CLIENT_BATCH_SIZE', '2')
    monkeypatch.setattr(worker, 'get_pull_cursor', lambda: None)
    monkeypatch.setattr(worker, 'save_pull_cursor', lambda c: None)
    monkeypatch.setattr(worker, 'save_cursor', lambda c: None)
    monkeypatch.setattr(worker, '_v5_clear_resume_state', lambda: None)
    monkeypatch.setattr(worker, '_v5_save_resume_state', lambda state: None)
    monkeypatch.setattr(worker, '_v5_get_resume_state', lambda: {
        'resume_sig': 'different-signature',
        'client_cursor': 2,
        'client_total': 3,
        'server_cursor': '100:1',
    })
    monkeypatch.setattr(
        worker,
        '_v5_collect_client_books_candidates',
        lambda **kwargs: (
            ['d1'],
            {'u1': 1, 'u2': 2, 'u3': 3},
            [
                {'id': 1, 'uuid': 'u1', 'last_modified': 10},
                {'id': 2, 'uuid': 'u2', 'last_modified': 20},
                {'id': 3, 'uuid': 'u3', 'last_modified': 30},
            ],
        ),
    )
    monkeypatch.setattr(
        worker,
        '_v5_build_client_books_chunk',
        lambda books_chunk, **kwargs: {
            b['uuid']: {'m': 'h-%s' % b['uuid'], 'c': None, 'f': None, 'lm': b['last_modified']}
            for b in books_chunk
        },
    )
    monkeypatch.setattr(worker, '_v5_apply_deleted_on_server', lambda **kwargs: (set(), False))
    monkeypatch.setattr(worker, '_v5_resolve_missing_id_map', lambda **kwargs: ({}, False))
    monkeypatch.setattr(worker, '_v5_push_missing_items', lambda **kwargs: False)
    monkeypatch.setattr(worker, '_v5_apply_updates_batch', lambda **kwargs: ([], False))
    monkeypatch.setattr(worker, '_v5_download_files_batch', lambda **kwargs: None)

    worker.sync_v5()

    assert calls[0]['client_cursor'] == 0
    assert calls[0]['client_books']['d'] == ['d1']


def test_sync_v5_resume_sends_deleted_only_first_batch_even_after_restore(monkeypatch):
    worker = _make_worker()
    worker.gui = None
    worker.calimob_library_id = 8
    worker.library_id = 'lib-123'
    worker.status_tag_mappings = {}

    calls = []
    class FakeClient:
        def sync_v5(self, **kwargs):
            calls.append(kwargs)
            return {
                'updates_for_client': [],
                'missing_from_server': [],
                'deleted_on_server': [],
                'cursor': '100:1',
                'has_more': False,
                'client_cursor_next': 3,
                'client_done': True,
                'skipped_hash': 0,
            }
    worker.client = FakeClient()

    monkeypatch.setenv('CALIMOB_V5_CLIENT_BATCH_SIZE', '2')
    monkeypatch.setattr(worker, 'get_pull_cursor', lambda: None)
    monkeypatch.setattr(worker, 'save_pull_cursor', lambda c: None)
    monkeypatch.setattr(worker, 'save_cursor', lambda c: None)
    monkeypatch.setattr(worker, '_v5_clear_resume_state', lambda: None)
    monkeypatch.setattr(worker, '_v5_save_resume_state', lambda state: None)
    monkeypatch.setattr(
        worker,
        '_v5_collect_client_books_candidates',
        lambda **kwargs: (
            ['d1'],
            {'u1': 1, 'u2': 2, 'u3': 3},
            [
                {'id': 1, 'uuid': 'u1', 'last_modified': 10},
                {'id': 2, 'uuid': 'u2', 'last_modified': 20},
                {'id': 3, 'uuid': 'u3', 'last_modified': 30},
            ],
        ),
    )
    monkeypatch.setattr(
        worker,
        '_v5_build_client_books_chunk',
        lambda books_chunk, **kwargs: {
            b['uuid']: {'m': 'h-%s' % b['uuid'], 'c': None, 'f': None, 'lm': b['last_modified']}
            for b in books_chunk
        },
    )
    resume_sig = worker._v5_build_resume_signature(
        [('u1', {'id': 1}, 10), ('u2', {'id': 2}, 20), ('u3', {'id': 3}, 30)],
        None,
        False
    )
    monkeypatch.setattr(worker, '_v5_get_resume_state', lambda: {
        'resume_sig': resume_sig,
        'client_cursor': 2,
        'client_total': 3,
        'server_cursor': '100:1',
    })
    monkeypatch.setattr(worker, '_v5_apply_deleted_on_server', lambda **kwargs: (set(), False))
    monkeypatch.setattr(worker, '_v5_resolve_missing_id_map', lambda **kwargs: ({}, False))
    monkeypatch.setattr(worker, '_v5_push_missing_items', lambda **kwargs: False)
    monkeypatch.setattr(worker, '_v5_apply_updates_batch', lambda **kwargs: ([], False))
    monkeypatch.setattr(worker, '_v5_download_files_batch', lambda **kwargs: None)

    worker.sync_v5()

    assert calls[0]['client_cursor'] == 2
    assert calls[0]['client_books']['d'] == []


def test_sync_v5_resume_state_saved_each_successful_batch_and_cleared_on_success(monkeypatch):
    worker = _make_worker()
    worker.gui = None
    worker.calimob_library_id = 8
    worker.library_id = 'lib-123'
    worker.status_tag_mappings = {}
    worker.client = Mock()
    worker.client.sync_v5 = Mock(side_effect=[
        {
            'updates_for_client': [],
            'missing_from_server': [],
            'deleted_on_server': [],
            'cursor': '100:1',
            'has_more': False,
            'client_cursor_next': 2,
            'client_done': False,
            'skipped_hash': 0,
        },
        {
            'updates_for_client': [],
            'missing_from_server': [],
            'deleted_on_server': [],
            'cursor': '100:1',
            'has_more': False,
            'client_cursor_next': 3,
            'client_done': True,
            'skipped_hash': 0,
        },
    ])

    monkeypatch.setenv('CALIMOB_V5_CLIENT_BATCH_SIZE', '2')
    monkeypatch.setattr(worker, 'get_pull_cursor', lambda: None)
    monkeypatch.setattr(worker, 'save_pull_cursor', lambda c: None)
    monkeypatch.setattr(worker, 'save_cursor', lambda c: None)
    monkeypatch.setattr(worker, '_v5_get_resume_state', lambda: None)
    monkeypatch.setattr(
        worker,
        '_v5_collect_client_books_candidates',
        lambda **kwargs: (
            ['d1'],
            {'u1': 1, 'u2': 2, 'u3': 3},
            [
                {'id': 1, 'uuid': 'u1', 'last_modified': 10},
                {'id': 2, 'uuid': 'u2', 'last_modified': 20},
                {'id': 3, 'uuid': 'u3', 'last_modified': 30},
            ],
        ),
    )
    monkeypatch.setattr(
        worker,
        '_v5_build_client_books_chunk',
        lambda books_chunk, **kwargs: {
            b['uuid']: {'m': 'h-%s' % b['uuid'], 'c': None, 'f': None, 'lm': b['last_modified']}
            for b in books_chunk
        },
    )
    monkeypatch.setattr(worker, '_v5_apply_deleted_on_server', lambda **kwargs: (set(), False))
    monkeypatch.setattr(worker, '_v5_resolve_missing_id_map', lambda **kwargs: ({}, False))
    monkeypatch.setattr(worker, '_v5_push_missing_items', lambda **kwargs: False)
    monkeypatch.setattr(worker, '_v5_apply_updates_batch', lambda **kwargs: ([], False))
    monkeypatch.setattr(worker, '_v5_download_files_batch', lambda **kwargs: None)

    saved_resume = []
    cleared = {'count': 0}
    monkeypatch.setattr(worker, '_v5_save_resume_state', lambda state: saved_resume.append(dict(state)))
    monkeypatch.setattr(worker, '_v5_clear_resume_state', lambda: cleared.__setitem__('count', cleared['count'] + 1))

    worker.sync_v5()

    assert len(saved_resume) >= 3
    assert cleared['count'] == 1


def test_sync_v5_resume_state_not_cleared_on_fatal_error(monkeypatch):
    worker = _make_worker()
    worker.gui = None
    worker.calimob_library_id = 8
    worker.library_id = 'lib-123'
    worker.status_tag_mappings = {}

    class FailingClient:
        def sync_v5(self, **kwargs):
            raise RuntimeError('boom')
    worker.client = FailingClient()

    monkeypatch.setenv('CALIMOB_V5_CLIENT_BATCH_SIZE', '2')
    monkeypatch.setattr(worker, 'get_pull_cursor', lambda: None)
    monkeypatch.setattr(worker, '_v5_get_resume_state', lambda: None)
    monkeypatch.setattr(
        worker,
        '_v5_collect_client_books_candidates',
        lambda **kwargs: (
            ['d1'],
            {'u1': 1},
            [{'id': 1, 'uuid': 'u1', 'last_modified': 10}],
        ),
    )
    monkeypatch.setattr(
        worker,
        '_v5_build_client_books_chunk',
        lambda books_chunk, **kwargs: {
            b['uuid']: {'m': 'h-%s' % b['uuid'], 'c': None, 'f': None, 'lm': b['last_modified']}
            for b in books_chunk
        },
    )

    saved_resume = []
    cleared = {'count': 0}
    monkeypatch.setattr(worker, '_v5_save_resume_state', lambda state: saved_resume.append(dict(state)))
    monkeypatch.setattr(worker, '_v5_clear_resume_state', lambda: cleared.__setitem__('count', cleared['count'] + 1))

    summary = worker.sync_v5()

    assert saved_resume
    assert cleared['count'] == 0
    assert summary['errors'], "fatal path should record errors"
