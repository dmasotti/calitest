"""
Unit tests for library_utils.py - Pure functions without external dependencies.
"""

import pytest
import os
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

# Import library_utils functions
import sys
from pathlib import Path
plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'
sys.path.insert(0, str(plugin_path.parent))

try:
    from sync_calimob import library_utils
except ImportError:
    from calibre_plugins.sync_calimob import library_utils


class TestReadLibraryMetadata:
    """Test _read_library_metadata() function."""
    
    def test_with_metadata_db(self, tmp_path):
        """Test reading library metadata from metadata.db."""
        # Create metadata.db
        db_path = tmp_path / 'metadata.db'
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT, value TEXT)")
        cur.execute("INSERT INTO meta (key, value) VALUES ('library_id', 'test-uuid-123')")
        cur.execute("INSERT INTO meta (key, value) VALUES ('name', 'Test Library')")
        conn.commit()
        conn.close()
        
        info = library_utils._read_library_metadata(str(tmp_path))
        
        assert info['id'] == 'test-uuid-123'
        assert info['name'] == 'Test Library'
        assert info['path'] == str(tmp_path)
    
    def test_without_metadata_db(self, tmp_path):
        """Test fallback when metadata.db doesn't exist."""
        info = library_utils._read_library_metadata(str(tmp_path))
        
        assert info['id'] is not None  # Should generate hash from path
        assert info['name'] is not None  # Should use basename
        assert info['path'] == str(tmp_path)
    
    def test_without_library_id(self, tmp_path):
        """Test fallback when library_id not in metadata.db."""
        # Create metadata.db without library_id
        db_path = tmp_path / 'metadata.db'
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT, value TEXT)")
        cur.execute("INSERT INTO meta (key, value) VALUES ('name', 'Test Library')")
        conn.commit()
        conn.close()
        
        info = library_utils._read_library_metadata(str(tmp_path))
        
        assert info['id'] is not None  # Should generate hash from path
        assert info['name'] == 'Test Library'


class TestNormalizePath:
    """Test _normalize_path() function."""
    
    def test_absolute_path(self):
        """Test normalization of absolute path."""
        path = '/tmp/test/library'
        normalized = library_utils._normalize_path(path)
        
        assert normalized == os.path.abspath(path)
    
    def test_home_expansion(self):
        """Test expansion of ~ in path."""
        path = '~/test/library'
        normalized = library_utils._normalize_path(path)
        
        assert normalized == os.path.abspath(os.path.expanduser(path))
    
    def test_none_path(self):
        """Test handling of None path."""
        normalized = library_utils._normalize_path(None)
        
        assert normalized is None
    
    def test_empty_path(self):
        """Test handling of empty path."""
        normalized = library_utils._normalize_path('')
        
        assert normalized is not None  # Should return absolute path


class TestGetCalibreLibraryId:
    """Test get_calibre_library_id() function."""
    
    def test_with_valid_db(self, tmp_path):
        """Test getting library ID from valid database."""
        # Create metadata.db with library_id
        db_path = tmp_path / 'metadata.db'
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT, value TEXT)")
        cur.execute("INSERT INTO meta (key, value) VALUES ('library_id', 'test-uuid-123')")
        conn.commit()
        conn.close()
        
        db = Mock()
        db.library_path = str(tmp_path)
        
        library_id = library_utils.get_calibre_library_id(db)
        
        assert library_id == 'test-uuid-123'
    
    def test_without_library_id(self, tmp_path):
        """Test fallback when library_id not found."""
        # Create metadata.db without library_id
        db_path = tmp_path / 'metadata.db'
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT, value TEXT)")
        conn.commit()
        conn.close()
        
        db = Mock()
        db.library_path = str(tmp_path)
        
        library_id = library_utils.get_calibre_library_id(db)
        
        assert library_id is not None  # Should generate hash from path


class TestGetCalibreLibraryName:
    """Test get_calibre_library_name() function."""
    
    def test_with_name_in_db(self, tmp_path):
        """Test getting library name from database."""
        # Create metadata.db with name
        db_path = tmp_path / 'metadata.db'
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT, value TEXT)")
        cur.execute("INSERT INTO meta (key, value) VALUES ('name', 'Test Library')")
        conn.commit()
        conn.close()
        
        db = Mock()
        db.library_path = str(tmp_path)
        
        library_name = library_utils.get_calibre_library_name(db)
        
        assert library_name == 'Test Library'
    
    def test_without_name(self, tmp_path):
        """Test fallback when name not found."""
        # Create metadata.db without name
        db_path = tmp_path / 'metadata.db'
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT, value TEXT)")
        conn.commit()
        conn.close()
        
        db = Mock()
        db.library_path = str(tmp_path)
        
        library_name = library_utils.get_calibre_library_name(db)
        
        assert library_name is not None  # Should use fallback name


class TestGetCalibreLibraryIdFromPath:
    """Test get_calibre_library_id_from_path() function."""
    
    def test_with_valid_path(self, tmp_path):
        """Test getting library ID from valid path."""
        # Create metadata.db with library_id
        db_path = tmp_path / 'metadata.db'
        conn = sqlite3.connect(str(db_path))
        cur = conn.cursor()
        cur.execute("CREATE TABLE IF NOT EXISTS meta (key TEXT, value TEXT)")
        cur.execute("INSERT INTO meta (key, value) VALUES ('library_id', 'test-uuid-123')")
        conn.commit()
        conn.close()
        
        library_id = library_utils.get_calibre_library_id_from_path(str(tmp_path))
        
        assert library_id == 'test-uuid-123'
    
    def test_with_invalid_path(self):
        """Test handling of invalid path."""
        library_id = library_utils.get_calibre_library_id_from_path('/nonexistent/path')
        
        assert library_id is None
