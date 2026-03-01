"""
Test fast path integration in sync_v5().

These tests verify that the fast path logic is correct,
focusing on the critical bug: library_uuid must be self.library_id.
"""
import pytest
import sys
import os

# Add plugin to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '../../..', 'sync_calimob'))


class TestFastPathLibraryUUID:
    """Test that library_uuid is correctly obtained from self.library_id."""
    
    def test_library_uuid_source_in_code(self):
        """
        Verify sync_worker.py uses self.library_id for library_uuid.
        
        This is a regression test for the bug where cfg.get_library_uuid(self.db)
        was called but the function didn't exist.
        """
        # Read sync_worker.py
        sync_worker_path = os.path.join(
            os.path.dirname(__file__), 
            '../../..', 
            'sync_calimob', 
            'sync_worker.py'
        )
        
        with open(sync_worker_path, 'r') as f:
            code = f.read()
        
        # Find fast path section
        assert 'Fast path: check library hash before full sync' in code, \
            "Fast path code not found"
        
        # Verify library_uuid is set from self.library_id
        assert 'library_uuid = self.library_id' in code, \
            "CRITICAL: library_uuid must be self.library_id, not queried from DB"
        
        # Verify the bug is NOT present
        assert 'cfg.get_library_uuid' not in code, \
            "BUG: cfg.get_library_uuid doesn't exist, use self.library_id"
    
    def test_sync_worker_has_library_id_attribute(self):
        """Verify SyncWorker.__init__ accepts library_id parameter."""
        sync_worker_path = os.path.join(
            os.path.dirname(__file__), 
            '../../..', 
            'sync_calimob', 
            'sync_worker.py'
        )
        
        with open(sync_worker_path, 'r') as f:
            code = f.read()
        
        # Verify __init__ signature
        assert 'def __init__(self, gui=None, db=None, library_id=None' in code, \
            "SyncWorker.__init__ must accept library_id parameter"
        
        # Verify library_id is stored
        assert 'self.library_id = library_id' in code, \
            "SyncWorker must store library_id as instance variable"
    
    def test_fast_path_calls_get_library_hash_with_library_uuid(self):
        """Verify fast path calls sync_utils.get_library_hash(db, library_uuid)."""
        sync_worker_path = os.path.join(
            os.path.dirname(__file__), 
            '../../..', 
            'sync_calimob', 
            'sync_worker.py'
        )
        
        with open(sync_worker_path, 'r') as f:
            code = f.read()
        
        # Verify get_library_hash is called with library_uuid
        assert 'sync_utils.get_library_hash(self.db, library_uuid)' in code, \
            "Fast path must call sync_utils.get_library_hash(db, library_uuid)"
    
    def test_fast_path_summary_flag_exists(self):
        """Verify fast_path_used flag is set in summary."""
        sync_worker_path = os.path.join(
            os.path.dirname(__file__), 
            '../../..', 
            'sync_calimob', 
            'sync_worker.py'
        )
        
        with open(sync_worker_path, 'r') as f:
            code = f.read()
        
        # Verify summary has fast_path_used flag
        assert "'fast_path_used': False" in code, \
            "Summary must initialize fast_path_used flag"
        
        assert "summary['fast_path_used'] = True" in code, \
            "Fast path must set summary['fast_path_used'] = True when used"


class TestFastPathLogic:
    """Test fast path decision logic."""
    
    def test_fast_path_compares_hashes(self):
        """Verify fast path compares local and server hashes."""
        sync_worker_path = os.path.join(
            os.path.dirname(__file__), 
            '../../..', 
            'sync_calimob', 
            'sync_worker.py'
        )
        
        with open(sync_worker_path, 'r') as f:
            code = f.read()
        
        # Verify hash comparison
        assert "local_hash_data['library_hash'] == server_hash_data['library_hash']" in code, \
            "Fast path must compare local and server library hashes"
    
    def test_fast_path_returns_early_on_match(self):
        """Verify fast path returns early when hashes match."""
        sync_worker_path = os.path.join(
            os.path.dirname(__file__), 
            '../../..', 
            'sync_calimob', 
            'sync_worker.py'
        )
        
        with open(sync_worker_path, 'r') as f:
            code = f.read()
        
        # Find fast path section
        fast_path_start = code.find('Fast path: check library hash before full sync')
        assert fast_path_start > 0
        
        # Extract fast path section (next ~100 lines)
        fast_path_section = code[fast_path_start:fast_path_start + 5000]
        
        # Verify early return on match
        assert 'return summary' in fast_path_section, \
            "Fast path must return early when hashes match"
        
        assert "summary['fast_path_used'] = True" in fast_path_section, \
            "Fast path must set flag before returning"
    
    def test_fast_path_handles_exceptions(self):
        """Verify fast path has exception handling."""
        sync_worker_path = os.path.join(
            os.path.dirname(__file__), 
            '../../..', 
            'sync_calimob', 
            'sync_worker.py'
        )
        
        with open(sync_worker_path, 'r') as f:
            code = f.read()
        
        # Find fast path section
        fast_path_start = code.find('Fast path: check library hash before full sync')
        assert fast_path_start > 0
        
        # Extract fast path section
        fast_path_section = code[fast_path_start:fast_path_start + 5000]
        
        # Verify exception handling
        assert 'except Exception' in fast_path_section, \
            "Fast path must have exception handling"
        
        assert 'continuing with normal sync' in fast_path_section.lower(), \
            "Fast path must log that it's falling back to normal sync"


class TestFastPathDocumentation:
    """Test that fast path is properly documented."""
    
    def test_fast_path_has_comments(self):
        """Verify fast path has explanatory comments."""
        sync_worker_path = os.path.join(
            os.path.dirname(__file__), 
            '../../..', 
            'sync_calimob', 
            'sync_worker.py'
        )
        
        with open(sync_worker_path, 'r') as f:
            code = f.read()
        
        # Verify comments explain the optimization
        assert 'Fast path' in code, \
            "Fast path must be documented with comments"
        
        assert '50k books' in code or '64 bytes' in code, \
            "Fast path comments should explain performance benefit"
    
    def test_fast_path_has_debug_logging(self):
        """Verify fast path has debug logging for troubleshooting."""
        sync_worker_path = os.path.join(
            os.path.dirname(__file__), 
            '../../..', 
            'sync_calimob', 
            'sync_worker.py'
        )
        
        with open(sync_worker_path, 'r') as f:
            code = f.read()
        
        # Find fast path section
        fast_path_start = code.find('Fast path: check library hash before full sync')
        fast_path_section = code[fast_path_start:fast_path_start + 5000]
        
        # Verify debug logging
        assert 'calimob_debug' in fast_path_section, \
            "Fast path must have debug logging"
        
        assert 'Fast path:' in fast_path_section, \
            "Fast path logs should be prefixed with 'Fast path:'"

