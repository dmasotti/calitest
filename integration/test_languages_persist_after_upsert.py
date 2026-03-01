#!/usr/bin/env python3
"""
Test that languages are persisted correctly after upsert and appear in response.
This test verifies the fix for the sync loop caused by languages being empty after upsert.
"""

import os
import sys
import requests
import json

import uuid

# Add project root to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

BASE_URL = "https://coral-shark-984693.hostingersite.com"
TOKEN = "44|jHjh0i1wsHYoPpSz2m7gRoUmWhtd7E2K5SiN1MEt984e5f11"
LIBRARY_ID = 8
TEST_UUID = str(uuid.uuid4())

def api_call(method, endpoint, data=None):
    """Make API call with authentication"""
    headers = {
        "Authorization": f"Bearer {TOKEN}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    url = f"{BASE_URL}{endpoint}"
    
    if method == "GET":
        response = requests.get(url, headers=headers)
    elif method == "POST":
        response = requests.post(url, headers=headers, json=data)
    elif method == "DELETE":
        response = requests.delete(url, headers=headers)
    else:
        raise ValueError(f"Unsupported method: {method}")
    
    return response

def test_languages_persist():
    """Test that languages are saved and returned correctly after upsert"""
    
    print("=" * 80)
    print("TEST: Languages persist after upsert")
    print("=" * 80)
    
    # Step 1: Create book with languages via upsert
    print("\n1. Creating book with languages [eng, por, ara]...")
    
    upsert_data = {
        "changes": [{
            "op": "upsert",
            "idempotency_key": f"test-{TEST_UUID}",
            "client_change_id": f"test-{TEST_UUID}",
            "item": {
                "id": 999,
                "uuid": TEST_UUID,
                "title": "Test Book Languages",
                "title_sort": "Test Book Languages",
                "author_sort": "Test Author",
                "authors": [{"name": "Test Author", "role": "author", "position": 0}],
                "series": None,
                "identifiers": {},
                "publisher": None,
                "pubdate": 1234567890,
                "languages": ["eng", "por", "ara"],  # 3 languages
                "tags": [],
                "status": None,
                "rating": None,
                "comments": None,
                "edition": None,
                "content_language": None,
                "files": [],
                "cover": {"has_cover": "No", "cover_hash": None, "cover_url": None},
                "timestamps": {"created_at": 1234567890, "deleted_at": None},
                "last_modified": 1234567890,
                "source": {"client": "test", "client_library": "test"},
                "extra": {},
                "progress_percent": None,
                "favorite": False,
                "metadata_hash": "test123"
            }
        }],
        "options": {"dry_run": False},
        "library_id": str(LIBRARY_ID),
        "calibre_library_uuid": "265073ef-4e7e-4253-8bdb-bc17a8763c7d"
    }
    
    response = api_call("POST", "/api/sync", upsert_data)
    
    if response.status_code != 200:
        print(f"❌ FAIL: Upsert failed with status {response.status_code}")
        print(f"Response: {response.text}")
        return False
    
    result = response.json()
    server_item = result["results"][0]["server_item"]
    
    print(f"✓ Upsert successful")
    print(f"  Server returned languages: {server_item.get('languages', [])}")
    
    # Step 2: Query database to check if languages were saved
    print("\n2. Checking database for saved languages...")
    
    sql_query = {
        "q": f"SELECT l.lang_code FROM books_languages_link link JOIN books_languages l ON link.lang_code = l.id WHERE link.book = '{TEST_UUID}' AND link.library_id = {LIBRARY_ID}"
    }
    
    response = api_call("POST", "/api/tools/sql", sql_query)
    
    if response.status_code != 200:
        print(f"❌ FAIL: SQL query failed with status {response.status_code}")
        return False
    
    sql_result = response.json()
    db_languages = [row["lang_code"] for row in sql_result.get("rows", [])]
    
    print(f"  Database has languages: {db_languages}")
    
    # Step 3: Verify languages match
    expected_languages = {"eng", "por", "ara"}
    actual_languages = set(db_languages)
    
    if actual_languages != expected_languages:
        print(f"❌ FAIL: Languages mismatch!")
        print(f"  Expected: {expected_languages}")
        print(f"  Got: {actual_languages}")
        success = False
    else:
        print(f"✓ Languages saved correctly in database")
        success = True
    
    # Step 4: Check if response languages match database
    response_languages = set(server_item.get("languages", []))
    
    if response_languages != actual_languages:
        print(f"❌ FAIL: Response languages don't match database!")
        print(f"  Response: {response_languages}")
        print(f"  Database: {actual_languages}")
        success = False
    else:
        print(f"✓ Response languages match database")
    
    # Cleanup
    print("\n3. Cleaning up test book...")
    api_call("POST", "/api/tools/sql", {
        "q": f"DELETE FROM books WHERE uuid = '{TEST_UUID}' AND library_id = {LIBRARY_ID}"
    })
    api_call("POST", "/api/tools/sql", {
        "q": f"DELETE FROM books_languages_link WHERE book = '{TEST_UUID}' AND library_id = {LIBRARY_ID}"
    })
    
    print("\n" + "=" * 80)
    if success:
        print("✅ TEST PASSED")
    else:
        print("❌ TEST FAILED")
    print("=" * 80)
    
    return success

if __name__ == "__main__":
    success = test_languages_persist()
    sys.exit(0 if success else 1)
