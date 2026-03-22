from __future__ import annotations

import sqlite3

from calibre_plugins.sync_calimob import mapping_table


def _create_library_path_with_books(tmp_path):
    library_root = tmp_path / 'library'
    library_root.mkdir()
    db_path = library_root / 'metadata.db'
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE books (id INTEGER PRIMARY KEY, last_modified TIMESTAMP NOT NULL)"
        )
        conn.commit()
    finally:
        conn.close()
    return str(library_root)


def test_get_modified_book_ids_new_and_modified(tmp_path):
    library_path = _create_library_path_with_books(tmp_path)
    lib_uuid = 'lib-uuid'

    # Create mapping table + one cached row
    mapping_table.upsert_entry(library_path, lib_uuid, 1, {'uuid': 'u1', 'last_modified': 100})

    # Insert books:
    # - id=1 last_modified=101 -> modified (should be returned)
    # - id=2 last_modified=50  -> new (no cache row, should be returned)
    # - id=3 last_modified=99  -> new (no cache row, should be returned)
    db_path = f"{library_path}/metadata.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO books(id,last_modified) VALUES(1,'1970-01-01 00:01:41+00:00')")  # 101
        conn.execute("INSERT INTO books(id,last_modified) VALUES(2,'1970-01-01 00:00:50+00:00')")  # 50
        conn.execute("INSERT INTO books(id,last_modified) VALUES(3,'1970-01-01 00:01:39+00:00')")  # 99
        conn.commit()
    finally:
        conn.close()

    ids = mapping_table.get_modified_book_ids(library_path, lib_uuid)
    assert set(ids) == {1, 2, 3}


def test_get_modified_book_ids_unchanged_not_returned(tmp_path):
    library_path = _create_library_path_with_books(tmp_path)
    lib_uuid = 'lib-uuid'
    mapping_table.upsert_entry(library_path, lib_uuid, 1, {'uuid': 'u1', 'last_modified': 100})
    db_path = f"{library_path}/metadata.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO books(id,last_modified) VALUES(1,'1970-01-01 00:01:40+00:00')")  # 100
        conn.commit()
    finally:
        conn.close()

    assert mapping_table.get_modified_book_ids(library_path, lib_uuid) == []


def test_get_deleted_book_entries(tmp_path):
    library_path = _create_library_path_with_books(tmp_path)
    lib_uuid = 'lib-uuid'
    # Two cached entries, only one will be "deleted" (book table missing)
    mapping_table.upsert_entry(library_path, lib_uuid, 10, {'uuid': 'u10', 'is_deleted': False})
    mapping_table.upsert_entry(library_path, lib_uuid, 11, {'uuid': 'u11', 'is_deleted': False})

    # Only book 11 exists in books table
    db_path = f"{library_path}/metadata.db"
    conn = sqlite3.connect(db_path)
    try:
        conn.execute("INSERT INTO books(id,last_modified) VALUES(11,'1970-01-01 00:00:01+00:00')")
        conn.commit()
    finally:
        conn.close()

    deleted = mapping_table.get_deleted_book_entries(library_path, lib_uuid)
    assert deleted == [(10, 'u10')]


def test_force_rebuild_drops_legacy_columns(tmp_path):
    library_root = tmp_path / 'library'
    library_root.mkdir()
    db_path = library_root / 'metadata.db'
    conn = sqlite3.connect(str(db_path))
    try:
        # Create a legacy calimob_books_sync table with client_ids/title_sort columns
        conn.execute(
            """
            CREATE TABLE calimob_books_sync (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              library_uuid TEXT NOT NULL,
              calibre_book_id INTEGER NOT NULL,
              uuid TEXT,
              title TEXT,
              title_sort TEXT,
              cover_hash TEXT,
              client_ids TEXT,
              notes TEXT,
              UNIQUE(library_uuid, calibre_book_id)
            )
            """
        )
        conn.commit()
    finally:
        conn.close()

    # Trigger explicit destructive rebuild and verify legacy columns are gone.
    assert mapping_table.force_rebuild_table(str(library_root)) is True

    conn = sqlite3.connect(str(db_path))
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(calimob_books_sync)").fetchall()]
    finally:
        conn.close()

    assert 'client_ids' not in cols
    assert 'title_sort' not in cols
    assert 'last_modified' in cols
    assert 'last_modified_server' in cols


def test_ensure_table_adds_missing_columns_via_alter(tmp_path):
    """Regression: old schema without last_modified/files_hash/formats_sig
    causes 'no such column: sync.last_modified' SQL error at runtime.

    _ensure_table must ALTER TABLE ADD COLUMN for each missing column
    instead of raising RuntimeError (which ensure_table swallows silently).
    """
    library_root = tmp_path / 'library'
    library_root.mkdir()
    db_path = library_root / 'metadata.db'
    conn = sqlite3.connect(str(db_path))
    try:
        # Create a minimal old-schema table WITHOUT the newer columns
        conn.execute(
            """
            CREATE TABLE calimob_books_sync (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              library_uuid TEXT NOT NULL,
              calibre_book_id INTEGER NOT NULL,
              uuid TEXT,
              title TEXT,
              cover_hash TEXT,
              created_at TEXT,
              modified_at TEXT,
              last_synced_at TEXT,
              version TEXT,
              deleted_at TEXT,
              UNIQUE(library_uuid, uuid),
              UNIQUE(library_uuid, calibre_book_id)
            )
            """
        )
        # Insert a row to verify data is preserved after migration
        conn.execute(
            "INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title) "
            "VALUES ('lib-1', 1, 'uuid-1', 'Old Book')"
        )
        conn.commit()
    finally:
        conn.close()

    # _ensure_table must succeed (add missing columns), NOT raise
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    try:
        mapping_table._ensure_table(conn)
        conn.commit()

        # Verify all expected columns are now present
        cols = {r['name'] for r in conn.execute("PRAGMA table_info(calimob_books_sync)").fetchall()}
        for expected in mapping_table._EXPECTED_COLUMNS:
            assert expected in cols, f"Column {expected!r} missing after _ensure_table migration"

        # Verify existing data is preserved
        row = conn.execute(
            "SELECT title, last_modified, files_hash, formats_sig FROM calimob_books_sync WHERE uuid='uuid-1'"
        ).fetchone()
        assert row is not None, "Existing row lost after migration"
        assert row['title'] == 'Old Book'
        assert row['last_modified'] is None  # newly added column, default NULL
        assert row['files_hash'] is None
        assert row['formats_sig'] is None
    finally:
        conn.close()






