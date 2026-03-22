from unittest.mock import Mock, patch

import pytest

from calibre_plugins.sync_calimob import rest_client


def _make_client():
    gui = Mock()
    gui.status_bar = Mock()
    gui.status_bar.showMessage = Mock()
    gui.status_bar.clearMessage = Mock()
    client = rest_client.RestApiClient(gui)
    client.token = "test-token-123"
    client._raw_discovery_endpoint = "https://api.example.com"
    return client


def _ensure_verify_batch_pref_key(monkeypatch):
    key_name = "presignedVerifyBatchEnabled"
    monkeypatch.setattr(
        rest_client.cfg,
        "plugin_prefs",
        {
            rest_client.cfg.STORE_PLUGIN: {},
            rest_client.cfg.STORE_LIBRARY_MAPPINGS: {},
        },
        raising=False,
    )
    monkeypatch.setattr(
        rest_client.cfg,
        "KEY_PRESIGNED_VERIFY_BATCH_ENABLED",
        key_name,
        raising=False,
    )
    defaults = dict(getattr(rest_client.cfg, "DEFAULT_STORE_VALUES", {}) or {})
    defaults[key_name] = False
    monkeypatch.setattr(rest_client.cfg, "DEFAULT_STORE_VALUES", defaults, raising=False)
    if not hasattr(rest_client.cfg, "parse_bool_pref"):
        def _parse_bool_pref(raw, default=False):
            if raw is None:
                return bool(default)
            if isinstance(raw, bool):
                return raw
            val = str(raw).strip().lower()
            if val in ("1", "true", "yes", "on"):
                return True
            if val in ("0", "false", "no", "off", ""):
                return False
            return bool(default)
        monkeypatch.setattr(rest_client.cfg, "parse_bool_pref", _parse_bool_pref, raising=False)
    plugin_store = rest_client.cfg.plugin_prefs.setdefault(rest_client.cfg.STORE_PLUGIN, {})
    plugin_store.setdefault(key_name, False)
    return key_name


def _ensure_verify_enabled_pref_key(monkeypatch):
    key_name = "presignedVerifyEnabled"
    monkeypatch.setattr(
        rest_client.cfg,
        "plugin_prefs",
        {
            rest_client.cfg.STORE_PLUGIN: {},
            rest_client.cfg.STORE_LIBRARY_MAPPINGS: {},
        },
        raising=False,
    )
    monkeypatch.setattr(
        rest_client.cfg,
        "KEY_PRESIGNED_VERIFY_ENABLED",
        key_name,
        raising=False,
    )
    defaults = dict(getattr(rest_client.cfg, "DEFAULT_STORE_VALUES", {}) or {})
    defaults[key_name] = True
    monkeypatch.setattr(rest_client.cfg, "DEFAULT_STORE_VALUES", defaults, raising=False)
    if not hasattr(rest_client.cfg, "parse_bool_pref"):
        def _parse_bool_pref(raw, default=False):
            if raw is None:
                return bool(default)
            if isinstance(raw, bool):
                return raw
            val = str(raw).strip().lower()
            if val in ("1", "true", "yes", "on"):
                return True
            if val in ("0", "false", "no", "off", ""):
                return False
            return bool(default)
        monkeypatch.setattr(rest_client.cfg, "parse_bool_pref", _parse_bool_pref, raising=False)
    plugin_store = rest_client.cfg.plugin_prefs.setdefault(rest_client.cfg.STORE_PLUGIN, {})
    plugin_store.setdefault(key_name, True)
    return key_name


def test_presigned_flow_returns_immediately_after_complete_without_polling(monkeypatch):
    """After start → PUT → complete, the presigned flow must return immediately
    with pending_verify=True, without any polling loop or verify request."""
    client = _make_client()

    class _DummyResponse:
        headers = {"ETag": '"etag-1"'}

        def getcode(self):
            return 200

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    request_log = []

    def _fake_request(method, endpoint, **kwargs):
        request_log.append((method, endpoint))
        if method == "POST" and endpoint == "/sync/uploads/start":
            return ({"status": "200"}, {
                "session_id": "session-nopoll-1",
                "status": "pending",
                "upload_url": "https://upload.example.com/tmp-key",
                "temp_object_key": "tmp-key",
                "final_object_key": "ebooks/abc.epub",
                "storage_provider": "r2",
            })
        if method == "POST" and endpoint == "/sync/uploads/complete":
            return ({"status": "200"}, {"status": "uploaded_unverified"})
        raise AssertionError("Unexpected request: %s %s" % (method, endpoint))

    with patch.object(client, "_request", side_effect=_fake_request):
        result = client._upload_file_via_presigned_flow(
            upload_url="https://api.example.com/api/items/uuid/11111111-2222-3333-4444-555555555555/files/epub?library_id=9",
            file_data=b"ebook binary",
            file_hash="sha256:%s" % ("c" * 64),
            file_name="book.epub",
            urllib_request=Mock(Request=Mock(return_value=object()), urlopen=Mock(return_value=_DummyResponse())),
            urllib_error=Mock(HTTPError=Exception),
        )

    # Must return with pending_verify, no polling
    assert result["status"] == "uploaded_unverified"
    assert result["session_id"] == "session-nopoll-1"
    assert result["pending_verify"] is True
    # Only start + complete, no verify or GET polling
    assert request_log == [("POST", "/sync/uploads/start"), ("POST", "/sync/uploads/complete")]


def test_presigned_verify_batch_uses_plugin_toggle_when_env_unset(monkeypatch):
    client = _make_client()
    key_name = _ensure_verify_batch_pref_key(monkeypatch)
    monkeypatch.setenv("CALIMOB_PRESIGNED_VERIFY_BATCH", "")
    plugin_store = rest_client.cfg.plugin_prefs.setdefault(rest_client.cfg.STORE_PLUGIN, {})

    plugin_store[key_name] = True
    assert client._is_presigned_verify_batch_enabled() is True

    plugin_store[key_name] = False
    assert client._is_presigned_verify_batch_enabled() is False


def test_presigned_verify_batch_env_overrides_plugin_toggle(monkeypatch):
    client = _make_client()
    key_name = _ensure_verify_batch_pref_key(monkeypatch)
    plugin_store = rest_client.cfg.plugin_prefs.setdefault(rest_client.cfg.STORE_PLUGIN, {})
    plugin_store[key_name] = False

    monkeypatch.setenv("CALIMOB_PRESIGNED_VERIFY_BATCH", "1")
    assert client._is_presigned_verify_batch_enabled() is True

    plugin_store[key_name] = True
    monkeypatch.setenv("CALIMOB_PRESIGNED_VERIFY_BATCH", "0")
    assert client._is_presigned_verify_batch_enabled() is False


def test_presigned_verify_enabled_uses_plugin_toggle_when_env_unset(monkeypatch):
    client = _make_client()
    key_name = _ensure_verify_enabled_pref_key(monkeypatch)
    monkeypatch.setenv("CALIMOB_PRESIGNED_VERIFY_ENABLED", "")
    plugin_store = rest_client.cfg.plugin_prefs.setdefault(rest_client.cfg.STORE_PLUGIN, {})

    plugin_store[key_name] = True
    assert client._is_presigned_verify_enabled() is True

    plugin_store[key_name] = False
    assert client._is_presigned_verify_enabled() is False


def test_presigned_verify_enabled_env_overrides_plugin_toggle(monkeypatch):
    client = _make_client()
    key_name = _ensure_verify_enabled_pref_key(monkeypatch)
    plugin_store = rest_client.cfg.plugin_prefs.setdefault(rest_client.cfg.STORE_PLUGIN, {})
    plugin_store[key_name] = False

    monkeypatch.setenv("CALIMOB_PRESIGNED_VERIFY_ENABLED", "1")
    assert client._is_presigned_verify_enabled() is True

    plugin_store[key_name] = True
    monkeypatch.setenv("CALIMOB_PRESIGNED_VERIFY_ENABLED", "0")
    assert client._is_presigned_verify_enabled() is False
