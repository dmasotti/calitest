"""
Integration test: Verify that PHP server and Python client compute identical metadata hashes.

This test uses:
- PHP: Real SyncService::computeSyncHashFromItem() via reflection
- Python: sync_utils.compute_metadata_hash() (shared with sync_worker.py)
"""
import json
import subprocess
import sys
import re
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
    
    # PHP startup warnings (e.g. missing xdebug) can be printed before JSON.
    # Parse the last JSON object found in stdout.
    stdout = result.stdout or ''
    matches = re.findall(r'\{.*\}', stdout, flags=re.DOTALL)
    if not matches:
        raise RuntimeError(f"PHP output did not contain JSON. stdout={stdout!r} stderr={result.stderr!r}")

    response = json.loads(matches[-1])
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
        'name': 'dirty_input_unsorted_arrays_and_client_only_fields',
        'json_item': {
            'uuid': 'f6a7b8c9-d0e1-2345-f123-456789012345',
            'title': 'Dirty Input',
            'title_sort': 'Dirty Input Sorted',
            'author_sort': 'Zeta, Alice & Alpha, Bob',
            'authors': [
                {'name': 'Zeta, Alice', 'role': 'editor', 'position': 2, 'id': 999, 'client_ids': ['x']},
                {'name': 'Alpha, Bob', 'role': 'author', 'position': 0, 'link': 'ignored'},
            ],
            'series': None,
            'identifiers': {'ISBN': '9780000000001', 'GoodReads': 'abc123'},
            'publisher': 'Dirty Publisher',
            'pubdate': 1700000000,
            'languages': ['ita', 'eng', 'deu'],
            'tags': [
                {'name': 'z-tag', 'id': 10},
                {'name': 'a-tag', 'link': 'ignored'},
            ],
            'rating': 1,
            'comments': 'dirty comments',
            'favorite': True,
            'status': 'reading',
            'source': 'client',
            'progress_percent': 42.5,
            'edition': 'first',
            'content_language': 'it',
            'extra': {'foo': 'bar'},
            'cover': '/tmp/path.jpg',
            'files': [{'format': 'EPUB', 'hash': 'sha256:deadbeef'}],
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'dirty_input_mixed_authors_tags_and_unsorted_languages',
        'json_item': {
            'uuid': '07b8c9d0-e1f2-3456-0123-567890123456',
            'title': 'Dirty Mixed Arrays',
            'authors': [
                {'name': 'Gamma'},
                {'name': 'Beta', 'position': 5},
                {'name': 'Alpha', 'role': 'author'},
            ],
            'series': {'name': 'S', 'index': 3},
            'identifiers': {'z-id': 'z', 'a-id': 'a', '': 'ignored', 'nullish': ''},
            'publisher': None,
            'pubdate': None,
            'languages': ['zzz', 'aaa', 'mmm', None],
            'tags': [
                {'name': 'z'},
                {'name': 'a'},
                {'name': 'm'},
            ],
            'rating': None,
            'comments': None,
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'log_case_deep_learning_rich_metadata',
        'json_item': {
            'uuid': 'db8dccdf-e56b-4bec-88a8-0fbc086e492b',
            'title': 'Deep Learning',
            'title_sort': 'Deep Learning',
            'author_sort': 'Goodfellow, Ian & Bengio, Yoshua & Courville, Aaron',
            'authors': [
                {'name': 'Dave Louapre', 'role': 'author', 'position': 0},
                {'name': 'Ian Goodfellow', 'role': 'author', 'position': 6},
                {'name': 'Yoshua Bengio', 'role': 'author', 'position': 7},
                {'name': 'Aaron Courville', 'role': 'author', 'position': 8},
            ],
            'series': {'name': 'serie1', 'series_index': 1.0},
            'identifiers': {
                'e2e_local_id': 'E2E-LOCAL-1771794679',
                'e2e_server_id': 'E2E-SERVER-1771794478',
                'goodreads': '30422361',
                'google': 'Np9SDQAAQBAJ',
                'isbn': '9780262035613',
                'testid': 'IT-E2E-1771791622',
            },
            'publisher': 'Scholastic Press',
            'pubdate': 1420066800,
            'languages': ['eng', 'por', 'ara'],
            'tags': [
                {'name': 'alien invasion'},
                {'name': 'dystopian'},
                {'name': 'Artificial Intelligence'},
            ],
            'rating': None,
            'comments': '<div><p>from log sample</p></div>',
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'log_case_string_theory_unicode_tags',
        'json_item': {
            'uuid': '66fb9f9f-3d09-4a56-b800-1ea4068e93a0',
            'title': 'String Theory',
            'title_sort': 'String Theory',
            'author_sort': 'Polchinski, Joseph',
            'authors': [
                {'name': 'Disney', 'role': 'author', 'position': 0},
                {'name': 'Joseph Polchinski', 'role': 'author', 'position': 3},
            ],
            'series': None,
            'identifiers': {'isbn': '9780521633031', 'amazon': '0521633125', 'google': '54DGYyNAjacC'},
            'publisher': 'Cambridge University Press',
            'pubdate': 909518400,
            'languages': ['eng'],
            'tags': [
                {'name': 'Fiction'},
                {'name': 'Juvenile Fiction'},
                {'name': 'Fiction teeee'},
                {'name': 'ma esiste un lungo elenco di coloro che hanno sedotto spiegando quello che si stava per mangiare"... Manuel Vázquez Montalbán'},
            ],
            'rating': None,
            'comments': None,
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'identifiers_as_list_entries',
        'json_item': {
            'uuid': '11111111-2222-3333-4444-555555555555',
            'title': 'Identifier List Form',
            'authors': [{'name': 'Author One', 'role': 'author', 'position': 0}],
            'series': None,
            'identifiers': [
                {'type': 'ISBN', 'value': '9780000000003'},
                {'scheme': 'goodreads', 'val': '999'},
            ],
            'publisher': None,
            'pubdate': None,
            'languages': ['eng'],
            'tags': [{'name': 't1'}],
            'rating': None,
            'comments': None,
        },
        'format_cache': {},
        'cover_hash': None,
    },
    {
        'name': 'identifiers_empty_list_vs_empty_map_shape',
        'json_item': {
            'uuid': '22222222-3333-4444-5555-666666666666',
            'title': 'Identifier Empty List',
            'title_sort': 'Identifier Empty List',
            'author_sort': 'One, Author',
            'authors': [{'name': 'Author One', 'role': 'editor', 'position': 9}],
            'series': None,
            'identifiers': [],
            'publisher': None,
            'pubdate': None,
            'languages': [],
            'tags': [],
            'rating': None,
            'comments': None,
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

EQUIVALENT_CASES = [
    {
        'name': 'equivalent_authors_tags_order_and_client_fields_ignored',
        'canonical': {
            'uuid': '77777777-7777-7777-7777-777777777777',
            'title': 'Equivalent Book',
            'authors': [
                {'name': 'A Author', 'role': 'author', 'position': 0},
                {'name': 'B Author', 'role': 'author', 'position': 1},
            ],
            'series': None,
            'identifiers': {'isbn': '9780000000002'},
            'publisher': 'Publisher',
            'pubdate': 1710000000,
            'languages': ['eng', 'ita'],
            'tags': [{'name': 'alpha'}, {'name': 'beta'}],
            'rating': 4,
            'comments': 'Same semantic content',
        },
        'dirty': {
            'uuid': '77777777-7777-7777-7777-777777777777',
            'title': 'Equivalent Book',
            'title_sort': 'Equivalent Book',
            'author_sort': 'B Author & A Author',
            'authors': [
                {'name': 'B Author', 'role': 'author', 'position': 1, 'id': 2, 'link': 'x'},
                {'name': 'A Author', 'role': 'author', 'position': 0, 'client_ids': ['y']},
            ],
            'series': None,
            'identifiers': {'ISBN': '9780000000002'},
            'publisher': 'Publisher',
            'pubdate': 1710000000,
            'languages': ['ita', 'eng'],
            'tags': [{'name': 'beta', 'id': 2}, {'name': 'alpha', 'link': 'x'}],
            'rating': 4,
            'comments': 'Same semantic content',
            'favorite': True,
            'status': 'reading',
            'source': 'client',
            'cover': '/tmp/ignored.jpg',
            'files': [{'format': 'EPUB', 'hash': 'sha256:ignored'}],
        },
    }
    ,
    {
        'name': 'equivalent_role_position_title_sort_author_sort_ignored',
        'canonical': {
            'uuid': '88888888-8888-8888-8888-888888888888',
            'title': 'Role Ignore',
            'authors': [
                {'name': 'A'},
                {'name': 'B'},
            ],
            'series': None,
            'identifiers': {'isbn': '9780000000004'},
            'publisher': None,
            'pubdate': None,
            'languages': ['eng', 'ita'],
            'tags': [{'name': 'x'}, {'name': 'y'}],
            'rating': None,
            'comments': None,
        },
        'dirty': {
            'uuid': '88888888-8888-8888-8888-888888888888',
            'title': 'Role Ignore',
            'title_sort': 'Role Ignore, The',
            'author_sort': 'B & A',
            'authors': [
                {'name': 'B', 'role': 'translator', 'position': 99, 'id': -1},
                {'name': 'A', 'role': 'author', 'position': 0, 'client_ids': [1, 2]},
            ],
            'series': None,
            'identifiers': {'ISBN': '9780000000004'},
            'publisher': None,
            'pubdate': None,
            'languages': ['ita', 'eng'],
            'tags': [{'name': 'y', 'id': -2}, {'name': 'x', 'link': 'ignored'}],
            'rating': 0,
            'comments': None,
            'status': 'done',
            'favorite': False,
        },
    }
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

def test_hash_equivalence_for_dirty_variants():
    """Semantically equivalent dirty payloads must produce the same hash."""
    for case in EQUIVALENT_CASES:
        canonical = case['canonical']
        dirty = case['dirty']

        _, py_hash_canonical = compute_python_hash(canonical, {}, None)
        _, py_hash_dirty = compute_python_hash(dirty, {}, None)
        if py_hash_canonical != py_hash_dirty:
            raise AssertionError(
                f"Python equivalence failed for {case['name']}: "
                f"{py_hash_canonical} != {py_hash_dirty}"
            )

        _, php_hash_canonical = compute_php_hash(canonical)
        _, php_hash_dirty = compute_php_hash(dirty)
        if php_hash_canonical != php_hash_dirty:
            raise AssertionError(
                f"PHP equivalence failed for {case['name']}: "
                f"{php_hash_canonical} != {php_hash_dirty}"
            )

        if py_hash_canonical != php_hash_canonical:
            raise AssertionError(
                f"Cross-language mismatch for {case['name']}: "
                f"python={py_hash_canonical} php={php_hash_canonical}"
            )

    print("\nAll dirty-variant equivalence checks passed.")


if __name__ == '__main__':
    test_hash_consistency()
    test_hash_equivalence_for_dirty_variants()
