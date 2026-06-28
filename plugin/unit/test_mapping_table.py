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


def test_ensure_table_adds_columns_even_with_legacy(tmp_path):
    """Regression: _ensure_table must ALTER TABLE to add missing columns
    even when legacy columns (title_sort, client_ids) are present.
    Previously `if missing and not legacy` skipped the ALTER, causing
    'no such column: sync.last_modified' on libraries with old schema.
    """
    library_path = _create_library_path(tmp_path)
    db_path = str(tmp_path / 'library' / 'metadata.db')
    conn = sqlite3.connect(db_path)
    conn.execute('''
        CREATE TABLE calimob_books_sync (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            library_uuid TEXT NOT NULL,
            calibre_book_id INTEGER NOT NULL,
            uuid TEXT,
            title TEXT,
            title_sort TEXT,
            cover_hash TEXT,
            client_ids TEXT,
            created_at TEXT,
            modified_at TEXT,
            last_synced_at TEXT,
            version TEXT,
            deleted_at TEXT,
            is_deleted INTEGER DEFAULT 0,
            last_sync_result TEXT,
            pending_cover_upload INTEGER DEFAULT 0,
            conflict_status TEXT,
            notes TEXT,
            UNIQUE(library_uuid, uuid),
            UNIQUE(library_uuid, calibre_book_id)
        )
    ''')
    conn.commit()
    conn.close()

    mapping_table.ensure_table(library_path)

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    cols = {r['name'] for r in conn.execute('PRAGMA table_info(calimob_books_sync)').fetchall()}
    conn.close()
    assert 'last_modified' in cols, "last_modified column not added despite legacy columns"
    assert 'last_modified_server' in cols
    assert 'metadata_hash_cache' in cols
    assert 'files_hash' in cols
