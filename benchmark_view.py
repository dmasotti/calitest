#!/usr/bin/env python3
"""
Test VIEW with hash computation in SQLite.
"""
import sqlite3
import time

DB_PATH = "/Users/macbookpro/Library/CloudStorage/Dropbox/Calibre/metadata_1.db"

def test_view_with_hash(limit=100):
    """Test creating a view with hash computation."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"\n=== Test VIEW with hash - {limit} books ===")
    
    # Drop view if exists
    cursor.execute("DROP VIEW IF EXISTS books_with_hash")
    
    # Create view with hash computation (Python will compute hash)
    # SQLite 3.39 doesn't have sha256() built-in
    cursor.execute("""
        CREATE VIEW books_with_hash AS
        SELECT 
            b.id,
            b.uuid,
            b.title,
            b.author_sort,
            (SELECT s.name FROM series s
             JOIN books_series_link bsl ON s.id = bsl.series
             WHERE bsl.book = b.id LIMIT 1) as series_name,
            b.series_index,
            (SELECT group_concat(t.name, ',')
             FROM tags t
             JOIN books_tags_link btl ON t.id = btl.tag
             WHERE btl.book = b.id
             ORDER BY t.name) as tags_normalized,
            (SELECT group_concat(type || ':' || val, ',')
             FROM identifiers
             WHERE book = b.id
             ORDER BY type) as identifiers_normalized,
            (SELECT p.name FROM publishers p
             JOIN books_publishers_link bpl ON p.id = bpl.publisher
             WHERE bpl.book = b.id LIMIT 1) as publisher,
            (SELECT group_concat(l.lang_code, ',')
             FROM languages l
             JOIN books_languages_link bll ON l.id = bll.lang_code
             WHERE bll.book = b.id
             ORDER BY l.lang_code) as languages_normalized,
            b.pubdate,
            (SELECT r.rating FROM ratings r
             JOIN books_ratings_link brl ON r.id = brl.rating
             WHERE brl.book = b.id LIMIT 1) as rating,
            c.text as comments,
            -- Concatenated payload for hash (computed in Python)
            coalesce(b.uuid, '') || '|' ||
            coalesce(b.title, '') || '|' ||
            coalesce(b.author_sort, '') || '|' ||
            coalesce((SELECT s.name FROM series s
                      JOIN books_series_link bsl ON s.id = bsl.series
                      WHERE bsl.book = b.id LIMIT 1), '') || '|' ||
            coalesce(printf('%.1f', b.series_index), '') || '|' ||
            coalesce((SELECT group_concat(t.name, ',')
                      FROM tags t
                      JOIN books_tags_link btl ON t.id = btl.tag
                      WHERE btl.book = b.id
                      ORDER BY t.name), '') || '|' ||
            coalesce((SELECT group_concat(type || ':' || val, ',')
                      FROM identifiers
                      WHERE book = b.id
                      ORDER BY type), '') || '|' ||
            coalesce((SELECT p.name FROM publishers p
                      JOIN books_publishers_link bpl ON p.id = bpl.publisher
                      WHERE bpl.book = b.id LIMIT 1), '') || '|' ||
            coalesce((SELECT group_concat(l.lang_code, ',')
                      FROM languages l
                      JOIN books_languages_link bll ON l.id = bll.lang_code
                      WHERE bll.book = b.id
                      ORDER BY l.lang_code), '') || '|' ||
            coalesce(b.pubdate, '') || '|' ||
            coalesce(cast((SELECT r.rating FROM ratings r
                           JOIN books_ratings_link brl ON r.id = brl.rating
                           WHERE brl.book = b.id LIMIT 1) as text), '') || '|' ||
            coalesce(c.text, '') as hash_payload
        FROM books b
        LEFT JOIN comments c ON c.book = b.id
    """)
    
    print("View created successfully")
    
    # Test query performance
    start = time.time()
    cursor.execute(f"SELECT id, uuid, hash_payload FROM books_with_hash LIMIT ?", (limit,))
    query_time = time.time()
    print(f"Query time: {query_time - start:.3f}s")
    
    rows = cursor.fetchall()
    fetch_time = time.time()
    print(f"Fetch time: {fetch_time - query_time:.3f}s")
    
    # Compute hash in Python (since SQLite doesn't have sha256)
    import hashlib
    hashes = []
    for row in rows:
        h = hashlib.sha256(row[2].encode('utf-8')).hexdigest()
        hashes.append((row[0], row[1], h))
    
    hash_time = time.time()
    print(f"Hash computation: {hash_time - fetch_time:.3f}s")
    
    total_time = hash_time - start
    print(f"Total time: {total_time:.3f}s")
    print(f"Per book: {(total_time / limit) * 1000:.2f}ms")
    
    # Cleanup
    cursor.execute("DROP VIEW books_with_hash")
    
    conn.close()
    return total_time

if __name__ == '__main__':
    test_view_with_hash(100)
    print("\n" + "="*50)
    test_view_with_hash(1000)
