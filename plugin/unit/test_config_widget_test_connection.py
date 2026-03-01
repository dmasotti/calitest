from __future__ import annotations

import copy
import types
from unittest.mock import Mock

import pytest

from calibre_plugins.sync_calimob import config as cfg
from calibre_plugins.sync_calimob import rest_client as rest_client_module


class _TextInput:
    def __init__(self, value: str):
        self._value = value

    def text(self):
        return self._value


def _make_dummy_widget(endpoint: str, token: str):
    widget = types.SimpleNamespace()
    widget._rest_endpoint_input = _TextInput(endpoint)
    widget._rest_token_input = _TextInput(token)
    widget.plugin_action = types.SimpleNamespace(gui=None)
    widget._refresh_device_token_ui = Mock()
    return widget


@pytest.fixture
def plugin_store_backup():
    before = copy.deepcopy(dict(cfg.plugin_prefs[cfg.STORE_PLUGIN]))
    yield
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = before


def test_ui_test_connection_discovery_unavailable_but_auth_ok(plugin_store_backup, monkeypatch):
    calls = {"info": [], "error": []}

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def _get_discovery(self, force=False):
            return None

        def get_libraries(self):
            return [{"id": 1}]

    monkeypatch.setattr(rest_client_module, "RestApiClient", _FakeClient)
    monkeypatch.setattr(cfg, "info_dialog", lambda *args, **kwargs: calls["info"].append((args, kwargs)))
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
    store[cfg.KEY_DEVICE_TOKEN] = ""
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

    widget = _make_dummy_widget("https://api.example.com/api", "tok-123")
    cfg.ConfigWidget.test_rest_connection(widget)

    assert len(calls["info"]) == 1
    assert len(calls["error"]) == 0
    msg = calls["info"][0][0][2]
    assert "Discovery unavailable, but direct API authentication is OK" in msg


def test_ui_test_connection_discovery_unavailable_and_auth_fail(plugin_store_backup, monkeypatch):
    calls = {"info": [], "error": []}

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def _get_discovery(self, force=False):
            return None

        def get_libraries(self):
            raise RuntimeError("auth bad")

    monkeypatch.setattr(rest_client_module, "RestApiClient", _FakeClient)
    monkeypatch.setattr(cfg, "info_dialog", lambda *args, **kwargs: calls["info"].append((args, kwargs)))
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
    store[cfg.KEY_DEVICE_TOKEN] = ""
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

    widget = _make_dummy_widget("https://api.example.com/api", "tok-123")
    cfg.ConfigWidget.test_rest_connection(widget)

    assert len(calls["info"]) == 0
    assert len(calls["error"]) == 1
    msg = calls["error"][0][0][2]
    assert "Discovery unavailable and authentication failed" in msg


def test_ui_test_connection_discovery_ok_and_auth_fail(plugin_store_backup, monkeypatch):
    calls = {"info": [], "error": []}

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def _get_discovery(self, force=False):
            return {"api_url": "https://api.example.com/api", "web_url": "https://api.example.com"}

        def get_libraries(self):
            raise RuntimeError("auth bad")

    monkeypatch.setattr(rest_client_module, "RestApiClient", _FakeClient)
    monkeypatch.setattr(cfg, "info_dialog", lambda *args, **kwargs: calls["info"].append((args, kwargs)))
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
    store[cfg.KEY_DEVICE_TOKEN] = ""
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

    widget = _make_dummy_widget("https://api.example.com/api", "tok-123")
    cfg.ConfigWidget.test_rest_connection(widget)

    assert len(calls["info"]) == 0
    assert len(calls["error"]) == 1
    msg = calls["error"][0][0][2]
    assert "Discovery reachable but authentication failed" in msg


def test_ui_test_connection_discovery_exception(plugin_store_backup, monkeypatch):
    calls = {"info": [], "error": []}

    class _FakeClient:
        def __init__(self, *_args, **_kwargs):
            pass

        def _get_discovery(self, force=False):
            raise RuntimeError("discovery down")

        def get_libraries(self):
            return [{"id": 1}]

    monkeypatch.setattr(rest_client_module, "RestApiClient", _FakeClient)
    monkeypatch.setattr(cfg, "info_dialog", lambda *args, **kwargs: calls["info"].append((args, kwargs)))
    monkeypatch.setattr(cfg, "error_dialog", lambda *args, **kwargs: calls["error"].append((args, kwargs)))

    store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
    store[cfg.KEY_DEVICE_TOKEN] = ""
    cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

    widget = _make_dummy_widget("https://api.example.com/api", "tok-123")
    cfg.ConfigWidget.test_rest_connection(widget)

    assert len(calls["info"]) == 0
    assert len(calls["error"]) == 1
    msg = calls["error"][0][0][2]
    assert "Failed to contact discovery" in msg
