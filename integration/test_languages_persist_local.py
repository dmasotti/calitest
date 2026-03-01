#!/usr/bin/env python3
"""
Local test: Verify languages persist after upsert and appear in buildItemFromUserBook response.
Tests the fix for unsetRelations() clearing cached relations.
"""

import requests
import json
import uuid

BASE_URL = "http://caliserver.test"
# Use a test token or create one via tinker
TOKEN = None  # Will get from login

def login():
    """Login and get token"""
    response = requests.post(f"{BASE_URL}/api/login", json={
        "email": "test@example.com",
        "password": "password"
    })
    if response.status_code == 200:
        return response.json()["token"]
    return None

def test_languages_persist_local():
    """Test that languages are saved and returned in response after upsert"""
    
    print("=" * 80)
    print("LOCAL TEST: Languages persist after upsert")
    print("=" * 80)
    
    # Get token
    token = login()
    if not token:
        print("❌ FAIL: Could not login")
        return False
    
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }
    
    test_uuid = str(uuid.uuid4())
    
    # Step 1: Upsert book with languages
    print(f"\n1. Upserting book {test_uuid[:8]} with languages [eng, por, ara]...")
    
    upsert_data = {
        "changes": [{
            "op": "upsert",
            "idempotency_key": f"test-{test_uuid}",
            "client_change_id": f"test-{test_uuid}",
            "item": {
                "id": 999,
                "uuid": test_uuid,
                "title": "Test Languages Persist",
                "authors": [{"name": "Test Author", "role": "author", "position": 0}],
                "languages": ["eng", "por", "ara"],  # 3 languages
                "tags": [],
                "identifiers": {},
                "publisher": None,
                "pubdate": 1234567890,
                "last_modified": 1234567890,
                "files": [],
                "cover": {"has_cover": "No"},
                "timestamps": {"created_at": 1234567890}
            }
        }],
        "options": {"dry_run": False},
        "library_id": "1",
        "calibre_library_uuid": str(uuid.uuid4())
    }
    
    response = requests.post(f"{BASE_URL}/api/sync", headers=headers, json=upsert_data)
    
    if response.status_code != 200:
        print(f"❌ FAIL: Upsert failed with status {response.status_code}")
        print(f"Response: {response.text}")
        return False
    
    result = response.json()
    
    if not result.get("results") or len(result["results"]) == 0:
        print(f"❌ FAIL: No results in response")
        return False
    
    server_item = result["results"][0].get("server_item", {})
    response_languages = server_item.get("languages", [])
    
    print(f"✓ Upsert successful")
    print(f"  Response languages: {response_languages}")
    
    # Step 2: Verify languages in response
    expected = {"ara", "eng", "por"}  # Sorted
    actual = set(response_languages)
    
    if actual != expected:
        print(f"❌ FAIL: Languages mismatch!")
        print(f"  Expected: {expected}")
        print(f"  Got: {actual}")
        return False
    
    print(f"✓ Languages correct in response")
    
    # Cleanup
    print(f"\n2. Cleaning up...")
    requests.delete(f"{BASE_URL}/api/books/{test_uuid}", headers=headers)
    
    print("\n" + "=" * 80)
    print("✅ TEST PASSED")
    print("=" * 80)
    
    return True

if __name__ == "__main__":
    import sys
    success = test_languages_persist_local()
    sys.exit(0 if success else 1)
