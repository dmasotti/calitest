"""
Unit tests for REST client declare_cover_absent (H3 escape hatch).

When the server asks for a byte-absent cover the client does not have, the client declares
the cover absent so the server converges to NO_COVER. This pins the HTTP shape.
"""
import pytest
from pathlib import Path
import importlib.util
from unittest.mock import Mock

plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'
spec = importlib.util.spec_from_file_location("rest_client", str(plugin_path / 'rest_client.py'))
rest_client = importlib.util.module_from_spec(spec)
spec.loader.exec_module(rest_client)


class TestDeclareCoverAbsent:
    def test_issues_delete_to_cover_path_with_library_params(self):
        client = rest_client.RestApiClient('http://test.com', 'token123')
        client._request = Mock(return_value={'has_cover': False, 'converged': True})

        client.declare_cover_absent(item_uuid='u-123', calibre_library_uuid='lib-uuid-9')

        client._request.assert_called_once()
        args, kwargs = client._request.call_args
        assert args[0] == 'DELETE'
        assert args[1] == '/items/uuid/u-123/cover'
        assert kwargs['params'].get('calibre_library_uuid') == 'lib-uuid-9'
        assert kwargs['success_status'] == 200

    def test_prefers_calibre_library_uuid_and_includes_library_id_when_given(self):
        client = rest_client.RestApiClient('http://test.com', 'token123')
        client._request = Mock(return_value={})

        client.declare_cover_absent(item_uuid='u-1', library_id=42, calibre_library_uuid='lib-x')

        _, kwargs = client._request.call_args
        assert kwargs['params'] == {'library_id': 42, 'calibre_library_uuid': 'lib-x'}

    def test_requires_item_uuid(self):
        client = rest_client.RestApiClient('http://test.com', 'token123')
        client._request = Mock()
        with pytest.raises(rest_client.RestApiError):
            client.declare_cover_absent(item_uuid=None, calibre_library_uuid='lib-x')
        client._request.assert_not_called()
