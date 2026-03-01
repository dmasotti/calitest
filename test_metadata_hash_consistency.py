#!/usr/bin/env python3
"""
Test metadata hash consistency between Python (client) and PHP (server).

This test verifies that both implementations compute the same hash for the same input.
"""

import sys
import os
import json
import subprocess
import re

# Add sync_calimob to path
sync_calimob_path = os.path.join(os.path.dirname(__file__), '..', 'sync_calimob')
sys.path.insert(0, sync_calimob_path)

# Import after adding to path
import sync_utils

def test_hash_consistency():
    """Test that Python and PHP compute the same metadata hash."""
    
    # Sample book data (from actual sync)
    test_cases = [
        {
            "name": "Minimal book",
            "json_item": {
                "id": 18337,
                "uuid": "85afa460-dd9c-4d4c-b5b5-41d9b60c4ff5",
                "title": "Etica dell'intelligenza artificiale",
                "authors": [{"name": "Unknown", "role": "author", "position": 0}],
                "series": None,
                "identifiers": {},
                "publisher": None,
                "pubdate": 1722722400,
                "languages": [],
                "tags": [],
                "rating": 0,
                "comments": None,
                "last_modified": 1767562562
            },
            "format_cache": {},
            "cover_hash": None
        },
        {
            "name": "Book with metadata",
            "json_item": {
                "id": 18339,
                "uuid": "7bc16adf-a306-44bc-a798-0038d17eff5a",
                "title": "Quantum-Native Application Development",
                "authors": [{"name": "Beach, Dr. David Francis", "role": "author", "position": 0}],
                "series": None,
                "identifiers": {},
                "publisher": "CIO Publishing",
                "pubdate": 1640649600,
                "languages": ["eng"],
                "tags": [],
                "rating": None,
                "comments": None,
                "last_modified": 1767565614
            },
            "format_cache": {
                "EPUB": {"hash": "sha256:40d6c63a03773ca6448d9b40f3e96d4a473aa972ed284ab137f4af4151eb0fc2"}
            },
            "cover_hash": "sha256:9f0d7769bfebcd475037dc0bc883b2dd44256a7c371c42b2ce16ba308145e2d9"
        }
    ]
    
    project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
    php_script = os.path.join(project_root, 'html', 'artisan')
    
    print("=" * 60)
    print("Testing metadata hash consistency (Python vs PHP)")
    print("=" * 60)
    
    all_passed = True
    
    for i, test_case in enumerate(test_cases, 1):
        print(f"\nTest {i}: {test_case['name']}")
        print("-" * 60)
        
        # Compute Python hash
        python_hash = sync_utils.compute_metadata_hash(
            test_case['json_item'],
            test_case.get('format_cache', {}),
            test_case.get('cover_hash')
        )
        
        print(f"Python hash: {python_hash}")
        
        # Compute PHP hash via helper script
        import tempfile
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            json.dump(test_case['json_item'], f)
            temp_file = f.name
        
        try:
            php_helper = os.path.join(project_root, 'tests', 'compute_hash.php')
            php_command = ['php', php_helper, temp_file]
            
            result = subprocess.run(
                php_command,
                capture_output=True,
                text=True,
                timeout=10
            )
            
            if result.returncode != 0:
                print(f"PHP error: {result.stderr}")
                all_passed = False
            else:
                # PHP can emit startup warnings (e.g. missing xdebug) before the hash.
                # Extract the last sha256 hex digest from stdout to compare reliably.
                matches = re.findall(r"\b[a-fA-F0-9]{64}\b", result.stdout or "")
                php_hash = matches[-1].lower() if matches else ""
                print(f"PHP hash:    {php_hash}")
                
                if not php_hash:
                    print("✗ FAIL: No valid hash found in PHP output")
                    if result.stdout:
                        print(f"PHP stdout: {result.stdout.strip()}")
                    if result.stderr:
                        print(f"PHP stderr: {result.stderr.strip()}")
                    all_passed = False
                elif python_hash == php_hash:
                    print("✓ PASS: Hashes match")
                else:
                    print("✗ FAIL: Hashes don't match")
                    all_passed = False
                
        except subprocess.TimeoutExpired:
            print("✗ FAIL: PHP command timed out")
            all_passed = False
        except Exception as e:
            print(f"✗ FAIL: Error running PHP: {e}")
            all_passed = False
        finally:
            if os.path.exists(temp_file):
                os.unlink(temp_file)
    
    print("\n" + "=" * 60)
    if all_passed:
        print("✓ All tests passed")
        return 0
    else:
        print("✗ Some tests failed")
        return 1

if __name__ == '__main__':
    sys.exit(test_hash_consistency())
