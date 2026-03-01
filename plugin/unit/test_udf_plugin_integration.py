"""
Test UDF integration in plugin code.

These tests verify that the UDF is properly registered and used
in the actual plugin code paths.
"""
import pytest
import sys
import os
import sqlite3
import tempfile
import shutil

# Add plugin to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..', 'sync_calimob'))

import mapping_table


class TestUDFIntegration:
    """Test UDF registration and usage in plugin."""
    
    @pytest.fixture
    def temp_db(self):
        """Create temporary test database."""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        
        conn = sqlite3.connect(path)
        
        # Create minimal Calibre schema
        conn.execute("""
            CREATE TABLE books (
                id INTEGER PRIMARY KEY,
                uuid TEXT,
                title TEXT,
                author_sort TEXT,
                path TEXT,
                series_index REAL,
                pubdate TEXT,
                last_modified INTEGER
            )
        """)
        
        conn.execute("""
            CREATE TABLE series (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        """)
        
        conn.execute("""
            CREATE TABLE books_series_link (
                id INTEGER PRIMARY KEY,
                book INTEGER,
                series INTEGER
            )
        """)
        
        conn.execute("""
            CREATE TABLE tags (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        """)
        
        conn.execute("""
            CREATE TABLE books_tags_link (
                id INTEGER PRIMARY KEY,
                book INTEGER,
                tag INTEGER
            )
        """)
        
        conn.execute("""
            CREATE TABLE identifiers (
                id INTEGER PRIMARY KEY,
                book INTEGER,
                type TEXT,
                val TEXT
            )
        """)
        
        conn.execute("""
            CREATE TABLE publishers (
                id INTEGER PRIMARY KEY,
                name TEXT
            )
        """)
        
        conn.execute("""
            CREATE TABLE books_publishers_link (
                id INTEGER PRIMARY KEY,
                book INTEGER,
                publisher INTEGER
            )
        """)
        
        conn.execute("""
            CREATE TABLE languages (
                id INTEGER PRIMARY KEY,
                lang_code TEXT
            )
        """)
        
        conn.execute("""
            CREATE TABLE books_languages_link (
                id INTEGER PRIMARY KEY,
                book INTEGER,
                lang_code INTEGER
            )
        """)
        
        conn.execute("""
            CREATE TABLE ratings (
                id INTEGER PRIMARY KEY,
                rating INTEGER
            )
        """)
        
        conn.execute("""
            CREATE TABLE books_ratings_link (
                id INTEGER PRIMARY KEY,
                book INTEGER,
                rating INTEGER
            )
        """)
        
        conn.execute("""
            CREATE TABLE comments (
                id INTEGER PRIMARY KEY,
                book INTEGER,
                text TEXT
            )
        """)
        
        # Create calimob_books_sync table
        conn.execute("""
            CREATE TABLE calimob_books_sync (
                id INTEGER PRIMARY KEY,
                library_uuid TEXT,
                calibre_book_id INTEGER,
                uuid TEXT,
                last_modified INTEGER,
                is_deleted INTEGER DEFAULT 0
            )
        """)
        
        # Insert test data
        conn.execute("""
            INSERT INTO books (id, uuid, title, author_sort, path, series_index, pubdate, last_modified)
            VALUES (1, 'test-uuid-1', 'Test Book 1', 'Author One', 'path1', 1.0, '2020-01-01', 1234567890)
        """)
        
        conn.execute("""
            INSERT INTO books (id, uuid, title, author_sort, path, series_index, pubdate, last_modified)
            VALUES (2, 'test-uuid-2', 'Test Book 2', 'Author Two', 'path2', 2.0, '2020-02-01', 1234567891)
        """)
        
        conn.execute("""
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, last_modified)
            VALUES ('test-library-uuid', 1, 'test-uuid-1', 1234567890)
        """)
        
        conn.execute("""
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, last_modified)
            VALUES ('test-library-uuid', 2, 'test-uuid-2', 1234567891)
        """)
        
        conn.commit()
        conn.close()
        
        yield path
        
        # Cleanup
        os.unlink(path)
    
    def test_sha256_udf_function_exists(self):
        """Test that sha256_udf function is defined."""
        assert hasattr(mapping_table, 'sha256_udf')
        assert callable(mapping_table.sha256_udf)
    
    def test_sha256_udf_returns_correct_hash(self):
        """Test that sha256_udf returns correct SHA256 hash."""
        import hashlib
        
        test_string = "test string"
        expected = hashlib.sha256(test_string.encode('utf-8')).hexdigest()
        result = mapping_table.sha256_udf(test_string)
        
        assert result == expected
    
    def test_sha256_udf_handles_none(self):
        """Test that sha256_udf handles None input."""
        result = mapping_table.sha256_udf(None)
        assert result is None
    
    def test_sha256_udf_handles_empty_string(self):
        """Test that sha256_udf handles empty string."""
        import hashlib
        
        expected = hashlib.sha256(''.encode('utf-8')).hexdigest()
        result = mapping_table.sha256_udf('')
        
        assert result == expected
    
    def test_sha256_udf_handles_unicode(self):
        """Test that sha256_udf handles unicode characters."""
        import hashlib
        
        test_string = "Hello 世界 🌍"
        expected = hashlib.sha256(test_string.encode('utf-8')).hexdigest()
        result = mapping_table.sha256_udf(test_string)
        
        assert result == expected
    
    def test_ensure_hash_views_registers_udf(self, temp_db):
        """Test that _ensure_hash_views registers the UDF."""
        conn = sqlite3.connect(temp_db)
        
        # Call _ensure_hash_views
        mapping_table._ensure_hash_views(conn)
        
        # Test that UDF is registered by using it
        cursor = conn.cursor()
        cursor.execute("SELECT sha256('test')")
        result = cursor.fetchone()[0]
        
        import hashlib
        expected = hashlib.sha256('test'.encode('utf-8')).hexdigest()
        
        assert result == expected
        
        conn.close()
    
    def test_ensure_hash_views_creates_books_hash_view(self, temp_db):
        """Test that _ensure_hash_views creates calimob_books_hash_v2 VIEW."""
        conn = sqlite3.connect(temp_db)
        
        mapping_table._ensure_hash_views(conn)
        
        # Check VIEW exists
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='view' AND name='calimob_books_hash_v2'
        """)
        
        assert cursor.fetchone() is not None
        
        conn.close()
    
    def test_ensure_hash_views_creates_library_hash_view(self, temp_db):
        """Test that _ensure_hash_views creates calimob_library_hash_payload VIEW."""
        conn = sqlite3.connect(temp_db)
        
        mapping_table._ensure_hash_views(conn)
        
        # Check VIEW exists
        cursor = conn.cursor()
        cursor.execute("""
            SELECT name FROM sqlite_master 
            WHERE type='view' AND name='calimob_library_hash_payload'
        """)
        
        assert cursor.fetchone() is not None
        
        conn.close()
    
    def test_books_hash_view_returns_hash(self, temp_db):
        """Test that calimob_books_hash_v2 VIEW returns metadata_hash."""
        conn = sqlite3.connect(temp_db)
        
        mapping_table._ensure_hash_views(conn)
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, uuid, metadata_hash 
            FROM calimob_books_hash_v2
            ORDER BY id
        """)
        
        rows = cursor.fetchall()
        
        assert len(rows) == 2
        assert rows[0][0] == 1  # book id
        assert rows[0][1] == 'test-uuid-1'  # uuid
        assert len(rows[0][2]) == 64  # SHA256 hash is 64 chars
        
        conn.close()
    
    def test_books_hash_view_hash_is_deterministic(self, temp_db):
        """Test that hash is deterministic (same input = same hash)."""
        conn = sqlite3.connect(temp_db)
        
        mapping_table._ensure_hash_views(conn)
        
        cursor = conn.cursor()
        
        # Query twice
        cursor.execute("SELECT metadata_hash FROM calimob_books_hash_v2 WHERE id=1")
        hash1 = cursor.fetchone()[0]
        
        cursor.execute("SELECT metadata_hash FROM calimob_books_hash_v2 WHERE id=1")
        hash2 = cursor.fetchone()[0]
        
        assert hash1 == hash2
        
        conn.close()
    
    def test_library_hash_view_returns_aggregated_hash(self, temp_db):
        """Test that calimob_library_hash_payload VIEW returns library_hash."""
        conn = sqlite3.connect(temp_db)
        
        mapping_table._ensure_hash_views(conn)
        
        cursor = conn.cursor()
        cursor.execute("""
            SELECT library_uuid, library_hash, total_books
            FROM calimob_library_hash_payload
        """)
        
        row = cursor.fetchone()
        
        assert row is not None
        assert row[0] == 'test-library-uuid'
        assert len(row[1]) == 64  # SHA256 hash
        assert row[2] == 2  # 2 books
        
        conn.close()
    
    def test_library_hash_changes_when_book_changes(self, temp_db):
        """Test that library hash changes when a book is modified."""
        conn = sqlite3.connect(temp_db)
        
        mapping_table._ensure_hash_views(conn)
        
        cursor = conn.cursor()
        
        # Get initial hash
        cursor.execute("SELECT library_hash FROM calimob_library_hash_payload")
        hash1 = cursor.fetchone()[0]
        
        # Modify a book
        cursor.execute("UPDATE books SET title='Modified Title' WHERE id=1")
        conn.commit()
        
        # Get new hash
        cursor.execute("SELECT library_hash FROM calimob_library_hash_payload")
        hash2 = cursor.fetchone()[0]
        
        assert hash1 != hash2, "Library hash should change when book is modified"
        
        conn.close()
    
    def test_ensure_hash_views_handles_missing_tables_gracefully(self):
        """Test that _ensure_hash_views doesn't crash if tables are missing."""
        fd, path = tempfile.mkstemp(suffix='.db')
        os.close(fd)
        
        conn = sqlite3.connect(path)
        
        # Don't create any tables - should not crash
        try:
            mapping_table._ensure_hash_views(conn)
            # Should not raise exception
        except Exception as e:
            pytest.fail(f"_ensure_hash_views should not crash on missing tables: {e}")
        finally:
            conn.close()
            os.unlink(path)
    
    def test_udf_performance_is_acceptable(self, temp_db):
        """Test that UDF performance is acceptable."""
        import time
        
        conn = sqlite3.connect(temp_db)
        mapping_table._ensure_hash_views(conn)
        
        cursor = conn.cursor()
        
        # Benchmark: Calculate hashes for all books
        start = time.time()
        cursor.execute("SELECT COUNT(*), COUNT(metadata_hash) FROM calimob_books_hash_v2")
        total, hashed = cursor.fetchone()
        elapsed = time.time() - start
        
        # Should be very fast (< 10ms for 2 books)
        assert elapsed < 0.01, f"UDF too slow: {elapsed}s for {total} books"
        assert total == hashed == 2
        
        conn.close()


class TestUDFEdgeCases:
    """Test edge cases in UDF implementation."""
    
    def test_sha256_udf_with_very_long_string(self):
        """Test UDF with very long string (1MB)."""
        long_string = 'a' * (1024 * 1024)  # 1MB
        
        result = mapping_table.sha256_udf(long_string)
        
        assert result is not None
        assert len(result) == 64
    
    def test_sha256_udf_with_special_characters(self):
        """Test UDF with special SQL characters."""
        test_string = "'; DROP TABLE books; --"
        
        result = mapping_table.sha256_udf(test_string)
        
        assert result is not None
        assert len(result) == 64
    
    def test_sha256_udf_with_newlines(self):
        """Test UDF with newlines and special whitespace."""
        test_string = "line1\nline2\r\nline3\ttab"
        
        result = mapping_table.sha256_udf(test_string)
        
        assert result is not None
        assert len(result) == 64
    
    def test_sha256_udf_consistency_with_hashlib(self):
        """Test that UDF produces same results as hashlib."""
        import hashlib
        
        test_cases = [
            "",
            "test",
            "Hello World",
            "Unicode: 你好世界",
            "Special: !@#$%^&*()",
            "Newlines:\n\r\n",
            "Very long: " + ("x" * 10000)
        ]
        
        for test_string in test_cases:
            udf_result = mapping_table.sha256_udf(test_string)
            hashlib_result = hashlib.sha256(test_string.encode('utf-8')).hexdigest()
            
            assert udf_result == hashlib_result, \
                f"UDF result doesn't match hashlib for: {test_string[:50]}"
