from __future__ import annotations

import copy
import types
from unittest.mock import Mock

import pytest

from calibre_plugins.sync_calimob import config as cfg
from calibre_plugins.sync_calimob import rest_client as rest_client_module


class _TextInput:
    def __init__(self, value: str = ""):
        self._value = value
        self.enabled = True

    def text(self):
        return self._value

    def setText(self, value):
        self._value = str(value)

    def setEnabled(self, enabled):
        self.enabled = bool(enabled)


class _CheckBox:
    def __init__(self, checked=False):
        self._checked = bool(checked)

    def isChecked(self):
        return self._checked

    def setChecked(self, checked):
        self._checked = bool(checked)


@pytest.fixture(autouse=True)
def isolated_plugin_prefs(monkeypatch):
    prefs = {
        cfg.STORE_PLUGIN: copy.deepcopy(dict(cfg.DEFAULT_STORE_VALUES)),
        cfg.STORE_USERS: {},
        cfg.STORE_LIBRARY_MAPPINGS: {},
        cfg.STORE_BOOK_UUID_CACHE: {},
    }
    monkeypatch.setattr(cfg, "plugin_prefs", prefs)
    return prefs


def _make_connection_widget(endpoint: str, token: str):
    widget = types.SimpleNamespace()
    widget._rest_endpoint_input = _TextInput(endpoint)
    widget._rest_token_input = _TextInput(token)
    widget.plugin_action = types.SimpleNamespace(gui=None)
    widget._refresh_device_token_ui = Mock()
    return widget


def test_test_connection_prioritizes_device_token_and_sets_status(isolated_plugin_prefs, monkeypatch):
    calls = {"info": [], "error": []}
    captured = {"token": None}

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            captured["token"] = cfg.plugin_prefs[cfg.STORE_PLUGIN].get(cfg.KEY_DEVICE_TOKEN) or cfg.plugin_prefs[
                cfg.STORE_PLUGIN
            ].get(cfg.KEY_REST_TOKEN)

        def _get_discovery(self, force=False):
            return {"api_url": "https://api.example.com/api"}

        def get_libraries(self):
            return [{"id": 1}]

    monkeypatch.setattr(rest_client_module, "RestApiClient", _FakeClient)
    monkeypatch.setattr(cfg, "info_dialog", lambda *args, **kwargs: calls["info"].append((args, kwargs)))
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
    store[cfg.KEY_REST_TOKEN] = "stored-manual-token"
    store[cfg.KEY_DEVICE_TOKEN] = "device-token-xyz"
    store[cfg.KEY_DEVICE_TOKEN_STATUS] = "unknown"
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

    widget = _make_connection_widget("https://api.example.com/api", "manual-token-ui")
    cfg.ConfigWidget.test_rest_connection(widget)

    assert captured["token"] == "device-token-xyz"
    assert cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_DEVICE_TOKEN_STATUS] == "authorized"
    assert len(calls["info"]) == 1
    assert len(calls["error"]) == 0


def test_test_connection_validates_missing_endpoint(isolated_plugin_prefs, monkeypatch):
    calls = {"error": []}
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    widget = _make_connection_widget("", "manual-token-ui")
    cfg.ConfigWidget.test_rest_connection(widget)

    assert len(calls["error"]) == 1
    assert "Please enter an endpoint URL" in calls["error"][0][0][2]


def test_test_connection_validates_missing_token(isolated_plugin_prefs, monkeypatch):
    calls = {"error": []}
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
    store[cfg.KEY_DEVICE_TOKEN] = ""
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

    widget = _make_connection_widget("https://api.example.com/api", "")
    cfg.ConfigWidget.test_rest_connection(widget)

    assert len(calls["error"]) == 1
    assert "Please enter an API token or authorize via browser" in calls["error"][0][0][2]


def test_test_connection_restores_prefs_after_failure(isolated_plugin_prefs, monkeypatch):
    calls = {"error": []}
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def _get_discovery(self, force=False):
            raise RuntimeError("boom")

    monkeypatch.setattr(rest_client_module, "RestApiClient", _FakeClient)

    store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
    store[cfg.KEY_REST_ENDPOINT] = "https://original.example/api"
    store[cfg.KEY_REST_TOKEN] = "original-manual-token"
    store[cfg.KEY_DEVICE_TOKEN] = "original-device-token"
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

    widget = _make_connection_widget("https://temp.example/api", "temp-manual-token")
    cfg.ConfigWidget.test_rest_connection(widget)

    assert cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_REST_ENDPOINT] == "https://original.example/api"
    assert cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_REST_TOKEN] == "original-manual-token"
    assert cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_DEVICE_TOKEN] == "original-device-token"
    assert len(calls["error"]) == 1


def test_open_advanced_settings_updates_shared_controls_without_overwriting_endpoint(isolated_plugin_prefs, monkeypatch):
    calls = {"info": [], "error": []}
    monkeypatch.setattr(cfg, "info_dialog", lambda *args, **kwargs: calls["info"].append((args, kwargs)))
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))
    monkeypatch.setattr(cfg, "QDialog", type("QDialog", (), {"Accepted": 1}))

    class _Dialog:
        def __init__(self, *_args, **_kwargs):
            pass

        def exec_(self):
            return 1

        def get_values(self):
            return {
                cfg.KEY_AUTO_SYNC_ENABLED: True,
                cfg.KEY_AUTO_SYNC_INTERVAL_MINUTES: 45,
                cfg.KEY_HTTP_TIMEOUT: 25,
            }

    monkeypatch.setattr(cfg, "SyncAdvancedSettingsDialog", _Dialog)

    store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
    store[cfg.KEY_REST_ENDPOINT] = "https://keep.this/api"
    store[cfg.KEY_REST_TOKEN] = "keep-token"
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

    widget = types.SimpleNamespace()
    widget._auto_sync_enabled_global = _CheckBox(False)
    widget._auto_sync_interval_global = _TextInput("30")
    widget._rest_endpoint_input = _TextInput("https://keep.this/api")
    widget._rest_token_input = _TextInput("keep-token")

    cfg.ConfigWidget._open_advanced_sync_settings_dialog(widget)

    assert cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_REST_ENDPOINT] == "https://keep.this/api"
    assert cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_REST_TOKEN] == "keep-token"
    assert cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_HTTP_TIMEOUT] == 25
    assert widget._auto_sync_enabled_global.isChecked() is True
    assert widget._auto_sync_interval_global.text() == "45"
    assert widget._auto_sync_interval_global.enabled is True
    assert len(calls["info"]) == 0
    assert len(calls["error"]) == 0


def test_advanced_dialog_on_accept_keeps_modal_open_on_validation_error(monkeypatch):
    calls = {"error": []}
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    accepted = {"value": False}
    dialog = types.SimpleNamespace()
    dialog.get_values = Mock(side_effect=ValueError("bad value"))
    dialog._on_save = None
    dialog.accept = lambda: accepted.__setitem__("value", True)

    cfg.SyncAdvancedSettingsDialog._on_accept(dialog)

    assert accepted["value"] is False
    assert len(calls["error"]) == 1


def test_advanced_dialog_on_accept_keeps_modal_open_on_save_error(monkeypatch):
    calls = {"error": []}
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    accepted = {"value": False}
    dialog = types.SimpleNamespace()
    dialog.get_values = Mock(return_value={cfg.KEY_HTTP_TIMEOUT: 25})
    dialog._on_save = Mock(side_effect=RuntimeError("save failed"))
    dialog.accept = lambda: accepted.__setitem__("value", True)

    cfg.SyncAdvancedSettingsDialog._on_accept(dialog)

    assert accepted["value"] is False
    assert len(calls["error"]) == 1


def test_advanced_dialog_get_values_rejects_out_of_range_client_batch():
    dialog = types.SimpleNamespace()
    dialog._parse_int = cfg.SyncAdvancedSettingsDialog._parse_int.__get__(dialog, cfg.SyncAdvancedSettingsDialog)
    dialog._discovery_url = _TextInput("")
    dialog._http_timeout = _TextInput("30")
    dialog._upload_timeout = _TextInput("120")
    dialog._discovery_ttl = _TextInput("3600")
    dialog._sync_batch = _TextInput("100")
    dialog._pull_limit = _TextInput("100")
    dialog._v5_client_batch = _TextInput("1")  # invalid (min 50)
    dialog._v5_server_batch = _TextInput("100")
    dialog._v5_resume_ttl = _TextInput("86400")
    dialog._cover_batch_max = _TextInput(str(1024 * 1024))
    dialog._cover_single_max = _TextInput(str(256 * 1024))
    dialog._file_chunk = _TextInput(str(1024 * 1024))
    dialog._debug_logs = _CheckBox(False)
    dialog._auto_sync_enabled = _CheckBox(True)
    dialog._auto_sync_minutes = _TextInput("30")

    with pytest.raises(ValueError):
        cfg.SyncAdvancedSettingsDialog.get_values(dialog)


def test_advanced_dialog_get_values_does_not_include_endpoint_or_token():
    dialog = types.SimpleNamespace()
    dialog._parse_int = cfg.SyncAdvancedSettingsDialog._parse_int.__get__(dialog, cfg.SyncAdvancedSettingsDialog)
    dialog._discovery_url = _TextInput("https://disc.example")
    dialog._http_timeout = _TextInput("30")
    dialog._upload_timeout = _TextInput("120")
    dialog._discovery_ttl = _TextInput("3600")
    dialog._sync_batch = _TextInput("100")
    dialog._pull_limit = _TextInput("100")
    dialog._v5_client_batch = _TextInput("100")
    dialog._v5_server_batch = _TextInput("100")
    dialog._v5_resume_ttl = _TextInput("86400")
    dialog._cover_batch_max = _TextInput(str(1024 * 1024))
    dialog._cover_single_max = _TextInput(str(256 * 1024))
    dialog._file_chunk = _TextInput(str(1024 * 1024))
    dialog._debug_logs = _CheckBox(False)
    dialog._auto_sync_enabled = _CheckBox(True)
    dialog._auto_sync_minutes = _TextInput("30")

    values = cfg.SyncAdvancedSettingsDialog.get_values(dialog)

    assert cfg.KEY_REST_ENDPOINT not in values
    assert cfg.KEY_REST_TOKEN not in values


def test_advanced_dialog_get_values_includes_file_and_cover_sync_flags():
    dialog = types.SimpleNamespace()
    dialog._parse_int = cfg.SyncAdvancedSettingsDialog._parse_int.__get__(dialog, cfg.SyncAdvancedSettingsDialog)
    dialog._discovery_url = _TextInput("https://disc.example")
    dialog._http_timeout = _TextInput("30")
    dialog._upload_timeout = _TextInput("120")
    dialog._discovery_ttl = _TextInput("3600")
    dialog._sync_batch = _TextInput("100")
    dialog._pull_limit = _TextInput("100")
    dialog._v5_client_batch = _TextInput("100")
    dialog._v5_server_batch = _TextInput("100")
    dialog._v5_resume_ttl = _TextInput("86400")
    dialog._cover_batch_max = _TextInput(str(1024 * 1024))
    dialog._cover_single_max = _TextInput(str(256 * 1024))
    dialog._file_chunk = _TextInput(str(1024 * 1024))
    dialog._debug_logs = _CheckBox(False)
    dialog._auto_sync_enabled = _CheckBox(True)
    dialog._auto_sync_minutes = _TextInput("30")
    dialog._sync_files_enabled = _CheckBox(False)
    dialog._sync_covers_enabled = _CheckBox(False)

    values = cfg.SyncAdvancedSettingsDialog.get_values(dialog)

    assert values[cfg.KEY_SYNC_FILES_ENABLED] is False
    assert values[cfg.KEY_SYNC_COVERS_ENABLED] is False


def test_invalidate_discovery_cache_clears_cache_and_refreshes(isolated_plugin_prefs, monkeypatch):
    import calibre.gui2 as gui2

    calls = {"info": [], "error": []}
    monkeypatch.setattr(gui2, "info_dialog", lambda *args, **kwargs: calls["info"].append((args, kwargs)))
    monkeypatch.setattr(gui2, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def _get_discovery(self, force=False):
            return {"api_url": "https://api.example.com/api"}

    monkeypatch.setattr(rest_client_module, "RestApiClient", _FakeClient)

    store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
    store[cfg.KEY_DISCOVERY_CACHE] = {"ts": 123, "data": {"api_url": "https://old.example/api"}}
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

    widget = types.SimpleNamespace()
    widget.plugin_action = types.SimpleNamespace(gui=None)
    widget._refresh_discovery_status = Mock()

    cfg.ConfigWidget.invalidate_discovery_cache(widget)

    assert cfg.KEY_DISCOVERY_CACHE not in cfg.plugin_prefs[cfg.STORE_PLUGIN]
    widget._refresh_discovery_status.assert_called_once_with(force=True)
    assert len(calls["info"]) == 1
    assert len(calls["error"]) == 0


def test_generate_and_revoke_device_token_flow(isolated_plugin_prefs, monkeypatch):
    import calibre.gui2 as gui2

    monkeypatch.setattr(gui2, "question_dialog", lambda *args, **kwargs: True)
    info_calls = []
    monkeypatch.setattr(gui2, "info_dialog", lambda *args, **kwargs: info_calls.append((args, kwargs)))
    monkeypatch.setattr(gui2, "error_dialog", lambda *args, **kwargs: None)

    fake_uuid_mod = types.SimpleNamespace(uuid4=lambda: "11111111-2222-3333-4444-555555555555")
    monkeypatch.setitem(__import__("sys").modules, "uuid", fake_uuid_mod)

    store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
    store[cfg.KEY_DEVICE_TOKEN] = ""
    store[cfg.KEY_REST_ENDPOINT] = ""  # skip server revoke call
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

    widget = types.SimpleNamespace()

    token = cfg.ConfigWidget.generate_device_token(widget)
    assert token == "11111111-2222-3333-4444-555555555555"
    assert cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_DEVICE_TOKEN] == token
    assert cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_DEVICE_TOKEN_STATUS] == "unknown"

    cfg.ConfigWidget.revoke_device_token(widget)
    assert cfg.KEY_DEVICE_TOKEN not in cfg.plugin_prefs[cfg.STORE_PLUGIN]
    assert cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_DEVICE_TOKEN_STATUS] == "unknown"
    assert len(info_calls) == 1
