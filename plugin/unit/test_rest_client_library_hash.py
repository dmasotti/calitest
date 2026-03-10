"""
Unit tests for REST client get_library_hash method.

Tests network error handling and response parsing.
"""
import pytest
from pathlib import Path
import importlib.util
from unittest.mock import Mock, MagicMock

# Import rest_client
plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'
spec = importlib.util.spec_from_file_location("rest_client",
    str(plugin_path / 'rest_client.py'))
rest_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rest_client)


class TestRestClientLibraryHash:
    """Test REST client get_library_hash method."""
    
    def test_get_library_hash_success(self):
        """Test successful library hash retrieval."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        
        # Mock the get method directly
        mock_response = {
            'library_metadata_hash': 'a' * 64,
            'library_covers_hash': 'b' * 64,
            'library_files_hash': 'c' * 64,
            'total_books': 100,
            'last_modified': '2024-01-01T00:00:00Z'
        }
        client.get = Mock(return_value=mock_response)
        
        result = client.get_library_hash(35)
        
        assert result is not None
        assert result['library_metadata_hash'] == 'a' * 64
        assert result['library_covers_hash'] == 'b' * 64
        assert result['library_files_hash'] == 'c' * 64
        assert result['total_books'] == 100
        assert result['last_modified'] == '2024-01-01T00:00:00Z'
    
    def test_get_library_hash_null_response(self):
        """Test when server returns null hash (VIEW not available)."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        
        mock_response = {
            'library_metadata_hash': None,
            'total_books': 0,
            'last_modified': None
        }
        client.get = Mock(return_value=mock_response)
        
        result = client.get_library_hash(35)
        
        assert result is None
    
    def test_get_library_hash_404_not_found(self):
        """Test when endpoint returns 404 (not implemented)."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        
        client.get = Mock(return_value=None)
        
        result = client.get_library_hash(35)
        
        assert result is None
    
    def test_get_library_hash_500_error(self):
        """Test when server returns 500 error."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        
        client.get = Mock(side_effect=Exception('Server error'))
        
        result = client.get_library_hash(35)
        
        assert result is None
    
    def test_get_library_hash_network_timeout(self):
        """Test network timeout handling."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        
        client.get = Mock(side_effect=TimeoutError('Connection timeout'))
        
        result = client.get_library_hash(35)
        
        assert result is None
    
    def test_get_library_hash_invalid_json(self):
        """Test invalid JSON response."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        
        # Return invalid structure
        client.get = Mock(return_value={'invalid': 'structure'})
        
        result = client.get_library_hash(35)
        
        # Should return None (no library_hash field)
        assert result is None
    
    def test_get_library_hash_missing_fields(self):
        """Test response with missing fields."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        
        # Has metadata hash but missing optional fields
        mock_response = {
            'library_metadata_hash': 'a' * 64
        }
        client.get = Mock(return_value=mock_response)
        
        result = client.get_library_hash(35)
        
        # Should still work with partial data
        assert result is not None
        assert result['library_metadata_hash'] == 'a' * 64

    def test_get_library_hash_accepts_split_hash_response(self):
        """Split fingerprint response should be accepted even without legacy library_hash."""
        client = rest_client.RestApiClient('http://test.com', 'token123')

        mock_response = {
            'library_metadata_hash': 'b' * 64,
            'library_covers_hash': 'c' * 64,
            'library_files_hash': 'd' * 64,
            'total_books': 10,
            'last_modified': '2026-03-03T11:00:00Z',
        }
        client.get = Mock(return_value=mock_response)

        result = client.get_library_hash(35)
        assert result is not None
        assert result['library_metadata_hash'] == 'b' * 64
        assert result['library_covers_hash'] == 'c' * 64
        assert result['library_files_hash'] == 'd' * 64

    def test_get_library_hash_does_not_inject_legacy_merkle_root_fields(self):
        client = rest_client.RestApiClient('http://test.com', 'token123')

        mock_response = {
            'library_metadata_hash': 'b' * 64,
            'library_covers_hash': 'c' * 64,
            'library_files_hash': 'd' * 64,
            'total_books': 10,
            'last_modified': '2026-03-03T11:00:00Z',
        }
        client.get = Mock(return_value=mock_response)

        result = client.get_library_hash(35)

        assert result is not None
        assert 'metadata_merkle_root' not in result
        assert 'covers_merkle_root' not in result
        assert 'files_merkle_root' not in result
    
    def test_get_library_hash_empty_hash(self):
        """Test when server returns empty hash string."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        
        mock_response = {
            'library_metadata_hash': '',
            'total_books': 0,
            'last_modified': None
        }
        client.get = Mock(return_value=mock_response)
        
        result = client.get_library_hash(35)
        
        assert result is None
    
    def test_get_library_hash_constructs_correct_url(self):
        """Test that correct URL and params are used."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        
        mock_response = {
            'library_metadata_hash': 'a' * 64,
            'total_books': 1,
            'last_modified': '2024-01-01T00:00:00Z'
        }
        client.get = Mock(return_value=mock_response)
        
        client.get_library_hash(42)
        
        # Verify get was called with correct path and params
        client.get.assert_called_once()
        call_args = client.get.call_args
        
        # First arg should be path
        assert call_args[0][0] == '/sync/v5/library-hash'
        
        # Should have params with library_id
        assert 'params' in call_args[1]
        assert call_args[1]['params']['library_id'] == 42
