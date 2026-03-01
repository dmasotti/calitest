#!/usr/bin/env python3
"""
Test SQLite UDF (User Defined Function) for SHA256 hash calculation.

This script tests if we can register a Python function in SQLite
to calculate SHA256 hashes directly in SQL queries, avoiding
the need to fetch data to Python and hash it there.
"""
import sqlite3
import hashlib
import time
import sys
import os

# Path to test database
TEST_DB = os.path.join(
    os.path.dirname(__file__),
    '../fixtures/databases/metadata_test.db'
)


def sha256_udf(text):
    """SHA256 hash function for SQLite."""
    if text is None:
        return None
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def test_udf_registration():
    """Test that we can register the UDF."""
    print("=" * 60)
    print("TEST 1: UDF Registration")
    print("=" * 60)
    
    conn = sqlite3.connect(TEST_DB)
    
    # Register the function
    conn.create_function("sha256", 1, sha256_udf)
    
    # Test it
    cursor = conn.cursor()
    cursor.execute("SELECT sha256('test')")
    result = cursor.fetchone()[0]
    
    expected = hashlib.sha256('test'.encode('utf-8')).hexdigest()
    
    print(f"Result:   {result}")
    print(f"Expected: {expected}")
    print(f"Match: {result == expected}")
    
    conn.close()
    
    assert result == expected, "UDF hash doesn't match Python hash!"
    print("✅ PASS: UDF registration works\n")


def test_udf_in_view():
    """Test using UDF in a VIEW."""
    print("=" * 60)
    print("TEST 2: UDF in VIEW")
    print("=" * 60)
    
    conn = sqlite3.connect(TEST_DB)
    conn.create_function("sha256", 1, sha256_udf)
    cursor = conn.cursor()
    
    # Create test VIEW with UDF
    cursor.execute("DROP VIEW IF EXISTS test_hash_view")
    cursor.execute("""
        CREATE VIEW test_hash_view AS
        SELECT 
            id,
            title,
            sha256(coalesce(title, '')) as title_hash
        FROM books
        LIMIT 10
    """)
    
    # Query the VIEW
    cursor.execute("SELECT id, title, title_hash FROM test_hash_view")
    rows = cursor.fetchall()
    
    print(f"Retrieved {len(rows)} rows from VIEW")
    
    # Verify first row
    if rows:
        book_id, title, view_hash = rows[0]
        expected_hash = hashlib.sha256((title or '').encode('utf-8')).hexdigest()
        print(f"\nFirst book:")
        print(f"  ID: {book_id}")
        print(f"  Title: {title[:50]}...")
        print(f"  VIEW hash: {view_hash[:16]}...")
        print(f"  Expected:  {expected_hash[:16]}...")
        print(f"  Match: {view_hash == expected_hash}")
        
        assert view_hash == expected_hash, "VIEW hash doesn't match!"
    
    # Cleanup
    cursor.execute("DROP VIEW test_hash_view")
    conn.close()
    
    print("✅ PASS: UDF works in VIEW\n")


def benchmark_with_udf():
    """Benchmark: Calculate hashes in SQL with UDF."""
    print("=" * 60)
    print("BENCHMARK 1: Hash Calculation WITH UDF (in SQL)")
    print("=" * 60)
    
    conn = sqlite3.connect(TEST_DB)
    conn.create_function("sha256", 1, sha256_udf)
    cursor = conn.cursor()
    
    # Create VIEW with UDF
    cursor.execute("DROP VIEW IF EXISTS bench_hash_view")
    cursor.execute("""
        CREATE VIEW bench_hash_view AS
        SELECT 
            id,
            sha256(
                coalesce(title, '') || '|' ||
                coalesce(author_sort, '') || '|' ||
                coalesce(path, '')
            ) as metadata_hash
        FROM books
    """)
    
    # Benchmark: Query all hashes
    start = time.time()
    cursor.execute("SELECT COUNT(*), COUNT(metadata_hash) FROM bench_hash_view")
    total, hashed = cursor.fetchone()
    elapsed = time.time() - start
    
    print(f"Total books: {total}")
    print(f"Hashed: {hashed}")
    print(f"Time: {elapsed:.3f}s")
    print(f"Per book: {(elapsed / total * 1000):.2f}ms")
    
    # Cleanup
    cursor.execute("DROP VIEW bench_hash_view")
    conn.close()
    
    print("✅ DONE\n")
    return elapsed, total


def benchmark_without_udf():
    """Benchmark: Calculate hashes in Python (current approach)."""
    print("=" * 60)
    print("BENCHMARK 2: Hash Calculation WITHOUT UDF (in Python)")
    print("=" * 60)
    
    conn = sqlite3.connect(TEST_DB)
    cursor = conn.cursor()
    
    # Query payloads (no hash)
    start = time.time()
    cursor.execute("""
        SELECT 
            id,
            coalesce(title, '') || '|' ||
            coalesce(author_sort, '') || '|' ||
            coalesce(path, '') as payload
        FROM books
    """)
    
    # Calculate hashes in Python
    count = 0
    for row in cursor:
        book_id, payload = row
        hash_value = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        count += 1
    
    elapsed = time.time() - start
    
    print(f"Total books: {count}")
    print(f"Time: {elapsed:.3f}s")
    print(f"Per book: {(elapsed / count * 1000):.2f}ms")
    
    conn.close()
    
    print("✅ DONE\n")
    return elapsed, count


def test_library_hash_with_udf():
    """Test library-level hash calculation with UDF."""
    print("=" * 60)
    print("TEST 3: Library Hash with UDF")
    print("=" * 60)
    
    conn = sqlite3.connect(TEST_DB)
    conn.create_function("sha256", 1, sha256_udf)
    cursor = conn.cursor()
    
    # Check if calimob_books_sync exists
    cursor.execute("""
        SELECT COUNT(*) FROM sqlite_master 
        WHERE type='table' AND name='calimob_books_sync'
    """)
    
    if cursor.fetchone()[0] == 0:
        print("⚠️  calimob_books_sync table doesn't exist, skipping")
        conn.close()
        return
    
    # Create VIEW with UDF for library hash
    cursor.execute("DROP VIEW IF EXISTS test_library_hash")
    cursor.execute("""
        CREATE VIEW test_library_hash AS
        SELECT 
            cbs.library_uuid,
            COUNT(*) as total_books,
            sha256(group_concat(
                sha256(
                    coalesce(b.uuid, '') || '|' ||
                    coalesce(b.title, '') || '|' ||
                    coalesce(b.author_sort, '')
                ), ''
            )) as library_hash
        FROM books b
        JOIN calimob_books_sync cbs ON b.id = cbs.calibre_book_id
        GROUP BY cbs.library_uuid
    """)
    
    # Query library hash
    start = time.time()
    cursor.execute("SELECT library_uuid, total_books, library_hash FROM test_library_hash")
    rows = cursor.fetchall()
    elapsed = time.time() - start
    
    print(f"Libraries: {len(rows)}")
    print(f"Time: {elapsed * 1000:.2f}ms")
    
    for library_uuid, total, lib_hash in rows:
        print(f"\nLibrary: {library_uuid}")
        print(f"  Books: {total}")
        print(f"  Hash: {lib_hash[:32]}...")
    
    # Cleanup
    cursor.execute("DROP VIEW test_library_hash")
    conn.close()
    
    print("✅ PASS: Library hash with UDF works\n")


def main():
    """Run all tests."""
    print("\n" + "=" * 60)
    print("SQLite UDF SHA256 Tests")
    print("=" * 60)
    print(f"Database: {TEST_DB}")
    print(f"Size: {os.path.getsize(TEST_DB) / 1024 / 1024:.1f} MB")
    print("=" * 60 + "\n")
    
    try:
        # Functional tests
        test_udf_registration()
        test_udf_in_view()
        test_library_hash_with_udf()
        
        # Benchmarks
        time_with_udf, count_with = benchmark_with_udf()
        time_without_udf, count_without = benchmark_without_udf()
        
        # Summary
        print("=" * 60)
        print("SUMMARY")
        print("=" * 60)
        print(f"Books tested: {count_with}")
        print(f"\nWITH UDF (SQL):    {time_with_udf:.3f}s ({time_with_udf/count_with*1000:.2f}ms/book)")
        print(f"WITHOUT UDF (Py):  {time_without_udf:.3f}s ({time_without_udf/count_without*1000:.2f}ms/book)")
        
        if time_without_udf > time_with_udf:
            speedup = time_without_udf / time_with_udf
            print(f"\n🚀 UDF is {speedup:.1f}x FASTER")
        else:
            slowdown = time_with_udf / time_without_udf
            print(f"\n⚠️  UDF is {slowdown:.1f}x SLOWER")
        
        print("\n✅ ALL TESTS PASSED")
        
    except Exception as e:
        print(f"\n❌ TEST FAILED: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == '__main__':
    main()
