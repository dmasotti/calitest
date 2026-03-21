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
        # cli.cfg.plugin_prefs must be the FakeJSONConfig with the seeded data
        assert isinstance(cli.cfg.plugin_prefs, FakeJSONConfig)
        assert cli.cfg.plugin_prefs[package_cfg.STORE_PLUGIN]["restEndpoint"] == "http://caliserver.test/api"
        # The calibre_plugins.sync_calimob.config namespace must also be updated.
        # In production cli.cfg IS calibre_plugins.sync_calimob.config; in the test
        # harness they may be two separate module instances of the same file.
        pkg_ns = sys.modules.get("calibre_plugins.sync_calimob.config")
        if pkg_ns is not None:
            assert isinstance(pkg_ns.plugin_prefs, FakeJSONConfig), (
                "calibre_plugins.sync_calimob.config.plugin_prefs not updated by _prepare_config"
            )
    finally:
        cli.cfg.plugin_prefs = original_local_prefs
        package_cfg.plugin_prefs = original_package_prefs
        pkg_ns = sys.modules.get("calibre_plugins.sync_calimob.config")
        if pkg_ns is not None and pkg_ns is not cli.cfg:
            pkg_ns.plugin_prefs = original_package_prefs
