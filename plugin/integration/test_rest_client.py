"""Integration-leaning tests for rest_client.py using local mocks only."""

from __future__ import annotations

import io
import json
from unittest.mock import Mock, patch

import pytest

# Import rest_client
import sys
from pathlib import Path

plugin_path = Path(__file__).parent.parent.parent.parent / "sync_calimob"
sys.path.insert(0, str(plugin_path.parent))

try:
    from sync_calimob import rest_client
except ImportError:
    from calibre_plugins.sync_calimob import rest_client


class DummyHttpResponse(dict):
    """Small mapping with httplib2-like get()."""


class DummyUrlOpenResponse:
    def __init__(self, status_code=200, body=None):
        self._status_code = status_code
        self._body = body if body is not None else b"{}"

    def getcode(self):
        return self._status_code

    def read(self):
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


@pytest.fixture
def mock_gui():
    gui = Mock()
    gui.status_bar = Mock()
    gui.status_bar.showMessage = Mock()
    gui.status_bar.clearMessage = Mock()
    return gui


@pytest.fixture
def rest_client_instance(mock_gui, mock_plugin_config):
    with patch("calibre_plugins.sync_calimob.config.plugin_prefs") as mock_prefs:
        mock_prefs.__getitem__ = Mock(
            side_effect=lambda key: {
                "Caliweb": mock_plugin_config["plugin"],
                "LibraryMappings": mock_plugin_config["library_mappings"],
            }.get(key, {})
        )
        client = rest_client.RestApiClient(mock_gui)
        client._raw_discovery_endpoint = "https://api.example.com"
        client.token = "test-token-123"
        client.max_retries = 3
        client.base_backoff = 0
        client.max_backoff = 0
        return client


def make_http_result(status_code, body):
    if isinstance(body, dict):
        body = json.dumps(body).encode("utf-8")
    elif isinstance(body, str):
        body = body.encode("utf-8")
    return DummyHttpResponse(status=str(status_code)), body


class TestRestApiClientInit:
    def test_init_with_config(self, mock_gui, mock_plugin_config):
        with patch("calibre_plugins.sync_calimob.config.plugin_prefs") as mock_prefs:
            mock_prefs.__getitem__ = Mock(
                side_effect=lambda key: {
                    "Caliweb": mock_plugin_config["plugin"],
                }.get(key, {})
            )
            client = rest_client.RestApiClient(mock_gui)
            assert client._raw_discovery_endpoint == "https://api.example.com"
            assert client.token == "test-token-123"

    def test_normalize_endpoint(self, mock_gui):
        with patch("calibre_plugins.sync_calimob.config.plugin_prefs") as mock_prefs:
            mock_prefs.__getitem__ = Mock(return_value={"restEndpoint": "example.com"})
            client = rest_client.RestApiClient(mock_gui)
            normalized = client.get_api_base()
            assert normalized.startswith("https://")
            assert normalized.endswith("/api")


class TestRestApiClientHeaders:
    def test_get_headers_with_token(self, rest_client_instance):
        headers = rest_client_instance._get_headers()
        assert headers["Authorization"] == "Bearer test-token-123"

    def test_get_headers_without_token(self, mock_gui):
        with patch("calibre_plugins.sync_calimob.config.plugin_prefs") as mock_prefs:
            mock_prefs.__getitem__ = Mock(
                return_value={
                    "restEndpoint": "https://api.example.com",
                    "restToken": "",
                    "deviceToken": "",
                }
            )
            client = rest_client.RestApiClient(mock_gui)
            headers = client._get_headers()
            assert "Authorization" not in headers


class TestRestApiClientRequests:
    def test_get_request_success(self, rest_client_instance):
        with patch.object(
            rest_client_instance.http,
            "request",
            return_value=make_http_result(200, {"status": "ok"}),
        ):
            response, body = rest_client_instance._request("GET", "/test")

        assert response["status"] == "200"
        assert body["status"] == "ok"

    def test_post_sync_pull(self, rest_client_instance):
        expected = {"new_cursor": "abc", "has_more": False, "changes": []}
        with patch.object(
            rest_client_instance,
            "_request",
            return_value=(DummyHttpResponse(status="200"), expected),
        ) as mock_request:
            response = rest_client_instance.post_sync_pull(
                cursor=None,
                limit=1,
                library_id=35,
                calibre_library_uuid="lib-uuid",
                include_inventory=True,
                include_inventory_hint=True,
                client_inventory={"uuids": ["uuid-1", "uuid-2"]},
            )

        assert response["new_cursor"] == "abc"
        _, args, kwargs = mock_request.mock_calls[0]
        assert args[0] == "POST"
        assert args[1] == "/sync/pull"
        assert kwargs["body"]["library_id"] == 35
        assert kwargs["body"]["include_inventory"] is True

    def test_get_request_404(self, rest_client_instance):
        with patch.object(
            rest_client_instance.http,
            "request",
            return_value=make_http_result(404, {"error": "Not found"}),
        ):
            with pytest.raises(rest_client.RestApiError) as exc_info:
                rest_client_instance._request("GET", "/test")

        assert exc_info.value.status_code == 404

    def test_post_request_success(self, rest_client_instance):
        with patch.object(
            rest_client_instance.http,
            "request",
            return_value=make_http_result(201, {"id": "123", "status": "created"}),
        ):
            response, body = rest_client_instance._request(
                "POST",
                "/test",
                body={"name": "Test"},
                success_status=201,
            )

        assert response["status"] == "201"
        assert body["id"] == "123"

    def test_sync_v5_sends_client_batch_fields(self, rest_client_instance):
        with patch.object(rest_client_instance, "post", return_value={"ok": True}) as mock_post:
            rest_client_instance.sync_v5(
                library_id=8,
                calibre_library_uuid="1685fd4f-054e-4451-9df8-119c27fc1289",
                cursor="123:4",
                batch_size=100,
                client_books={"b": {"u1": {"m": "h1"}}, "d": []},
                client_cursor=500,
                client_batch_size=250,
            )

        _, kwargs = mock_post.call_args
        body = kwargs["body"]
        assert body["client_cursor"] == 500
        assert body["client_batch_size"] == 250
        assert body["library_id"] == "8"

    def test_retry_on_500_error(self, rest_client_instance, monkeypatch):
        sleeps = []

        def fake_sleep(delay):
            sleeps.append(delay)

        results = [
            make_http_result(500, {"error": "Internal error"}),
            make_http_result(500, {"error": "Internal error"}),
            make_http_result(200, {"status": "ok"}),
        ]

        monkeypatch.setattr(rest_client.time, "sleep", fake_sleep)

        with patch.object(rest_client_instance.http, "request", side_effect=results) as mock_request:
            response, body = rest_client_instance._request("GET", "/test")

        assert response["status"] == "200"
        assert body["status"] == "ok"
        assert mock_request.call_count == 3
        assert sleeps

    def test_retry_on_429_respects_retry_after(self, rest_client_instance, monkeypatch):
        sleeps = []

        def fake_sleep(delay):
            sleeps.append(delay)

        results = [
            make_http_result(429, {"error": "rate limit"}),
            make_http_result(200, {"status": "ok"}),
        ]
        results[0][0]["retry-after"] = "2"

        monkeypatch.setattr(rest_client.time, "sleep", fake_sleep)

        with patch.object(rest_client_instance.http, "request", side_effect=results) as mock_request:
            response, body = rest_client_instance._request("GET", "/test")

        assert response["status"] == "200"
        assert body["status"] == "ok"
        assert mock_request.call_count == 2
        assert sleeps and max(sleeps) >= 1


class TestRestApiClientMethods:
    def test_get_libraries(self, rest_client_instance):
        with patch.object(
            rest_client_instance,
            "get",
            return_value={"libraries": [{"id": "1"}, {"id": "2"}]},
        ):
            result = rest_client_instance.get_libraries()
        assert isinstance(result, list)
        assert len(result) == 2

    def test_create_library_requires_calibre_library_uuid(self, rest_client_instance):
        with pytest.raises(rest_client.RestApiError):
            rest_client_instance.create_library("New Library")

    def test_create_library(self, rest_client_instance):
        with patch.object(
            rest_client_instance,
            "post",
            return_value={"id": "new-lib-123", "name": "New Library"},
        ) as mock_post:
            result = rest_client_instance.create_library(
                "New Library",
                calibre_library_uuid="11111111-2222-3333-4444-555555555555",
            )

        assert result["id"] == "new-lib-123"
        _, args, kwargs = mock_post.mock_calls[0]
        assert args[0] == "/libraries"
        assert kwargs["body"]["calibre_library_uuid"] == "11111111-2222-3333-4444-555555555555"

    def test_get_library_uses_uuid_endpoint(self, rest_client_instance):
        with patch.object(
            rest_client_instance,
            "get",
            return_value={
                "id": "1",
                "name": "Library 1",
                "calibre_library_uuid": "11111111-2222-3333-4444-555555555555",
            },
        ) as mock_get:
            result = rest_client_instance.get_library("11111111222233334444555555555555")

        assert result["id"] == "1"
        assert result["calibre_library_uuid"] == "11111111-2222-3333-4444-555555555555"
        _, args, _ = mock_get.mock_calls[0]
        assert args[0] == "/libraries/uuid/11111111-2222-3333-4444-555555555555"

    def test_get_sync(self, rest_client_instance):
        with patch.object(rest_client_instance, "get", return_value={"changes": [], "new_cursor": "n"}) as mock_get:
            result = rest_client_instance.get_sync(
                cursor="abc",
                limit=10,
                library_id="123",
                calibre_library_uuid="11111111-2222-3333-4444-555555555555",
                include_inventory=True,
            )

        assert result["new_cursor"] == "n"
        _, args, kwargs = mock_get.mock_calls[0]
        assert args[0] == "/sync"
        assert kwargs["params"]["cursor"] == "abc"
        assert kwargs["params"]["include_inventory"] is True

    def test_upload_cover(self, rest_client_instance):
        cover_data = b"fake_cover_image_data"
        with patch("urllib.request.urlopen", return_value=DummyUrlOpenResponse(200, b'{\"status\":\"uploaded\",\"cover_hash\":\"abc123\"}')) as mock_urlopen:
            result = rest_client_instance.upload_cover(
                calibre_book_id=123,
                library_id=None,
                cover_data=cover_data,
                idempotency_key="idem-cover-123",
                cover_hash="abc123",
                item_uuid="123",
                calibre_library_uuid="lib-uuid",
            )

        assert result["status"] == "uploaded"
        request = mock_urlopen.call_args.args[0]
        assert request.headers.get("X-cover-hash") == "abc123"
        assert request.headers.get("X-idempotency-key") == "idem-cover-123"
        assert request.full_url == "https://api.example.com/api/items/uuid/123/cover?calibre_library_uuid=lib-uuid"

    def test_upload_file_delegates_to_presigned_flow(self, rest_client_instance):
        with patch.object(rest_client_instance, "_is_presigned_upload_enabled", return_value=True), patch.object(
            rest_client_instance,
            "_upload_file_via_presigned_flow",
            return_value={"status": "verified", "file_hash": "sha256:abc123"},
        ) as mock_upload:
            result = rest_client_instance.upload_file(
                upload_url="ignored-by-presigned",
                file_data=b"ebook binary",
                file_hash="sha256:abc123",
                file_name="ebook.epub",
                item_uuid="book-uuid",
                file_format="EPUB",
                library_id="1",
            )

        assert result["status"] == "verified"
        assert mock_upload.called

    def test_upload_file_presigned_failure_has_no_legacy_fallback(self, rest_client_instance):
        with patch.object(rest_client_instance, "_is_presigned_upload_enabled", return_value=True), patch.object(
            rest_client_instance,
            "_upload_file_via_presigned_flow",
            side_effect=rest_client.RestApiError("boom"),
        ):
            with pytest.raises(rest_client.RestApiError):
                rest_client_instance.upload_file(
                    upload_url="ignored-by-presigned",
                    file_data=b"ebook binary",
                    file_hash="sha256:abc123",
                    file_name="ebook.epub",
                    item_uuid="book-uuid",
                    file_format="EPUB",
                    library_id="1",
                )


class TestRestApiClientErrorHandling:
    def test_401_unauthorized(self, rest_client_instance):
        with patch.object(
            rest_client_instance.http,
            "request",
            return_value=make_http_result(401, {"error": "Unauthorized"}),
        ):
            with pytest.raises(rest_client.RestApiError) as exc_info:
                rest_client_instance._request("GET", "/test")
        assert exc_info.value.status_code == 401

    def test_403_forbidden(self, rest_client_instance):
        with patch.object(
            rest_client_instance.http,
            "request",
            return_value=make_http_result(403, {"error": "Forbidden"}),
        ):
            with pytest.raises(rest_client.RestApiError) as exc_info:
                rest_client_instance._request("GET", "/test")
        assert exc_info.value.status_code == 403

    def test_network_error(self, rest_client_instance):
        with patch.object(rest_client_instance.http, "request", side_effect=OSError("network down")):
            with pytest.raises(rest_client.RestApiError):
                rest_client_instance._request("GET", "/test")
