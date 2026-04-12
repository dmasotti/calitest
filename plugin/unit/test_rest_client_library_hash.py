"""
Unit tests for REST client get_library_hash method.

Tests network error handling and response parsing.
"""
import pytest
from pathlib import Path
import importlib.util
from unittest.mock import Mock, MagicMock, patch

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
    
    def test_get_library_hash_500_error_returns_error_dict(self):
        """When server raises (e.g. RestApiError 500), return _error dict for UI visibility (per PREFLIGHT_LIBRARY_HASH_ERROR_VISIBILITY_TODO)."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        client.get = Mock(side_effect=rest_client.RestApiError('Server error', status_code=500))
        result = client.get_library_hash(35)
        assert result is not None
        assert result.get('_error') is True
        assert 'Server error' in result.get('message', '')
        assert result.get('status_code') == 500

    def test_get_library_hash_generic_exception_returns_error_dict(self):
        """When generic Exception (e.g. ConnectionError), return _error dict with status_code None."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        client.get = Mock(side_effect=Exception('Server error'))
        result = client.get_library_hash(35)
        assert result is not None
        assert result.get('_error') is True
        assert 'Server error' in result.get('message', '')
        assert result.get('status_code') is None
    
    def test_get_library_hash_network_timeout_returns_error_dict(self):
        """Network/timeout errors must be visible: return _error dict (per PREFLIGHT_LIBRARY_HASH_ERROR_VISIBILITY_TODO)."""
        client = rest_client.RestApiClient('http://test.com', 'token123')
        client.get = Mock(side_effect=TimeoutError('Connection timeout'))
        result = client.get_library_hash(35)
        assert result is not None
        assert result.get('_error') is True
        assert 'Connection timeout' in result.get('message', '')
        assert result.get('status_code') is None
    
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

    def test_get_library_hash_retries_after_rebuild_pending_then_succeeds(self, monkeypatch):
        client = rest_client.RestApiClient('http://test.com', 'token123')

        responses = [
            rest_client.RestApiError(
                'Request failed with status 202',
                status_code=202,
                response_body={
                    'rebuild_pending': True,
                    'reason': 'stale_dimensions',
                    'dimensions': ['metadata', 'covers', 'files'],
                    'retry_after': 2,
                    'job_status': 'running',
                    'job_elapsed_seconds': 5,
                },
            ),
            {
                'library_metadata_hash': 'a' * 64,
                'library_covers_hash': 'b' * 64,
                'library_files_hash': 'c' * 64,
                'total_books': 100,
                'last_modified': '2024-01-01T00:00:00Z',
            },
        ]
        sleeps = []

        def fake_get(*_args, **_kwargs):
            result = responses.pop(0)
            if isinstance(result, Exception):
                raise result
            return result

        client.get = Mock(side_effect=fake_get)
        monkeypatch.setattr(rest_client.time, 'sleep', lambda seconds: sleeps.append(seconds))

        result = client.get_library_hash(35)

        assert result is not None
        assert result['library_metadata_hash'] == 'a' * 64
        # Decision logic returns retry_after=15 for running job with elapsed < 60s
        assert len(sleeps) == 1
        assert client.get.call_count == 2

    def test_get_library_hash_returns_error_after_max_rebuild_pending_retries(self, monkeypatch):
        client = rest_client.RestApiClient('http://test.com', 'token123')

        def pending_error(retry_after):
            return rest_client.RestApiError(
                'Request failed with status 202',
                status_code=202,
                response_body={
                    'rebuild_pending': True,
                    'reason': 'missing_dimensions',
                    'dimensions': ['metadata', 'covers', 'files'],
                    'retry_after': retry_after,
                    'job_status': 'failed',
                    'job_error': 'rebuild pending too long',
                },
            )

        client.get = Mock(side_effect=[
            pending_error(5),
        ])
        sleeps = []
        monkeypatch.setattr(rest_client.time, 'sleep', lambda seconds: sleeps.append(seconds))

        result = client.get_library_hash(35)

        assert result is not None
        assert result.get('_error') is True
        assert result.get('status_code') == 202
        assert result.get('rebuild_pending') is True
        assert sleeps == []
        assert client.get.call_count == 1

    def test_get_library_hash_rebuild_pending_invalid_retry_after_uses_default_wait(self, monkeypatch):
        client = rest_client.RestApiClient('http://test.com', 'token123')

        client.get = Mock(side_effect=[
            rest_client.RestApiError(
                'Request failed with status 202',
                status_code=202,
                response_body={
                    'rebuild_pending': True,
                    'reason': 'stale_dimensions',
                    'dimensions': ['metadata'],
                    'retry_after': 'invalid',
                    'job_status': 'running',
                    'job_elapsed_seconds': 5,
                },
            ),
            {
                'library_metadata_hash': 'd' * 64,
                'library_covers_hash': None,
                'library_files_hash': None,
                'total_books': 5,
                'last_modified': '2024-01-01T00:00:00Z',
            },
        ])
        sleeps = []
        monkeypatch.setattr(rest_client.time, 'sleep', lambda seconds: sleeps.append(seconds))

        result = client.get_library_hash(35)

        assert result is not None
        assert result['library_metadata_hash'] == 'd' * 64
        # Decision logic uses its own retry_after (15 for running, elapsed < 60s)
        assert len(sleeps) == 1
        assert client.get.call_count == 2

    def test_get_library_hash_calls_progress_callback_during_retry_wait(self, monkeypatch):
        """During rebuild_pending retries, progress_callback must be called so
        the user sees a status message instead of a frozen UI."""
        client = rest_client.RestApiClient('http://test.com', 'token123')

        client.get = Mock(side_effect=[
            rest_client.RestApiError(
                'Request failed with status 202',
                status_code=202,
                response_body={
                    'rebuild_pending': True,
                    'reason': 'stale_dimensions',
                    'dimensions': ['metadata', 'covers', 'files'],
                    'retry_after': 2,
                },
            ),
            rest_client.RestApiError(
                'Request failed with status 202',
                status_code=202,
                response_body={
                    'rebuild_pending': True,
                    'reason': 'stale_dimensions',
                    'dimensions': ['metadata', 'covers', 'files'],
                    'retry_after': 2,
                },
            ),
            {
                'library_metadata_hash': 'a' * 64,
                'library_covers_hash': 'b' * 64,
                'library_files_hash': 'c' * 64,
                'total_books': 5000,
                'last_modified': '2024-01-01T00:00:00Z',
            },
        ])

        sleeps = []
        monkeypatch.setattr(rest_client.time, 'sleep', lambda seconds: sleeps.append(seconds))

        progress_messages = []
        def progress_cb(msg, current=None, total=None):
            progress_messages.append(msg)

        result = client.get_library_hash(35, progress_callback=progress_cb)

        assert result is not None
        assert result['library_metadata_hash'] == 'a' * 64
        # Progress callback must have been called at least once per retry
        assert len(progress_messages) >= 2, (
            "progress_callback should be called during each retry wait, got: %s" % progress_messages
        )
        # Messages should mention the wait/retry
        assert any('rebuild' in m.lower() or 'waiting' in m.lower() or 'retry' in m.lower()
                    for m in progress_messages), (
            "progress messages should mention rebuild/waiting/retry: %s" % progress_messages
        )

    def test_get_merkle_branches_500_error_returns_error_dict(self):
        client = rest_client.RestApiClient('http://test.com', 'token123')
        client.get = Mock(side_effect=rest_client.RestApiError('Merkle branches failed', status_code=500))

        result = client.get_merkle_branches(library_id=35, dimension='metadata')

        assert result is not None
        assert result.get('_error') is True
        assert result.get('status_code') == 500
        assert 'Merkle branches failed' in result.get('message', '')

    def test_get_merkle_leaves_timeout_returns_error_dict(self):
        client = rest_client.RestApiClient('http://test.com', 'token123')
        client.get = Mock(side_effect=TimeoutError('Merkle leaves timeout'))

        result = client.get_merkle_leaves(library_id=35, dimension='metadata', branch_id=3)

        assert result is not None
        assert result.get('_error') is True
        assert result.get('status_code') is None
        assert 'Merkle leaves timeout' in result.get('message', '')

    def test_get_merkle_root_generic_exception_returns_error_dict(self):
        client = rest_client.RestApiClient('http://test.com', 'token123')
        client.get = Mock(side_effect=Exception('Merkle root exploded'))

        result = client.get_merkle_root(library_id=35)

        assert result is not None
        assert result.get('_error') is True
        assert result.get('status_code') is None
        assert 'Merkle root exploded' in result.get('message', '')

    def test_sync_v5_can_enable_server_profile_via_env(self, monkeypatch):
        client = rest_client.RestApiClient('http://test.com', 'token123')
        monkeypatch.setenv('CALIMOB_PROFILE_SYNC_V5', '1')

        with patch.object(client, 'post', return_value={'ok': True}) as mock_post:
            client.sync_v5(
                library_id=8,
                calibre_library_uuid='1685fd4f-054e-4451-9df8-119c27fc1289',
                client_books={'b': {}, 'd': []},
            )

        _, kwargs = mock_post.call_args
        body = kwargs['body']
        assert body['options']['profile_sync_v5'] is True
