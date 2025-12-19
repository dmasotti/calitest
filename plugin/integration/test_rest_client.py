"""
Integration tests for rest_client.py - Tests with HTTP mocking.
"""

import pytest
import responses
from unittest.mock import Mock, patch

# Import rest_client
import sys
from pathlib import Path
plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'
sys.path.insert(0, str(plugin_path.parent))

try:
    from sync_calimob import rest_client
except ImportError:
    from calibre_plugins.sync_calimob import rest_client


@pytest.fixture
def mock_gui():
    """Mock GUI object."""
    gui = Mock()
    gui.status_bar = Mock()
    gui.status_bar.showMessage = Mock()
    gui.status_bar.clearMessage = Mock()
    return gui


@pytest.fixture
def rest_client_instance(mock_gui, mock_plugin_config):
    """Create RestApiClient instance with mocked config."""
    with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
        mock_prefs.__getitem__ = Mock(side_effect=lambda key: {
            'Goodreads': mock_plugin_config['plugin'],
            'LibraryMappings': mock_plugin_config['library_mappings'],
        }.get(key, {}))
        
        client = rest_client.RestApiClient(mock_gui)
        client.endpoint = 'https://api.example.com/api'
        client.token = 'test-token-123'
        return client


class TestRestApiClientInit:
    """Test RestApiClient initialization."""
    
    def test_init_with_config(self, mock_gui, mock_plugin_config):
        """Test initialization with configuration."""
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
            mock_prefs.__getitem__ = Mock(side_effect=lambda key: {
                'Goodreads': mock_plugin_config['plugin'],
            }.get(key, {}))
            
            client = rest_client.RestApiClient(mock_gui)
            
            assert client.endpoint == 'https://api.example.com/api'
            assert client.token == 'test-token-123'
    
    def test_normalize_endpoint(self, mock_gui):
        """Test endpoint normalization."""
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
            mock_prefs.__getitem__ = Mock(return_value={
                'restEndpoint': 'example.com',  # Without https://
            })
            
            client = rest_client.RestApiClient(mock_gui)
            
            assert client.endpoint.startswith('https://')
            assert '/api' in client.endpoint


class TestRestApiClientHeaders:
    """Test header generation."""
    
    def test_get_headers_with_token(self, rest_client_instance):
        """Test headers include Bearer token."""
        headers = rest_client_instance._get_headers()
        
        assert 'Authorization' in headers
        assert headers['Authorization'].startswith('Bearer ')
        assert 'test-token-123' in headers['Authorization']
    
    def test_get_headers_without_token(self, mock_gui):
        """Test headers without token."""
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
            mock_prefs.__getitem__ = Mock(return_value={
                'restEndpoint': 'https://api.example.com',
                'restToken': '',
                'deviceToken': '',
            })
            
            client = rest_client.RestApiClient(mock_gui)
            headers = client._get_headers()
            
            assert 'Authorization' not in headers


class TestRestApiClientRequests:
    """Test HTTP request methods."""
    
    @responses.activate
    def test_get_request_success(self, rest_client_instance):
        """Test successful GET request."""
        responses.add(
            responses.GET,
            'https://api.example.com/api/test',
            json={'status': 'ok'},
            status=200
        )
        
        response = rest_client_instance._request('GET', '/test')
        
        assert response is not None
        assert 'status' in response
        assert response['status'] == 'ok'
    
    @responses.activate
    def test_get_request_404(self, rest_client_instance):
        """Test GET request with 404 error."""
        responses.add(
            responses.GET,
            'https://api.example.com/api/test',
            json={'error': 'Not found'},
            status=404
        )
        
        with pytest.raises(rest_client.RestApiError) as exc_info:
            rest_client_instance._request('GET', '/test')
        
        assert exc_info.value.status_code == 404
    
    @responses.activate
    def test_post_request_success(self, rest_client_instance):
        """Test successful POST request."""
        responses.add(
            responses.POST,
            'https://api.example.com/api/test',
            json={'id': '123', 'status': 'created'},
            status=201
        )
        
        response = rest_client_instance._request('POST', '/test', json={'name': 'Test'})
        
        assert response is not None
        assert response['id'] == '123'
    
    @responses.activate
    def test_retry_on_500_error(self, rest_client_instance):
        """Test retry logic on 500 error."""
        # First two requests fail, third succeeds
        responses.add(
            responses.GET,
            'https://api.example.com/api/test',
            json={'error': 'Internal error'},
            status=500
        )
        responses.add(
            responses.GET,
            'https://api.example.com/api/test',
            json={'error': 'Internal error'},
            status=500
        )
        responses.add(
            responses.GET,
            'https://api.example.com/api/test',
            json={'status': 'ok'},
            status=200
        )
        
        response = rest_client_instance._request('GET', '/test')
        
        assert response is not None
        assert response['status'] == 'ok'
        # Should have made 3 requests (2 failures + 1 success)
        assert len(responses.calls) == 3


class TestRestApiClientMethods:
    """Test specific API methods."""
    
    @responses.activate
    def test_get_libraries(self, rest_client_instance):
        """Test get_libraries() method."""
        responses.add(
            responses.GET,
            'https://api.example.com/api/libraries',
            json={
                'libraries': [
                    {'id': '1', 'name': 'Library 1'},
                    {'id': '2', 'name': 'Library 2'}
                ]
            },
            status=200
        )
        
        result = rest_client_instance.get_libraries()
        
        assert 'libraries' in result
        assert len(result['libraries']) == 2
        assert result['libraries'][0]['id'] == '1'
    
    @responses.activate
    def test_create_library(self, rest_client_instance):
        """Test create_library() method."""
        responses.add(
            responses.POST,
            'https://api.example.com/api/libraries',
            json={'id': 'new-lib-123', 'name': 'New Library'},
            status=201
        )
        
        result = rest_client_instance.create_library('New Library')
        
        assert result['id'] == 'new-lib-123'
        assert result['name'] == 'New Library'
    
    @responses.activate
    def test_pull_changes(self, rest_client_instance):
        """Test pull_changes() method."""
        responses.add(
            responses.GET,
            'https://api.example.com/api/libraries/123/changes',
            json={
                'changes': [
                    {'op': 'create', 'item': {'id': '1', 'title': 'Book 1'}},
                    {'op': 'update', 'item': {'id': '2', 'title': 'Book 2 Updated'}}
                ],
                'cursor': 'next-cursor-123'
            },
            status=200
        )
        
        result = rest_client_instance.pull_changes('123', cursor=None)
        
        assert 'changes' in result
        assert len(result['changes']) == 2
        assert result['cursor'] == 'next-cursor-123'
    
    @responses.activate
    def test_push_changes(self, rest_client_instance):
        """Test push_changes() method."""
        responses.add(
            responses.POST,
            'https://api.example.com/api/libraries/123/changes',
            json={
                'applied': [
                    {'client_change_id': 'change-1', 'status': 'applied'},
                    {'client_change_id': 'change-2', 'status': 'applied'}
                ]
            },
            status=200
        )
        
        changes = [
            {'op': 'create', 'item': {'title': 'New Book'}}
        ]
        
        result = rest_client_instance.push_changes('123', changes)
        
        assert 'applied' in result
        assert len(result['applied']) == 2
    
    @responses.activate
    def test_upload_cover(self, rest_client_instance):
        """Test upload_cover() method."""
        cover_data = b'fake_cover_image_data'
        
        responses.add(
            responses.PUT,
            'https://api.example.com/api/items/123/cover',
            json={'status': 'uploaded', 'cover_hash': 'abc123'},
            status=200
        )
        
        result = rest_client_instance.upload_cover(
            calibre_book_id=123,
            library_id='lib-123',
            cover_data=cover_data,
            cover_hash='abc123'
        )
        
        assert result['status'] == 'uploaded'
        # Verify cover data was sent
        assert len(responses.calls) == 1
        assert responses.calls[0].request.body == cover_data
    
    @responses.activate
    def test_download_cover(self, rest_client_instance):
        """Test download_cover() method."""
        cover_data = b'fake_cover_image_data'
        
        responses.add(
            responses.GET,
            'https://api.example.com/api/items/123/cover',
            body=cover_data,
            content_type='image/jpeg',
            status=200
        )
        
        result = rest_client_instance.download_cover(
            calibre_book_id=123,
            library_id='lib-123'
        )
        
        assert result == cover_data


class TestRestApiClientErrorHandling:
    """Test error handling."""
    
    @responses.activate
    def test_401_unauthorized(self, rest_client_instance):
        """Test handling of 401 Unauthorized."""
        responses.add(
            responses.GET,
            'https://api.example.com/api/test',
            json={'error': 'Unauthorized'},
            status=401
        )
        
        with pytest.raises(rest_client.RestApiError) as exc_info:
            rest_client_instance._request('GET', '/test')
        
        assert exc_info.value.status_code == 401
    
    @responses.activate
    def test_403_forbidden(self, rest_client_instance):
        """Test handling of 403 Forbidden."""
        responses.add(
            responses.GET,
            'https://api.example.com/api/test',
            json={'error': 'Forbidden'},
            status=403
        )
        
        with pytest.raises(rest_client.RestApiError) as exc_info:
            rest_client_instance._request('GET', '/test')
        
        assert exc_info.value.status_code == 403
    
    @responses.activate
    def test_network_error(self, rest_client_instance):
        """Test handling of network errors."""
        responses.add(
            responses.GET,
            'https://api.example.com/api/test',
            body=Exception('Network error')
        )
        
        with pytest.raises(Exception):
            rest_client_instance._request('GET', '/test')
