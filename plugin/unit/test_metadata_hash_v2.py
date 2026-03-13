"""
Unit tests for metadata hash v2 implementation.

Verifies:
1. VIEW creation works
2. Hash v2 computation is correct
3. Hash v2 is deterministic
4. Library hash works
5. Performance is acceptable
"""
import sys
import os
import sqlite3
import tempfile
import shutil
import hashlib
import time
from pathlib import Path

import pytest

# Import modules without Calibre dependencies
import importlib.util

plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'

spec = importlib.util.spec_from_file_location("sync_utils", 
    str(plugin_path / 'sync_utils.py'))
sync_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_utils)

spec = importlib.util.spec_from_file_location("mapping_table",
    str(plugin_path / 'mapping_table.py'))
mapping_table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping_table)


def create_calibre_schema(conn):
    """Create complete Calibre schema for testing."""
    cursor = conn.cursor()
    
    # Books table with all required columns
    cursor.execute('''
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            uuid TEXT,
            title TEXT,
            author_sort TEXT,
            series_index REAL DEFAULT 1.0,
            pubdate TEXT,
            timestamp TEXT
        )
    ''')
    
    # Related tables
    cursor.execute('CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT)')
    cursor.execute('CREATE TABLE books_authors_link (book INTEGER, author INTEGER)')
    cursor.execute('CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT)')
    cursor.execute('CREATE TABLE books_series_link (book INTEGER, series INTEGER)')
    cursor.execute('CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)')
    cursor.execute('CREATE TABLE books_tags_link (book INTEGER, tag INTEGER)')
    cursor.execute('CREATE TABLE identifiers (book INTEGER, type TEXT, val TEXT)')
    cursor.execute('CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT)')
    cursor.execute('CREATE TABLE books_publishers_link (book INTEGER, publisher INTEGER)')
    cursor.execute('CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT)')
    cursor.execute('CREATE TABLE books_languages_link (book INTEGER, lang_code INTEGER)')
    cursor.execute('CREATE TABLE ratings (id INTEGER PRIMARY KEY, rating INTEGER)')
    cursor.execute('CREATE TABLE books_ratings_link (book INTEGER, rating INTEGER)')
    cursor.execute('CREATE TABLE comments (book INTEGER, text TEXT)')
    
    conn.commit()


@pytest.fixture
def test_db(tmp_path):
    """Create test database with sample data."""
    db_path = tmp_path / 'metadata.db'
    
    conn = sqlite3.connect(str(db_path))
    create_calibre_schema(conn)
    cursor = conn.cursor()
    
    # Insert test data
    cursor.execute('''
        INSERT INTO books (id, uuid, title, author_sort, series_index, pubdate)
        VALUES (1, 'test-uuid-123', 'Test Book', 'Author, Test', 1.0, '2024-01-01')
    ''')
    cursor.execute("INSERT INTO authors (id, name) VALUES (1, 'Author Test')")
    cursor.execute("INSERT INTO books_authors_link (book, author) VALUES (1, 1)")
    
    cursor.execute("INSERT INTO series (id, name) VALUES (1, 'Test Series')")
    cursor.execute("INSERT INTO books_series_link (book, series) VALUES (1, 1)")
    
    cursor.execute("INSERT INTO tags (id, name) VALUES (1, 'Fiction'), (2, 'Adventure')")
    cursor.execute("INSERT INTO books_tags_link (book, tag) VALUES (1, 1), (1, 2)")
    
    cursor.execute("INSERT INTO identifiers (book, type, val) VALUES (1, 'isbn', '1234567890')")
    
    cursor.execute("INSERT INTO publishers (id, name) VALUES (1, 'Test Publisher')")
    cursor.execute("INSERT INTO books_publishers_link (book, publisher) VALUES (1, 1)")
    
    cursor.execute("INSERT INTO languages (id, lang_code) VALUES (1, 'eng')")
    cursor.execute("INSERT INTO books_languages_link (book, lang_code) VALUES (1, 1)")
    
    cursor.execute("INSERT INTO ratings (id, rating) VALUES (1, 4)")
    cursor.execute("INSERT INTO books_ratings_link (book, rating) VALUES (1, 1)")
    
    cursor.execute("INSERT INTO comments (book, text) VALUES (1, 'Test description')")
    
    conn.commit()
    
    # Create calimob_books_sync table and VIEWs
    mapping_table._ensure_table(conn)
    mapping_table._ensure_hash_views(conn)
    
    # Insert sync entry
    cursor.execute('''
        INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
        VALUES ('test-lib-uuid', 1, 'test-uuid-123', 'Test Book', 1234567890)
    ''')
    
    conn.commit()
    
    yield conn
    
    conn.close()


class TestViewCreation:
    """Test VIEW creation."""
    
    def test_views_are_created(self, test_db):
        """Test that VIEWs are created correctly."""
        cursor = test_db.cursor()
        
        # Check VIEW exists
        cursor.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='calimob_books_hash_v2'")
        assert cursor.fetchone() is not None, "VIEW calimob_books_hash_v2 not created"
        
        cursor.execute("SELECT name FROM sqlite_master WHERE type='view' AND name='calimob_library_hash_payload'")
        assert cursor.fetchone() is not None, "VIEW calimob_library_hash_payload not created"
    
    def test_view_query_works(self, test_db):
        """Test VIEW query returns data."""
        cursor = test_db.cursor()
        
        cursor.execute("SELECT id, uuid, metadata_hash FROM calimob_books_hash_v2 WHERE id = 1")
        row = cursor.fetchone()
        
        assert row is not None, "VIEW query returned no results"
        assert row[0] == 1, "Wrong book ID"
        assert row[1] == 'test-uuid-123', "Wrong UUID"
        assert len(row[2]) > 0, "Empty hash payload"


class TestHashV2Computation:
    """Test hash v2 computation."""
    
    def test_compute_hash_v2(self, test_db):
        """Test hash v2 computation."""
        hash_v2 = sync_utils.compute_metadata_hash_v2(test_db, 1, 'test-lib-uuid')
        
        assert hash_v2 is not None, "Hash v2 is None"
        assert len(hash_v2) == 64, f"Hash v2 wrong length: {len(hash_v2)}"
        assert hash_v2.isalnum(), "Hash v2 not alphanumeric"
    
    def test_hash_is_deterministic(self, test_db):
        """Test hash v2 is deterministic."""
        hash_v2_1 = sync_utils.compute_metadata_hash_v2(test_db, 1, 'test-lib-uuid')
        hash_v2_2 = sync_utils.compute_metadata_hash_v2(test_db, 1, 'test-lib-uuid')
        
        assert hash_v2_1 == hash_v2_2, "Hash v2 not deterministic"


class TestLibraryHash:
    """Test library hash computation."""
    
    def test_get_library_hash(self, test_db):
        """Test library hash computation."""
        result = sync_utils.get_library_hash(test_db, 'test-lib-uuid')
        
        assert result is not None, "Library hash is None"
        assert 'library_metadata_hash' in result, "Missing library_metadata_hash"
        assert 'library_covers_hash' in result, "Missing library_covers_hash"
        assert 'library_files_hash' in result, "Missing library_files_hash"
        assert 'total_books' in result, "Missing total_books"
        assert 'last_modified' in result, "Missing last_modified"
        
        assert len(result['library_metadata_hash']) == 64, "Library metadata hash wrong length"
        assert result['total_books'] == 1, f"Wrong total_books: {result['total_books']}"


class TestPerformance:
    """Test performance of hash v2."""
    
    def test_performance(self, test_db):
        """Test performance is acceptable."""
        # Warm up
        sync_utils.compute_metadata_hash_v2(test_db, 1, 'test-lib-uuid')
        
        # Measure
        iterations = 100
        start = time.time()
        
        for _ in range(iterations):
            sync_utils.compute_metadata_hash_v2(test_db, 1, 'test-lib-uuid')
        
        elapsed = time.time() - start
        per_book = (elapsed / iterations) * 1000
        
        # Should be < 5ms per book (target: 0.3ms, but test env is slower)
        assert per_book < 5, f"Too slow: {per_book}ms per book"


class TestEdgeCases:
    """Test edge cases and error handling."""
    
    def test_book_with_minimal_metadata(self, tmp_path):
        """Test book with only required fields."""
        db_path = tmp_path / 'minimal.db'
        conn = sqlite3.connect(str(db_path))
        create_calibre_schema(conn)
        cursor = conn.cursor()
        
        # Insert minimal book (only title)
        cursor.execute("INSERT INTO books (id, uuid, title) VALUES (1, 'uuid-1', 'Minimal Book')")
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        cursor.execute('''
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
            VALUES ('lib-1', 1, 'uuid-1', 'Minimal Book', 1000)
        ''')
        conn.commit()
        
        # Should compute hash even with minimal metadata
        hash_v2 = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        assert hash_v2 is not None
        assert len(hash_v2) == 64
        
        conn.close()
    
    def test_book_with_null_values(self, tmp_path):
        """Test book with NULL values in optional fields."""
        db_path = tmp_path / 'nulls.db'
        conn = sqlite3.connect(str(db_path))
        create_calibre_schema(conn)
        cursor = conn.cursor()
        
        # Insert book with NULLs
        cursor.execute("INSERT INTO books (id, uuid, title, author_sort, pubdate) VALUES (1, 'uuid-1', 'Book', NULL, NULL)")
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        cursor.execute('''
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
            VALUES ('lib-1', 1, 'uuid-1', 'Book', 1000)
        ''')
        conn.commit()
        
        hash_v2 = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        assert hash_v2 is not None
        
        conn.close()
    
    def test_book_not_in_sync_table(self, tmp_path):
        """Test book that hasn't been synced yet."""
        db_path = tmp_path / 'not_synced.db'
        conn = sqlite3.connect(str(db_path))
        create_calibre_schema(conn)
        cursor = conn.cursor()
        
        cursor.execute("INSERT INTO books (id, uuid, title) VALUES (1, 'uuid-1', 'Book')")
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        # Don't insert into calimob_books_sync
        
        # Should still return hash (VIEWs read from books table directly)
        hash_v2 = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        assert hash_v2 is not None
        assert len(hash_v2) == 64
        
        conn.close()
    
    def test_empty_library(self, tmp_path):
        """Test library with no books."""
        db_path = tmp_path / 'empty.db'
        conn = sqlite3.connect(str(db_path))
        create_calibre_schema(conn)
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        
        # Should return None (no books)
        result = sync_utils.get_library_hash(conn, 'lib-1')
        assert result is None
        
        conn.close()
    
    def test_library_with_multiple_books(self, tmp_path):
        """Test library hash with multiple books."""
        db_path = tmp_path / 'multi.db'
        conn = sqlite3.connect(str(db_path))
        create_calibre_schema(conn)
        cursor = conn.cursor()
        
        # Insert 3 books
        cursor.execute("INSERT INTO books (id, uuid, title) VALUES (1, 'uuid-1', 'Book 1')")
        cursor.execute("INSERT INTO books (id, uuid, title) VALUES (2, 'uuid-2', 'Book 2')")
        cursor.execute("INSERT INTO books (id, uuid, title) VALUES (3, 'uuid-3', 'Book 3')")
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        cursor.execute('''
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
            VALUES 
                ('lib-1', 1, 'uuid-1', 'Book 1', 1000),
                ('lib-1', 2, 'uuid-2', 'Book 2', 2000),
                ('lib-1', 3, 'uuid-3', 'Book 3', 3000)
        ''')
        conn.commit()
        
        result = sync_utils.get_library_hash(conn, 'lib-1')
        assert result is not None
        assert result['total_books'] == 3
        # Note: last_modified is now 0 because VIEWs don't use calimob_books_sync
        assert result['last_modified'] == 0
        assert len(result['library_metadata_hash']) == 64
        
        conn.close()
    
    def test_hash_changes_on_metadata_update(self, tmp_path):
        """Test that hash changes when metadata changes."""
        db_path = tmp_path / 'update.db'
        conn = sqlite3.connect(str(db_path))
        create_calibre_schema(conn)
        cursor = conn.cursor()
        
        cursor.execute("INSERT INTO books (id, uuid, title) VALUES (1, 'uuid-1', 'Original Title')")
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        cursor.execute('''
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
            VALUES ('lib-1', 1, 'uuid-1', 'Original Title', 1000)
        ''')
        conn.commit()
        
        hash_before = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        
        # Update title
        cursor.execute("UPDATE books SET title = 'Updated Title' WHERE id = 1")
        conn.commit()
        
        hash_after = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        
        assert hash_before != hash_after, "Hash should change when metadata changes"
        
        conn.close()
    
    def test_unicode_and_special_characters(self, tmp_path):
        """Test hash with unicode and special characters."""
        db_path = tmp_path / 'unicode.db'
        conn = sqlite3.connect(str(db_path))
        create_calibre_schema(conn)
        cursor = conn.cursor()
        
        # Insert book with unicode
        cursor.execute("INSERT INTO books (id, uuid, title, author_sort) VALUES (1, 'uuid-1', '日本語タイトル', 'Müller, François')")
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        cursor.execute('''
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
            VALUES ('lib-1', 1, 'uuid-1', '日本語タイトル', 1000)
        ''')
        conn.commit()
        
        hash_v2 = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        assert hash_v2 is not None
        assert len(hash_v2) == 64
        
        # Should be deterministic with unicode
        hash_v2_again = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        assert hash_v2 == hash_v2_again
        
        conn.close()
    
    def test_wrong_library_uuid(self, test_db):
        """Test querying with wrong library UUID (should still return hash)."""
        # Note: After removing library_uuid filter, hash is always returned
        # This is correct because VIEWs now read directly from books table
        hash_v2 = sync_utils.compute_metadata_hash_v2(test_db, 1, 'wrong-library-uuid')
        assert hash_v2 is not None
        assert len(hash_v2) == 64
    
    def test_nonexistent_book_id(self, test_db):
        """Test querying non-existent book."""
        hash_v2 = sync_utils.compute_metadata_hash_v2(test_db, 99999, 'test-lib-uuid')
        assert hash_v2 is None
