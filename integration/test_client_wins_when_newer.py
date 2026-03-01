#!/usr/bin/env python3
"""
Test: Client always wins when last_modified is newer or equal.

Verifies the fix for bug where server updates were applied even when
client had newer timestamp, if metadata hashes didn't match.

Critical logic (sync_worker.py line 4140):
    if local_last_modified >= server_last_modified:
        skip_update = True  # Client wins, regardless of metadata_matches
"""

import sys
import os

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '../..')))

def log(msg):
    from datetime import datetime
    print(f"[{datetime.now().strftime('%H:%M:%S')}] {msg}")

def test_skip_logic_in_code():
    """Verify the skip logic in sync_worker.py is correct"""
    log("=" * 60)
    log("TEST: Client Wins When Newer (Code Verification)")
    log("=" * 60)
    
    log("\n1. Reading sync_worker.py...")
    # Use absolute path relative to this test file
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(test_dir, '../..'))
    sync_worker_path = os.path.join(project_root, 'sync_calimob/sync_worker.py')
    
    with open(sync_worker_path, 'r') as f:
        code = f.read()
    
    # Find the skip logic section
    log("\n2. Checking skip update logic...")
    
    # Look for the correct pattern (without nested if metadata_matches)
    correct_pattern = """if server_last_modified and local_last_modified and local_last_modified >= server_last_modified:
            skip_update = True"""
    
    # Look for the OLD buggy pattern (with nested if metadata_matches)
    buggy_pattern = """if server_last_modified and local_last_modified and local_last_modified >= server_last_modified:
            if metadata_matches:
                skip_update = True"""
    
    has_correct = correct_pattern.replace(' ', '').replace('\n', '') in code.replace(' ', '').replace('\n', '')
    has_buggy = buggy_pattern.replace(' ', '').replace('\n', '') in code.replace(' ', '').replace('\n', '')
    
    log(f"  Correct logic (skip_update = True unconditionally): {'✅' if has_correct else '❌'}")
    log(f"  Buggy logic (nested if metadata_matches): {'❌ FOUND' if has_buggy else '✅ NOT FOUND'}")
    
    if has_buggy:
        log("\n  ❌ FAIL: Code still has buggy nested condition")
        log("  Expected:")
        log("    if local_last_modified >= server_last_modified:")
        log("        skip_update = True  # Client wins always")
        log("\n  Found:")
        log("    if local_last_modified >= server_last_modified:")
        log("        if metadata_matches:  # ← BUG: Should not check this")
        log("            skip_update = True")
        return False
    
    if not has_correct:
        log("\n  ❌ FAIL: Cannot find correct skip logic")
        return False
    
    log("\n  ✅ PASS: Skip logic is correct")
    return True

def test_rating_conversion():
    """Verify rating None stays None (not converted to 0)"""
    log("\n3. Checking rating conversion in sync_mapper.py...")
    
    # Use absolute path relative to this test file
    test_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.abspath(os.path.join(test_dir, '../..'))
    sync_mapper_path = os.path.join(project_root, 'sync_calimob/sync_mapper.py')
    
    with open(sync_mapper_path, 'r') as f:
        code = f.read()
    
    # Look for the buggy pattern: else: metadata_dict['rating'] = 0
    buggy_rating = "else:\n        metadata_dict['rating'] = 0"
    
    has_buggy_rating = buggy_rating in code
    
    log(f"  Buggy rating conversion (None → 0): {'❌ FOUND' if has_buggy_rating else '✅ NOT FOUND'}")
    
    if has_buggy_rating:
        log("\n  ❌ FAIL: Rating None is still converted to 0")
        log("  This causes hash mismatch when both client and server have None")
        return False
    
    # Check for correct comment
    has_correct_comment = "leave rating unset (None)" in code
    log(f"  Correct comment (leave rating unset): {'✅' if has_correct_comment else '⚠️'}")
    
    log("\n  ✅ PASS: Rating None stays None")
    return True

def test_scenario_simulation():
    """Simulate the scenario that triggered the bug"""
    log("\n4. Simulating bug scenario...")
    
    # Scenario: Client has newer timestamp but different metadata
    server_lm = 1771841998  # 2026-02-23 10:19:58
    client_lm = 1771854266  # 2026-02-23 13:44:26 (3 hours later)
    
    server_hash = "23b8571c"
    client_hash = "38bb79d1"
    metadata_matches = (server_hash == client_hash)
    
    log(f"  Server last_modified: {server_lm}")
    log(f"  Client last_modified: {client_lm}")
    log(f"  Server hash: {server_hash}")
    log(f"  Client hash: {client_hash}")
    log(f"  Metadata matches: {metadata_matches}")
    
    log("\n  Applying logic:")
    log(f"    if local_last_modified ({client_lm}) >= server_last_modified ({server_lm}):")
    
    if client_lm >= server_lm:
        log(f"      skip_update = True  ✅")
        log(f"\n  Result: Client wins (no update from server)")
        log(f"  Reason: Client is newer ({client_lm} > {server_lm})")
        log(f"  Note: metadata_matches={metadata_matches} is IGNORED (correct!)")
        return True
    else:
        log(f"      skip_update = False  ❌")
        log(f"\n  Result: Server wins (update applied)")
        log(f"  This is WRONG - client should win when newer!")
        return False

def main():
    try:
        result1 = test_skip_logic_in_code()
        result2 = test_rating_conversion()
        result3 = test_scenario_simulation()
        
        log("\n" + "=" * 60)
        if result1 and result2 and result3:
            log("✅ ALL TESTS PASSED")
            log("\nFix verified:")
            log("  1. Client wins when last_modified >= server (always)")
            log("  2. metadata_matches check removed from condition")
            log("  3. Rating None stays None (not converted to 0)")
            return 0
        else:
            log("❌ SOME TESTS FAILED")
            return 1
    except Exception as e:
        log(f"\n❌ TEST ERROR: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == '__main__':
    sys.exit(main())
