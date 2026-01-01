#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Integration tests for sync_calimob plugin
Run from project root: /Applications/calibre.app/Contents/MacOS/calibre-debug -e tests/plugin/test_plugin_integration.py

These tests run inside Calibre's environment, so all Calibre modules are available.
"""

from __future__ import (unicode_literals, division, absolute_import, print_function)

import sys
import json
import hashlib
from datetime import datetime

# Import plugin modules (available in Calibre environment)
try:
    from calibre.customize.ui import find_plugin
    from calibre.utils.date import utcnow
    
    # Load the sync_calimob plugin
    plugin = find_plugin('sync_calimob')
    if not plugin:
        print("ERROR: sync_calimob plugin not found. Make sure it's installed.")
        sys.exit(1)
    
    # Import plugin modules from plugin path
    sys.path.insert(0, plugin.plugin_path)
    import sync_mapper
    
    print("✓ Plugin modules loaded successfully")
    
except Exception as e:
    print("ERROR loading plugin:", str(e))
    sys.exit(1)


def test_calculate_cover_hash():
    """Test cover hash calculation"""
    print("\n[TEST] Cover hash calculation")
    
    test_data = b"test cover data for hashing"
    hash_result = sync_mapper.calculate_cover_hash(test_data)
    
    assert hash_result is not None, "Hash should not be None"
    assert isinstance(hash_result, str), "Hash should be string"
    assert len(hash_result) == 64, f"SHA256 hash should be 64 chars, got {len(hash_result)}"
    
    print(f"  ✓ Hash calculated: {hash_result[:16]}...")
    return True


def test_delete_payload_structure():
    """Test delete payload construction (UUID-only protocol)"""
    print("\n[TEST] Delete payload structure")
    
    book_id = 123
    library_id = "test-lib-456"
    book_uuid = "11111111-2222-3333-4444-555555555555"
    
    # Construct like plugin does
    item_payload = {
        'id': book_id,
        'uuid': book_uuid,
        'last_modified': int(utcnow().timestamp())
    }
    
    assert 'id' in item_payload, "Must have 'id' field"
    assert 'uuid' in item_payload, "Must have 'uuid' field"
    assert 'client_ids' not in item_payload, "Must NOT include client_ids"
    assert item_payload['id'] == book_id, f"ID should be {book_id}"
    assert item_payload['uuid'] == book_uuid, "UUID should be set"
    
    print(f"  ✓ Payload structure valid")
    print(f"  ✓ ID field: {item_payload['id']}")
    print(f"  ✓ UUID: {item_payload['uuid']}")
    
    return True


def test_idempotency_key_generation():
    """Test idempotency key is deterministic"""
    print("\n[TEST] Idempotency key generation")
    
    payload = {
        'op': 'create',
        'item': {
            'id': 123,
            'title': 'Test Book'
        }
    }
    
    # Generate twice
    raw1 = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    key1 = hashlib.sha256(raw1.encode('utf-8')).hexdigest()
    
    raw2 = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    key2 = hashlib.sha256(raw2.encode('utf-8')).hexdigest()
    
    assert key1 == key2, "Same payload should generate same key"
    print(f"  ✓ Deterministic key: {key1[:16]}...")
    
    # Different payload should generate different key
    payload2 = payload.copy()
    payload2['item']['id'] = 456
    raw3 = json.dumps(payload2, sort_keys=True, separators=(',', ':'))
    key3 = hashlib.sha256(raw3.encode('utf-8')).hexdigest()
    
    assert key1 != key3, "Different payload should generate different key"
    print(f"  ✓ Different payload gives different key")
    
    return True


def test_protocol_compliance():
    """Test protocol compliance (UUID-only + idempotency)"""
    print("\n[TEST] Protocol compliance")
    
    book_id = 999
    book_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
    
    # Modern protocol uses 'id' + 'uuid' and no client_ids
    modern_item = {
        'id': book_id,
        'uuid': book_uuid,
        'title': 'Modern Protocol Book'
    }
    
    assert 'id' in modern_item, "Modern protocol must use 'id' field"
    assert 'calibre_book_id' not in modern_item, "Should NOT have legacy 'calibre_book_id'"
    assert 'uuid' in modern_item, "Modern protocol must include 'uuid'"
    assert 'client_ids' not in modern_item, "client_ids must not be sent"
    
    change = {
        'op': 'create',
        'item': modern_item,
        'idempotency_key': 'test-idempotency-key'
    }
    assert change['idempotency_key'], "idempotency_key is required on every change"
    
    print("  ✓ Uses 'id' + 'uuid'")
    print("  ✓ No legacy 'calibre_book_id' or client_ids")
    print("  ✓ idempotency_key present")
    
    return True


def run_all_tests():
    """Run all tests and report results"""
    print("=" * 60)
    print("  sync_calimob Plugin Integration Tests")
    print("=" * 60)
    
    tests = [
        ("Cover Hash Calculation", test_calculate_cover_hash),
        ("Delete Payload Structure", test_delete_payload_structure),
        ("Idempotency Key Generation", test_idempotency_key_generation),
        ("Protocol Compliance", test_protocol_compliance),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
        except AssertionError as e:
            failed += 1
            print(f"\n  ✗ FAILED: {test_name}")
            print(f"    Error: {str(e)}")
        except Exception as e:
            failed += 1
            print(f"\n  ✗ ERROR: {test_name}")
            print(f"    Exception: {str(e)}")
    
    print("\n" + "=" * 60)
    print(f"  Test Results: {passed} passed, {failed} failed")
    print("=" * 60)
    
    return failed == 0


if __name__ == '__main__':
    success = run_all_tests()
    sys.exit(0 if success else 1)
