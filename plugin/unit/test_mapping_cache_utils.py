from datetime import datetime

from calibre_plugins.sync_calimob import mapping_cache


def test_update_and_get_book_mapping_entry(monkeypatch):
    prefs = {}
    timestamp = datetime(2025, 1, 1)
    monkeypatch.setattr(mapping_cache, '_now_iso', lambda: '2025-01-01T00:00:00Z')
    mapping_cache.update_book_mapping(prefs, 'lib-1', 7, {'uuid': 'abc-123', 'title': 'Test'})
    entry = mapping_cache.get_book_mapping_entry(prefs, 'lib-1', 7)
    assert entry['uuid'] == 'abc-123'
    assert 'created_at' in entry


def test_mark_book_deleted_sets_flags():
    prefs = {}
    mapping_cache.mark_book_deleted(prefs, 'lib-1', 8, deleted_at=datetime(2025, 2, 2))
    entry = mapping_cache.get_book_mapping_entry(prefs, 'lib-1', 8)
    assert entry['is_deleted'] is True
    assert entry['last_sync_result'] == 'deleted'


def test_cache_book_uuid_skips_empty():
    prefs = {}
    mapping_cache.cache_book_uuid(prefs, 'lib', 9, '')
    assert mapping_cache.get_book_mapping_entry(prefs, 'lib', 9) == {}


def test_get_book_uuid_cache_for_library_returns_entries():
    prefs = {}
    mapping_cache.update_book_mapping(prefs, 'lib-2', 11, {'uuid': 'foo'})
    cache = mapping_cache.get_book_uuid_cache_for_library(prefs, 'lib-2')
    assert '11' in cache or 11 in cache
