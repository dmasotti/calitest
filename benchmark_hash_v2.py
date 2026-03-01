#!/usr/bin/env python3
"""
Benchmark metadata hash computation v2 (SQL-native method).
Tests performance on real Calibre database.
"""
import sqlite3
import hashlib
import time

DB_PATH = "/Users/macbookpro/Library/CloudStorage/Dropbox/Calibre/metadata_1.db"

def compute_hash_v2(row):
    """Compute hash from denormalized row data."""
    parts = [
        row[0] or '',  # uuid
        row[1] or '',  # title
        row[2] or '',  # author_sort
        row[3] or '',  # series_name
        f"{row[4]:.1f}" if row[4] else '',  # series_index
        row[5] or '',  # tags_normalized
        row[6] or '',  # identifiers_normalized
        row[7] or '',  # publisher
        row[8] or '',  # languages_normalized
        row[9] or '',  # pubdate
        str(row[10]) if row[10] else '',  # rating
        row[11] or '',  # comments
    ]
    payload = '|'.join(parts)
    return hashlib.sha256(payload.encode('utf-8')).hexdigest()

def benchmark_v2(limit=100):
    """Benchmark v2 method with denormalized data."""
    conn = sqlite3.connect(DB_PATH)
    cursor = conn.cursor()
    
    print(f"\n=== Benchmark v2 (SQL-native) - {limit} books ===")
    
    start = time.time()
    
    # Single query to get all denormalized data
    cursor.execute("""
        SELECT 
            b.uuid,
            b.title,
            b.author_sort,
            (SELECT s.name FROM series s
             JOIN books_series_link bsl ON s.id = bsl.series
             WHERE bsl.book = b.id
             LIMIT 1) as series_name,
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
             WHERE bpl.book = b.id
             LIMIT 1) as publisher,
            (SELECT group_concat(l.lang_code, ',')
             FROM languages l
             JOIN books_languages_link bll ON l.id = bll.lang_code
             WHERE bll.book = b.id
             ORDER BY l.lang_code) as languages_normalized,
            b.pubdate,
            (SELECT r.rating FROM ratings r
             JOIN books_ratings_link brl ON r.id = brl.rating
             WHERE brl.book = b.id
             LIMIT 1) as rating,
            c.text as comments
        FROM books b
        LEFT JOIN comments c ON c.book = b.id
        LIMIT ?
    """, (limit,))
    
    query_time = time.time()
    print(f"Query time: {query_time - start:.3f}s")
    
    rows = cursor.fetchall()
    fetch_time = time.time()
    print(f"Fetch time: {fetch_time - query_time:.3f}s")
    
    # Compute hashes
    hashes = []
    for row in rows:
        h = compute_hash_v2(row)
        hashes.append(h)
    
    hash_time = time.time()
    print(f"Hash computation: {hash_time - fetch_time:.3f}s")
    
    total_time = hash_time - start
    print(f"Total time: {total_time:.3f}s")
    print(f"Per book: {(total_time / limit) * 1000:.2f}ms")
    print(f"Hashes computed: {len(hashes)}")
    
    conn.close()
    return total_time

if __name__ == '__main__':
    # Test with 100 books
    benchmark_v2(100)
    
    # Test with 1000 books
    print("\n" + "="*50)
    benchmark_v2(1000)
