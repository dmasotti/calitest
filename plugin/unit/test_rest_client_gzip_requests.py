import gzip
from unittest.mock import Mock

from calibre_plugins.sync_calimob.rest_client import RestApiClient


def _make_client():
    gui = Mock()
    gui.status_bar = Mock()
    gui.status_bar.showMessage = Mock()
    gui.status_bar.clearMessage = Mock()
    client = RestApiClient(gui)
    client.token = "test-token-123"
    client._raw_discovery_endpoint = "https://api.example.com"
    return client


def test_sync_json_request_is_gzipped_when_large(monkeypatch):
    monkeypatch.setenv("CALIMOB_GZIP_JSON_REQUESTS", "1")
    monkeypatch.setenv("CALIMOB_GZIP_MIN_BYTES", "128")

    client = _make_client()
    calls = []

    def fake_request(url, method, body, headers):
        calls.append({"url": url, "method": method, "body": body, "headers": dict(headers)})
        return {"status": "200"}, b'{"ok": true}'

    client.http.request = fake_request
    payload = {"items": [{"n": i, "txt": "x" * 64} for i in range(50)]}

    response, body = client._request("POST", "/sync/v5", body=payload, success_status=200)

    assert response["status"] == "200"
    assert body["ok"] is True
    assert len(calls) == 1
    assert calls[0]["headers"].get("Content-Encoding") == "gzip"
    assert "X-Original-Content-Length" in calls[0]["headers"]
    assert gzip.decompress(calls[0]["body"]).decode("utf-8").startswith('{"items":')


def test_gzip_request_falls_back_to_plain_json_on_415(monkeypatch):
    monkeypatch.setenv("CALIMOB_GZIP_JSON_REQUESTS", "1")
    monkeypatch.setenv("CALIMOB_GZIP_MIN_BYTES", "128")

    client = _make_client()
    calls = []

    def fake_request(url, method, body, headers):
        calls.append({"url": url, "method": method, "body": body, "headers": dict(headers)})
        if len(calls) == 1:
            return {"status": "415"}, b'{"error":"unsupported encoding"}'
        return {"status": "200"}, b'{"ok": true}'

    client.http.request = fake_request
    payload = {"items": [{"n": i, "txt": "y" * 64} for i in range(50)]}

    response, body = client._request("POST", "/sync/v5", body=payload, success_status=200)

    assert response["status"] == "200"
    assert body["ok"] is True
    assert len(calls) == 2
    assert calls[0]["headers"].get("Content-Encoding") == "gzip"
    assert "Content-Encoding" not in calls[1]["headers"]
    assert "X-Calimob-No-Gzip" not in calls[1]["headers"]
    assert calls[1]["body"].decode("utf-8").startswith('{"items":')


def test_non_sync_request_is_not_gzipped_even_when_large(monkeypatch):
    monkeypatch.setenv("CALIMOB_GZIP_JSON_REQUESTS", "1")
    monkeypatch.setenv("CALIMOB_GZIP_MIN_BYTES", "128")

    client = _make_client()
    calls = []

    def fake_request(url, method, body, headers):
        calls.append({"url": url, "method": method, "body": body, "headers": dict(headers)})
        return {"status": "200"}, b'{"ok": true}'

    client.http.request = fake_request
    payload = {"items": [{"n": i, "txt": "z" * 64} for i in range(50)]}

    response, body = client._request("POST", "/libraries", body=payload, success_status=200)

    assert response["status"] == "200"
    assert body["ok"] is True
    assert len(calls) == 1
    assert "Content-Encoding" not in calls[0]["headers"]


def test_binary_cover_upload_is_not_gzipped(monkeypatch):
    monkeypatch.setenv("CALIMOB_GZIP_JSON_REQUESTS", "1")
    monkeypatch.setenv("CALIMOB_GZIP_MIN_BYTES", "1")

    client = _make_client()
    calls = []

    def fake_request(url, method, body, headers):
        calls.append({"url": url, "method": method, "body": body, "headers": dict(headers)})
        return {"status": "200"}, b'{"ok": true}'

    client.http.request = fake_request
    cover_data = b"\x00\x01\x02" * 8192

    response, body = client._request(
        "PUT",
        "/items/uuid/book-1/cover",
        body=cover_data,
        headers={"Content-Type": "image/jpeg"},
        success_status=200,
    )

    assert response["status"] == "200"
    assert body["ok"] is True
    assert len(calls) == 1
    assert calls[0]["body"] == cover_data
    assert "Content-Encoding" not in calls[0]["headers"]


def test_gzip_response_body_is_decoded_when_transport_returns_compressed_bytes(monkeypatch):
    monkeypatch.setenv("CALIMOB_GZIP_JSON_REQUESTS", "1")
    monkeypatch.setenv("CALIMOB_GZIP_MIN_BYTES", "1")

    client = _make_client()

    def fake_request(url, method, body, headers):
        compressed = gzip.compress(b'{"ok": true, "mode": "compressed"}', compresslevel=6)
        return {"status": "200", "content-encoding": "gzip"}, compressed

    client.http.request = fake_request
    response, body = client._request("POST", "/sync/v5", body={"x": "y"}, success_status=200)

    assert response["status"] == "200"
    assert body["ok"] is True
    assert body["mode"] == "compressed"
