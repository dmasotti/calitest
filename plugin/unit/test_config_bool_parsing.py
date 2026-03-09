from calibre_plugins.sync_calimob import config as cfg
from calibre_plugins.sync_calimob import sync_worker
import json


def test_parse_bool_pref_accepts_common_string_values():
    assert cfg.parse_bool_pref('true') is True
    assert cfg.parse_bool_pref('1') is True
    assert cfg.parse_bool_pref('yes') is True
    assert cfg.parse_bool_pref('on') is True
    assert cfg.parse_bool_pref('false') is False
    assert cfg.parse_bool_pref('0') is False
    assert cfg.parse_bool_pref('no') is False
    assert cfg.parse_bool_pref('off') is False
    assert cfg.parse_bool_pref('') is False


def test_parse_bool_pref_handles_none_and_numeric_with_default():
    assert cfg.parse_bool_pref(None, default=True) is True
    assert cfg.parse_bool_pref(None, default=False) is False
    assert cfg.parse_bool_pref(1) is True
    assert cfg.parse_bool_pref(0) is False


def test_sync_flags_loaded_from_json_file_bool_values(tmp_path, monkeypatch):
    prefs_file = tmp_path / "sync_calimob.json"
    prefs_file.write_text(json.dumps({
        cfg.STORE_PLUGIN: {
            cfg.KEY_SYNC_FILES_ENABLED: False,
            cfg.KEY_SYNC_COVERS_ENABLED: False,
        }
    }))

    loaded = json.loads(prefs_file.read_text())
    monkeypatch.setattr(cfg, "plugin_prefs", loaded, raising=False)

    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    assert worker._sync_files_enabled() is False
    assert worker._sync_covers_enabled() is False


def test_sync_flags_loaded_from_json_file_legacy_string_values(tmp_path, monkeypatch):
    prefs_file = tmp_path / "sync_calimob.json"
    prefs_file.write_text(json.dumps({
        cfg.STORE_PLUGIN: {
            cfg.KEY_SYNC_FILES_ENABLED: "false",
            cfg.KEY_SYNC_COVERS_ENABLED: "off",
        }
    }))

    loaded = json.loads(prefs_file.read_text())
    monkeypatch.setattr(cfg, "plugin_prefs", loaded, raising=False)

    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    assert worker._sync_files_enabled() is False
    assert worker._sync_covers_enabled() is False


def test_sync_flags_library_mapping_precedence_over_global(monkeypatch):
    prefs = {
        cfg.STORE_PLUGIN: {
            cfg.KEY_SYNC_FILES_ENABLED: True,
            cfg.KEY_SYNC_COVERS_ENABLED: True,
        },
        cfg.STORE_LIBRARY_MAPPINGS: {
            'lib-x': {
                cfg.KEY_SYNC_FILES_ENABLED: 'false',
                cfg.KEY_SYNC_COVERS_ENABLED: 'off',
            }
        },
    }
    monkeypatch.setattr(cfg, "plugin_prefs", prefs, raising=False)

    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    worker.library_id = 'lib-x'
    worker.mapping = prefs[cfg.STORE_LIBRARY_MAPPINGS]['lib-x']
    assert worker._sync_files_enabled() is False
    assert worker._sync_covers_enabled() is False
