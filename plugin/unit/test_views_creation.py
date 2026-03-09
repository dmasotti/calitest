"""Test that VIEWs are created automatically."""
import pytest
import tempfile
import os
import sqlite3


def _create_minimal_calibre_schema(conn):
    conn.execute("CREATE TABLE books (id INTEGER PRIMARY KEY, uuid TEXT, title TEXT, author_sort TEXT, series_index REAL, pubdate TEXT, last_modified INTEGER)")
    conn.execute("CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE books_series_link (book INTEGER, series INTEGER)")
    conn.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)")
    conn.execute("CREATE TABLE books_tags_link (book INTEGER, tag INTEGER)")
    conn.execute("CREATE TABLE identifiers (book INTEGER, type TEXT, val TEXT)")
    conn.execute("CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT)")
    conn.execute("CREATE TABLE books_languages_link (book INTEGER, lang_code INTEGER)")
    conn.execute("CREATE TABLE ratings (id INTEGER PRIMARY KEY, rating INTEGER)")
    conn.execute("CREATE TABLE books_ratings_link (book INTEGER, rating INTEGER)")


def test_views_created_on_ensure_table(tmp_path):
    """Test that _ensure_table creates VIEWs."""
    from calibre_plugins.sync_calimob import mapping_table as mt

    db_path = tmp_path / "metadata.db"
    conn = sqlite3.connect(str(db_path))
    _create_minimal_calibre_schema(conn)

    mt._ensure_table(conn)
    
    # Verify VIEWs exist
    cursor = conn.cursor()
    
    # Check VIEW 1
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name='calimob_books_hash_v2'"
    )
    assert cursor.fetchone() is not None, "VIEW calimob_books_hash_v2 not created"
    
    # Check VIEW 2
    cursor.execute(
        "SELECT name FROM sqlite_master WHERE type='view' AND name='calimob_library_hash_payload'"
    )
    assert cursor.fetchone() is not None, "VIEW calimob_library_hash_payload not created"
    conn.close()


def test_views_work_with_empty_db(mock_calibre_db):
    """Test that VIEWs work even with no books."""
    from calibre_plugins.sync_calimob import sync_utils
    
    # Should return None or empty result, not crash
    result = sync_utils.get_library_hash(mock_calibre_db, "test-library-uuid")
    
    # Empty DB should return None or 0 books
    if result:
        assert result.get('total_books', 0) == 0


@pytest.mark.skip(reason="Requires real DB, not mock")
def test_fast_path_available_after_init(mock_calibre_db):
    """Test that fast path is available after initialization."""
    from calibre_plugins.sync_calimob import sync_utils, mapping_table as mt
    
    # Ensure VIEWs exist
    conn = mock_calibre_db.new_api.backend.conn
    mt._ensure_table(conn)
    
    # Add a book
    mock_calibre_db.new_api.add_books(
        [(tempfile.NamedTemporaryFile(suffix='.epub', delete=False).name, ['epub'])],
        ['Test Book'],
        ['Test Author']
    )
    
    # Debug: check if VIEW returns data
    cursor = conn.cursor()
    cursor.execute("SELECT * FROM calimob_library_hash_payload")
    row = cursor.fetchone()
    print(f"VIEW result: {row}")
    
    # Fast path should work (library_uuid not used anymore)
    result = sync_utils.get_library_hash(mock_calibre_db, None)
    print(f"get_library_hash result: {result}")
    
    assert result is not None, "Fast path not available"
    assert 'library_metadata_hash' in result
    assert result['total_books'] >= 1
