import os
import sys


def test_prepare_config_rebinds_package_and_local_plugin_prefs(monkeypatch, tmp_path):
    from calibre_plugins.sync_calimob import config as package_cfg

    sys.modules.setdefault("config", package_cfg)

    from calibre_plugins.sync_calimob import cli

    original_local_prefs = cli.cfg.plugin_prefs
    original_package_prefs = package_cfg.plugin_prefs
    created = []

    class FakeJSONConfig(dict):
        def __init__(self, name):
            super().__init__()
            self.name = name
            created.append(name)

    config_json = tmp_path / "sync_calimob.json"
    config_json.write_text('{"Caliweb": {"restEndpoint": "http://caliserver.test/api"}}', encoding="utf-8")

    monkeypatch.setattr(cli, "JSONConfig", FakeJSONConfig)

    try:
        cli._prepare_config(config_json=str(config_json))

        assert os.environ.get("CALIBRE_CONFIG_DIRECTORY")
        assert created == ["plugins/sync_calimob"]
        assert cli.cfg.plugin_prefs is package_cfg.plugin_prefs
        assert isinstance(cli.cfg.plugin_prefs, FakeJSONConfig)
    finally:
        cli.cfg.plugin_prefs = original_local_prefs
        package_cfg.plugin_prefs = original_package_prefs
