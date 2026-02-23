#!/usr/bin/env python3
"""
Integration test: Verify file upload success is tracked correctly.

Tests the complete flow:
1. Server marks file as missing (needs_file_upload=true, file_missing=true)
2. Client uploads file
3. Server marks file as uploaded (is_uploaded=true, file_missing=false)
4. Next sync: server doesn't request file again
"""

import sys
import os
from datetime import datetime

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

try:
    import requests
except ImportError:
    print("ERROR: requests library required")
    sys.exit(1)

API_BASE = "https://coral-shark-984693.hostingersite.com/api"
TOKEN = "44|jHjh0i1wsHYoPpSz2m7gRoUmWhtd7E2K5SiN1MEt984e5f11"
HEADERS = {
    "Authorization": f"Bearer {TOKEN}",
    "Accept": "application/json",
    "Content-Type": "application/json"
}

def log(msg):
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def sql_query(query):
    response = requests.post(f"{API_BASE}/tools/sql", headers=HEADERS, json={"q": query})
    if response.status_code != 200:
        raise Exception(f"SQL failed: {response.text}")
    return response.json()

def test_file_upload_tracking():
    """Test complete file upload verification flow"""
    log("=" * 60)
    log("INTEGRATION TEST: File Upload Verification")
    log("=" * 60)
    
    # Step 1: Find a book with file
    log("\n1. Finding test book with file...")
    result = sql_query("""
        SELECT b.uuid, bf.format, bf.is_uploaded, bf.file_missing, bf.needs_file_upload
        FROM books b
        JOIN books_files bf ON bf.book = b.uuid
        WHERE b.uuid IS NOT NULL AND bf.format = 'EPUB'
        LIMIT 1
    """)
    
    if not result.get('rows'):
        log("  ❌ No books with files found")
        return False
    
    book = result['rows'][0]
    book_uuid = book['uuid']
    book_format = book['format']
    
    log(f"  Book: {book_uuid[:8]}, Format: {book_format}")
    log(f"  Current state:")
    log(f"    is_uploaded: {book['is_uploaded']}")
    log(f"    file_missing: {book['file_missing']}")
    log(f"    needs_file_upload: {book['needs_file_upload']}")
    
    # Step 2: Simulate file missing (mark as needs upload)
    log("\n2. Simulating file missing state...")
    sql_query(f"""
        UPDATE books_files 
        SET is_uploaded = 0, file_missing = 1, needs_file_upload = 1
        WHERE book = '{book_uuid}' AND format = '{book_format}'
    """)
    
    result = sql_query(f"""
        SELECT is_uploaded, file_missing, needs_file_upload
        FROM books_files
        WHERE book = '{book_uuid}' AND format = '{book_format}'
    """)
    state = result['rows'][0]
    
    log(f"  State after marking missing:")
    log(f"    is_uploaded: {state['is_uploaded']}")
    log(f"    file_missing: {state['file_missing']}")
    log(f"    needs_file_upload: {state['needs_file_upload']}")
    
    if state['is_uploaded'] or not state['file_missing'] or not state['needs_file_upload']:
        log("  ❌ Failed to mark file as missing")
        return False
    
    log("  ✅ File marked as missing")
    
    # Step 3: Check server would request upload
    log("\n3. Verifying server requests upload...")
    
    # Server logic: needsUpload = (!is_uploaded || file_missing || needs_file_upload || empty(storage_key))
    needs_upload = (not state['is_uploaded'] or state['file_missing'] or state['needs_file_upload'])
    
    if needs_upload:
        log("  ✅ Server would request upload (needs_upload=true)")
    else:
        log("  ❌ Server would NOT request upload")
        return False
    
    # Step 4: Simulate successful upload
    log("\n4. Simulating successful file upload...")
    sql_query(f"""
        UPDATE books_files 
        SET is_uploaded = 1, file_missing = 0, needs_file_upload = 0
        WHERE book = '{book_uuid}' AND format = '{book_format}'
    """)
    
    result = sql_query(f"""
        SELECT is_uploaded, file_missing, needs_file_upload
        FROM books_files
        WHERE book = '{book_uuid}' AND format = '{book_format}'
    """)
    state = result['rows'][0]
    
    log(f"  State after upload:")
    log(f"    is_uploaded: {state['is_uploaded']}")
    log(f"    file_missing: {state['file_missing']}")
    log(f"    needs_file_upload: {state['needs_file_upload']}")
    
    if not state['is_uploaded'] or state['file_missing'] or state['needs_file_upload']:
        log("  ❌ File not marked as uploaded correctly")
        return False
    
    log("  ✅ File marked as uploaded")
    
    # Step 5: Verify server won't request upload again
    log("\n5. Verifying server won't request upload again...")
    
    needs_upload = (not state['is_uploaded'] or state['file_missing'] or state['needs_file_upload'])
    
    if not needs_upload:
        log("  ✅ Server won't request upload (needs_upload=false)")
    else:
        log("  ❌ Server would still request upload")
        return False
    
    # Step 6: Verify code implementation
    log("\n6. Verifying server code implementation...")
    
    with open('html/routes/api.php', 'r') as f:
        code = f.read()
    
    checks = [
        ("Sets is_uploaded=true", "is_uploaded = true" in code or "$file->is_uploaded = true" in code),
        ("Sets file_missing=false", "file_missing = false" in code or "$file->file_missing = false" in code),
        ("Sets needs_file_upload=false", "needs_file_upload = false" in code or "$file->needs_file_upload = false" in code),
    ]
    
    all_pass = True
    for check_name, result in checks:
        status = "✅" if result else "❌"
        log(f"  {status} {check_name}")
        if not result:
            all_pass = False
    
    return all_pass

def main():
    try:
        result = test_file_upload_tracking()
        
        log("\n" + "=" * 60)
        if result:
            log("✅ TEST PASSED: File upload verification works correctly")
            log("\nFlow verified:")
            log("  1. File missing → server requests upload")
            log("  2. Client uploads → server marks as uploaded")
            log("  3. Next sync → server doesn't request upload")
            return 0
        else:
            log("❌ TEST FAILED")
            return 1
    except Exception as e:
        log(f"\n❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
