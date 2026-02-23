"""
Integration test: Verify that PHP server and Python client compute identical metadata hashes.

This test uses:
- PHP: Real SyncService::computeSyncHashFromItem() via reflection
- Python: sync_utils.compute_metadata_hash() (shared with sync_worker.py)
"""
import json
import subprocess
import sys
from pathlib import Path

# Add sync_calimob to path
sync_calimob_path = Path(__file__).parent.parent.parent / 'sync_calimob'
sys.path.insert(0, str(sync_calimob_path))

# Import sync_utils (no Calibre dependencies)
import sync_utils


def compute_python_hash(json_item, format_cache, cover_hash):
    """Compute hash using REAL sync_utils code (same as sync_worker uses)."""
    import copy
    
    hash_value = sync_utils.compute_metadata_hash(json_item, format_cache, cover_hash)
    
    # Get normalized JSON for comparison
    metadata_snapshot = copy.deepcopy(json_item)
    
    for key in ('id', 'last_modified', 'version', 'last_modified_server', 'calibre_book_id'):
        metadata_snapshot.pop(key, None)
    metadata_snapshot.pop('files', None)
    metadata_snapshot.pop('timestamps', None)
    metadata_snapshot.pop('payload', None)
    
    for key in ('author_sort', 'title_sort', 'content_language', 'edition', 'extra',
               'favorite', 'progress_percent', 'status', 'source'):
        metadata_snapshot.pop(key, None)
    
    metadata_snapshot.pop('cover', None)
    
    metadata_snapshot['authors'] = sync_utils.sanitize_person_list(metadata_snapshot.get('authors'))
    
    series = metadata_snapshot.get('series')
    if series:
        metadata_snapshot['series'] = sync_utils.sanitize_series(series)
    elif series is None:
        metadata_snapshot.pop('series_index', None)
    
    metadata_snapshot['tags'] = sync_utils.sanitize_tags(metadata_snapshot.get('tags', []))
    metadata_snapshot['identifiers'] = sync_utils.sanitize_identifiers(metadata_snapshot.get('identifiers'))
    metadata_snapshot['languages'] = sync_utils.normalize_string_list(metadata_snapshot.get('languages', []))
    
    payload = {'metadata': metadata_snapshot}
    normalized = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
    normalized = normalized.replace(' ', '')
    
    return normalized, hash_value


def compute_python_hash_OLD(json_item, format_cache, cover_hash):
    """
    OLD standalone version - kept for reference.
    Compute metadata hash using Python client logic (standalone version).
    Extracted from sync_worker.py to avoid Calibre dependencies.
    """
    import hashlib
    import copy
    try:
        metadata_snapshot = copy.deepcopy(json_item)
        
        # Exclude fields
        for key in ('id', 'last_modified', 'version', 'last_modified_server', 'calibre_book_id'):
            metadata_snapshot.pop(key, None)
        metadata_snapshot.pop('files', None)
        metadata_snapshot.pop('timestamps', None)
        metadata_snapshot.pop('payload', None)
        
        # Exclude client-only fields
        for key in ('author_sort', 'title_sort', 'content_language', 'edition', 'extra',
                   'favorite', 'progress_percent', 'status', 'source'):
            metadata_snapshot.pop(key, None)
        
        # Exclude cover
        metadata_snapshot.pop('cover', None)
        
        # Sanitize authors
        authors = metadata_snapshot.get('authors', [])
        normalized_authors = []
        if isinstance(authors, list):
            for author in authors:
                if isinstance(author, dict):
                    entry = {}
                    if 'name' in author:
                        entry['name'] = author['name']
                    if 'role' in author:
                        entry['role'] = author['role']
                    if 'position' in author:
                        entry['position'] = author['position']
                    if entry:
                        normalized_authors.append(entry)
        metadata_snapshot['authors'] = normalized_authors
        
        # Sanitize series
        series = metadata_snapshot.get('series')
        if series and isinstance(series, dict):
            metadata_snapshot['series'] = {
                'name': series.get('name'),
                'series_index': series.get('series_index', series.get('index')),
            }
        elif series is None:
            metadata_snapshot.pop('series_index', None)
        
        # Sanitize tags
        tags = metadata_snapshot.get('tags', [])
        if isinstance(tags, list):
            normalized_tags = []
            for tag in tags:
                if isinstance(tag, dict):
                    name = tag.get('name')
                    if name:
                        normalized_tags.append({'name': name})
                elif tag:
                    normalized_tags.append({'name': str(tag)})
            normalized_tags.sort(key=lambda x: x.get('name') or '')
            metadata_snapshot['tags'] = normalized_tags
        
        # Sanitize identifiers
        identifiers = metadata_snapshot.get('identifiers', {})
        normalized_identifiers = {}
        if isinstance(identifiers, dict):
            for key, value in identifiers.items():
                if key and value not in (None, ''):
                    normalized_identifiers[str(key).lower()] = str(value)
        metadata_snapshot['identifiers'] = dict(sorted(normalized_identifiers.items())) if normalized_identifiers else {}
        
        # Sanitize languages
        languages = metadata_snapshot.get('languages', [])
        if isinstance(languages, list):
            normalized_languages = [str(v) for v in languages if v]
            normalized_languages.sort()
            metadata_snapshot['languages'] = normalized_languages
        
        payload = {'metadata': metadata_snapshot}
        
        # JSON encode with same settings as client
        normalized = json.dumps(payload, sort_keys=True, separators=(',', ':'), default=str)
        
        # Remove ALL spaces
        normalized = normalized.replace(' ', '')
        
        return normalized, hashlib.sha256(normalized.encode('utf-8')).hexdigest()
    except Exception as e:
        print(f"Python hash error: {e}")
        return None


def compute_php_hash(metadata_item):
    """Call PHP script to compute hash using PRODUCTION MetadataHasher (no duplication)."""
    base_dir = Path(__file__).parent.parent.parent
    php_script = f"""<?php
require_once '{base_dir}/html/vendor/autoload.php';

use App\\Services\\Sync\\MetadataHasher;

$input = json_decode(file_get_contents('php://stdin'), true);

// Use PRODUCTION code directly (standalone, no dependencies)
$hash = MetadataHasher::computeHash($input);

echo json_encode(['hash' => $hash, 'normalized' => '']);
"""
    
    php_file = Path('/tmp/test_hash_server.php')
    php_file.write_text(php_script)
    
    result = subprocess.run(
        ['php', str(php_file)],
        input=json.dumps(metadata_item),
        capture_output=True,
        text=True,
    )
    
    if result.returncode != 0:
        raise RuntimeError(f"PHP script failed: {result.stderr}")
    
    if result.stderr:
        print(result.stderr, end='')
    
    response = json.loads(result.stdout)
    return response['normalized'], response['hash']


# Test cases with different metadata scenarios
TEST_CASES = [
    {
        'name': 'minimal_book_empty_identifiers',
        'json_item': {
            'uuid': '12e64593-ad21-492f-9534-26ede83bd4fb',
            'title': 'Minimal Book',
            'authors': [
                {'name': 'Dan Simmons', 'role': 'author', 'position': 0},
            ],
            'series': None,
            'identifiers': {},
            'publisher': None,
            'pubdate': 1722722400,
            'languages': [],
            'tags': [],
            'rating': 0,
            'comments': None,
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'book_with_rating_none',
        'json_item': {
            'uuid': '22e64593-ad21-492f-9534-26ede83bd4fc',
            'title': 'Book with No Rating',
            'authors': [
                {'name': 'Test Author', 'role': 'author', 'position': 0},
            ],
            'series': None,
            'identifiers': {},
            'publisher': None,
            'pubdate': 1722722400,
            'languages': [],
            'tags': [],
            'rating': None,  # ← Critical: None should stay None, not become 0
            'comments': None,
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'book_with_identifiers',
        'json_item': {
            'uuid': 'a1b2c3d4-e5f6-7890-abcd-ef1234567890',
            'title': 'Book with ISBN',
            'authors': [
                {'name': 'John Doe', 'role': 'author', 'position': 0},
            ],
            'series': None,
            'identifiers': {'isbn': '978-0-123456-78-9', 'goodreads': '12345'},
            'publisher': 'Test Publisher',
            'pubdate': 1609459200,
            'languages': ['eng'],
            'tags': [{'name': 'Fiction'}, {'name': 'Sci-Fi'}],
            'rating': 4,
            'comments': 'A great book',
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'book_with_series',
        'json_item': {
            'uuid': 'b2c3d4e5-f6a7-8901-bcde-f12345678901',
            'title': 'Book in Series',
            'authors': [
                {'name': 'Jane Smith', 'role': 'author', 'position': 0},
                {'name': 'Bob Johnson', 'role': 'author', 'position': 1},
            ],
            'series': {'name': 'The Great Series', 'series_index': 2.0},
            'identifiers': {},
            'publisher': None,
            'pubdate': None,
            'languages': [],
            'tags': [],
            'rating': 0,
            'comments': None,
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'book_with_multiple_languages',
        'json_item': {
            'uuid': 'c3d4e5f6-a7b8-9012-cdef-123456789012',
            'title': 'Multilingual Book',
            'authors': [
                {'name': 'Author Name', 'role': 'author', 'position': 0},
            ],
            'series': None,
            'identifiers': {},
            'publisher': 'International Press',
            'pubdate': 1640995200,
            'languages': ['eng', 'fra', 'deu'],
            'tags': [{'name': 'Language'}, {'name': 'Education'}],
            'rating': 5,
            'comments': 'Excellent multilingual resource',
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'book_with_special_characters',
        'json_item': {
            'uuid': 'd4e5f6a7-b8c9-0123-def1-234567890123',
            'title': 'Book with "Quotes" & Special <Characters>',
            'authors': [
                {'name': 'O\'Brien, Patrick', 'role': 'author', 'position': 0},
            ],
            'series': None,
            'identifiers': {'isbn': '978-1-234-56789-0'},
            'publisher': 'Test & Co.',
            'pubdate': 1577836800,
            'languages': ['eng'],
            'tags': [{'name': 'Fiction & Fantasy'}, {'name': 'Sci-Fi/Horror'}],
            'rating': 3,
            'comments': 'Contains special chars: <>&"\' and unicode: café, naïve, 日本語',
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'book_with_empty_arrays',
        'json_item': {
            'uuid': 'e5f6a7b8-c9d0-1234-ef12-345678901234',
            'title': 'Empty Arrays Book',
            'authors': [],
            'series': None,
            'identifiers': {},
            'publisher': None,
            'pubdate': None,
            'languages': [],
            'tags': [],
            'rating': 0,
            'comments': None,
        },
        'format_cache': {},
        'cover_hash': None,
    },
]


def test_hash_consistency():
    """Test that PHP and Python compute identical hashes for all test cases."""
    results = []
    
    for test_case in TEST_CASES:
        name = test_case['name']
        json_item = test_case['json_item']
        format_cache = test_case['format_cache']
        cover_hash = test_case['cover_hash']
        
        print(f"\n{'='*60}")
        print(f"Test: {name}")
        print(f"{'='*60}")
        
        # Compute Python hash
        python_normalized, python_hash = compute_python_hash(json_item, format_cache, cover_hash)
        print(f"Python hash: {python_hash}")
        
        # Compute PHP hash
        php_normalized, php_hash = compute_php_hash(json_item)
        print(f"PHP hash:    {php_hash}")
        
        # Compare hashes
        hash_match = python_hash == php_hash
        
        # Compare normalized JSON
        json_match = python_normalized == php_normalized
        
        status = "✅ PASS" if hash_match else "❌ FAIL"
        print(f"Result: {status}")
        
        # Show diff if failed
        if not hash_match:
            print(f"\n  JSON match: {'✅' if json_match else '❌'}")
            if not json_match:
                print(f"  Python JSON: {python_normalized[:150]}...")
                print(f"  PHP JSON:    {php_normalized[:150]}...")
                
                # Find first difference
                for i, (p, h) in enumerate(zip(python_normalized, php_normalized)):
                    if p != h:
                        start = max(0, i - 20)
                        end = min(len(python_normalized), i + 20)
                        print(f"  First diff at position {i}:")
                        print(f"    Python: ...{python_normalized[start:end]}...")
                        print(f"    PHP:    ...{php_normalized[start:end]}...")
                        break
        
        results.append({
            'name': name,
            'python_hash': python_hash,
            'php_hash': php_hash,
            'python_json': python_normalized,
            'php_json': php_normalized,
            'hash_match': hash_match,
            'json_match': json_match,
        })
    
    # Summary
    print(f"\n{'='*60}")
    print("SUMMARY")
    print(f"{'='*60}")
    
    passed = sum(1 for r in results if r['hash_match'])
    total = len(results)
    
    for result in results:
        status = "✅" if result['hash_match'] else "❌"
        print(f"{status} {result['name']}")
    
    print(f"\nPassed: {passed}/{total}")
    
    # Assert all passed
    failed = [r for r in results if not r['hash_match']]
    if failed:
        print("\n❌ FAILED TESTS:")
        for r in failed:
            print(f"  - {r['name']}")
            print(f"    Python hash: {r['python_hash']}")
            print(f"    PHP hash:    {r['php_hash']}")
            if not r['json_match']:
                print(f"    JSON mismatch detected")
        raise AssertionError(f"{len(failed)} test(s) failed")
    
    print("\n✅ All tests passed!")


if __name__ == '__main__':
    test_hash_consistency()
