from __future__ import division, absolute_import, print_function, unicode_literals

import sqlite3

from calibre_plugins.sync_calimob import mapping_table


def _create_library_path(tmp_path):
    library_root = tmp_path / 'library'
    library_root.mkdir()
    metadata_db = library_root / 'metadata.db'
    sqlite3.connect(str(metadata_db)).close()
    return str(library_root)


def test_upsert_entry_creates_row(tmp_path):
    library_path = _create_library_path(tmp_path)
    updates = {
        'uuid': '11111111-2222-3333-4444-555555555555',
        'title': 'Mapped Title',
        'pending_cover_upload': True,
        'last_sync_result': 'collected',
        'version': 'v1',
    }
    mapping_table.upsert_entry(library_path, 'library-uuid', 1, updates)
    entry = mapping_table.fetch_entry(library_path, 'library-uuid', 1)
    assert entry['uuid'] == updates['uuid']
    assert entry['title'] == 'Mapped Title'
    assert entry['pending_cover_upload'] is True
    assert entry['last_sync_result'] == 'collected'


def test_upsert_entry_updates_row(tmp_path):
    library_path = _create_library_path(tmp_path)
    initial = {
        'uuid': '22222222-3333-4444-5555-666666666666',
        'title': 'Original',
    }
    mapping_table.upsert_entry(library_path, 'library-uuid', 5, initial)
    before = mapping_table.fetch_entry(library_path, 'library-uuid', 5)
    assert before['title'] == 'Original'
    mapping_table.upsert_entry(library_path, 'library-uuid', 5, {
        'title': 'Updated',
        'pending_cover_upload': False,
        'last_sync_result': 'applied'
    })
    after = mapping_table.fetch_entry(library_path, 'library-uuid', 5)
    assert after['title'] == 'Updated'
    assert after['pending_cover_upload'] is False
    assert before['created_at'] == after['created_at']
    assert after['last_sync_result'] == 'applied'


def test_fetch_all_entries_returns_dict(tmp_path):
    library_path = _create_library_path(tmp_path)
    mapping_table.upsert_entry(library_path, 'library-uuid', 7, {'uuid': '7', 'title': 'Seven'})
    mapping_table.upsert_entry(library_path, 'library-uuid', 8, {'uuid': '8', 'title': 'Eight'})
    entries = mapping_table.fetch_all(library_path, 'library-uuid')
    assert '7' in entries
    assert '8' in entries
    assert entries['7']['title'] == 'Seven'
    assert mapping_table.get_uuid_for_book(library_path, 'library-uuid', 8) == '8'
