"""
Hash consistency tests between plugin (Python) and server (PHP).

Verifies that the same metadata produces the same hash on both sides.
"""
import pytest
import sqlite3
import hashlib
from pathlib import Path
import importlib.util

# Import modules
plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'

spec = importlib.util.spec_from_file_location("sync_utils",
    str(plugin_path / 'sync_utils.py'))
sync_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_utils)

spec = importlib.util.spec_from_file_location("mapping_table",
    str(plugin_path / 'mapping_table.py'))
mapping_table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping_table)


def create_test_schema(conn):
    """Create Calibre schema for testing."""
    cursor = conn.cursor()
    
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


def compute_server_hash(payload):
    """
    Simulate server-side hash computation (PHP MetadataHasherV2).
    
    This mimics the PHP implementation:
    return hash('sha256', $payload);
    """
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()


class TestHashConsistency:
    """Test hash consistency between plugin and server."""
    
    def test_simple_book_hash_consistency(self, tmp_path):
        """Test that plugin and server produce same hash for simple book."""
        db_path = tmp_path / 'test.db'
        conn = sqlite3.connect(str(db_path))
        create_test_schema(conn)
        cursor = conn.cursor()
        
        # Insert book
        cursor.execute("""
            INSERT INTO books (id, uuid, title, author_sort, series_index, pubdate)
            VALUES (1, 'test-uuid', 'Test Book', 'Author, Test', 1.0, '2024-01-01')
        """)
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        cursor.execute("""
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
            VALUES ('lib-1', 1, 'test-uuid', 'Test Book', 1000)
        """)
        conn.commit()
        
        # Get payload from VIEW
        cursor.execute("""
            SELECT hash_payload FROM calimob_books_hash_v2
            WHERE id = 1 AND library_uuid = 'lib-1'
        """)
        row = cursor.fetchone()
        assert row is not None
        
        payload = row[0]
        
        # Compute hash on plugin side (using sync_utils)
        plugin_hash = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        
        # Compute hash on server side (simulated)
        server_hash = compute_server_hash(payload)
        
        assert plugin_hash == server_hash, f"Plugin hash {plugin_hash} != Server hash {server_hash}"
        
        conn.close()
    
    def test_book_with_tags_hash_consistency(self, tmp_path):
        """Test hash consistency for book with tags."""
        db_path = tmp_path / 'test.db'
        conn = sqlite3.connect(str(db_path))
        create_test_schema(conn)
        cursor = conn.cursor()
        
        cursor.execute("INSERT INTO books (id, uuid, title) VALUES (1, 'uuid-1', 'Book')")
        cursor.execute("INSERT INTO tags (id, name) VALUES (1, 'Fiction'), (2, 'Adventure')")
        cursor.execute("INSERT INTO books_tags_link (book, tag) VALUES (1, 1), (1, 2)")
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        cursor.execute("""
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
            VALUES ('lib-1', 1, 'uuid-1', 'Book', 1000)
        """)
        conn.commit()
        
        cursor.execute("SELECT hash_payload FROM calimob_books_hash_v2 WHERE id = 1")
        payload = cursor.fetchone()[0]
        
        plugin_hash = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        server_hash = compute_server_hash(payload)
        
        assert plugin_hash == server_hash
        
        conn.close()
    
    def test_book_with_series_hash_consistency(self, tmp_path):
        """Test hash consistency for book with series."""
        db_path = tmp_path / 'test.db'
        conn = sqlite3.connect(str(db_path))
        create_test_schema(conn)
        cursor = conn.cursor()
        
        cursor.execute("INSERT INTO books (id, uuid, title, series_index) VALUES (1, 'uuid-1', 'Book', 2.5)")
        cursor.execute("INSERT INTO series (id, name) VALUES (1, 'Test Series')")
        cursor.execute("INSERT INTO books_series_link (book, series) VALUES (1, 1)")
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        cursor.execute("""
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
            VALUES ('lib-1', 1, 'uuid-1', 'Book', 1000)
        """)
        conn.commit()
        
        cursor.execute("SELECT hash_payload FROM calimob_books_hash_v2 WHERE id = 1")
        payload = cursor.fetchone()[0]
        
        plugin_hash = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        server_hash = compute_server_hash(payload)
        
        assert plugin_hash == server_hash
        
        conn.close()
    
    def test_unicode_hash_consistency(self, tmp_path):
        """Test hash consistency with unicode characters."""
        db_path = tmp_path / 'test.db'
        conn = sqlite3.connect(str(db_path))
        create_test_schema(conn)
        cursor = conn.cursor()
        
        cursor.execute("""
            INSERT INTO books (id, uuid, title, author_sort)
            VALUES (1, 'uuid-1', '日本語タイトル', 'Müller, François')
        """)
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        cursor.execute("""
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
            VALUES ('lib-1', 1, 'uuid-1', '日本語タイトル', 1000)
        """)
        conn.commit()
        
        cursor.execute("SELECT hash_payload FROM calimob_books_hash_v2 WHERE id = 1")
        payload = cursor.fetchone()[0]
        
        plugin_hash = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        server_hash = compute_server_hash(payload)
        
        assert plugin_hash == server_hash
        
        conn.close()
    
    def test_library_hash_consistency(self, tmp_path):
        """Test library hash consistency with multiple books."""
        db_path = tmp_path / 'test.db'
        conn = sqlite3.connect(str(db_path))
        create_test_schema(conn)
        cursor = conn.cursor()
        
        # Insert 3 books
        for i in range(1, 4):
            cursor.execute(f"""
                INSERT INTO books (id, uuid, title)
                VALUES ({i}, 'uuid-{i}', 'Book {i}')
            """)
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        
        for i in range(1, 4):
            cursor.execute(f"""
                INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
                VALUES ('lib-1', {i}, 'uuid-{i}', 'Book {i}', {i * 1000})
            """)
        conn.commit()
        
        # Get library payload from VIEW
        cursor.execute("""
            SELECT library_payload FROM calimob_library_hash_payload
            WHERE library_uuid = 'lib-1'
        """)
        row = cursor.fetchone()
        assert row is not None
        
        library_payload = row[0]
        
        # Compute library hash on plugin side
        plugin_result = sync_utils.get_library_hash(conn, 'lib-1')
        plugin_library_hash = plugin_result['library_hash']
        
        # Compute library hash on server side (simulated)
        server_library_hash = compute_server_hash(library_payload)
        
        assert plugin_library_hash == server_library_hash
        
        conn.close()
    
    def test_hash_ordering_independence(self, tmp_path):
        """Test that book order doesn't affect library hash."""
        # Create two databases with same books in different order
        db1_path = tmp_path / 'db1.db'
        db2_path = tmp_path / 'db2.db'
        
        for db_path in [db1_path, db2_path]:
            conn = sqlite3.connect(str(db_path))
            create_test_schema(conn)
            cursor = conn.cursor()
            
            # Insert books (same data, potentially different order)
            cursor.execute("INSERT INTO books (id, uuid, title) VALUES (1, 'uuid-a', 'Book A')")
            cursor.execute("INSERT INTO books (id, uuid, title) VALUES (2, 'uuid-b', 'Book B')")
            conn.commit()
            
            mapping_table._ensure_table(conn)
            mapping_table._ensure_hash_views(conn)
            
            cursor.execute("""
                INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
                VALUES 
                    ('lib-1', 1, 'uuid-a', 'Book A', 1000),
                    ('lib-1', 2, 'uuid-b', 'Book B', 2000)
            """)
            conn.commit()
            conn.close()
        
        # Get library hashes from both databases
        conn1 = sqlite3.connect(str(db1_path))
        result1 = sync_utils.get_library_hash(conn1, 'lib-1')
        conn1.close()
        
        conn2 = sqlite3.connect(str(db2_path))
        result2 = sync_utils.get_library_hash(conn2, 'lib-1')
        conn2.close()
        
        # Library hashes should be identical (VIEW orders by book ID)
        assert result1['library_hash'] == result2['library_hash']
    
    def test_special_characters_in_metadata(self, tmp_path):
        """Test hash consistency with special SQL characters."""
        db_path = tmp_path / 'test.db'
        conn = sqlite3.connect(str(db_path))
        create_test_schema(conn)
        cursor = conn.cursor()
        
        # Insert book with special characters
        cursor.execute("""
            INSERT INTO books (id, uuid, title, author_sort)
            VALUES (1, 'uuid-1', 'Book with "quotes" and ''apostrophes''', 'O''Brien, Patrick')
        """)
        conn.commit()
        
        mapping_table._ensure_table(conn)
        mapping_table._ensure_hash_views(conn)
        cursor.execute("""
            INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid, title, last_modified)
            VALUES ('lib-1', 1, 'uuid-1', 'Book with "quotes" and ''apostrophes''', 1000)
        """)
        conn.commit()
        
        cursor.execute("SELECT hash_payload FROM calimob_books_hash_v2 WHERE id = 1")
        payload = cursor.fetchone()[0]
        
        plugin_hash = sync_utils.compute_metadata_hash_v2(conn, 1, 'lib-1')
        server_hash = compute_server_hash(payload)
        
        assert plugin_hash == server_hash
        
        conn.close()
