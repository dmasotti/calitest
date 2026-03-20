from __future__ import division, absolute_import, print_function, unicode_literals

import unittest

import importlib.util
import sys
import types
from pathlib import Path

PLUGIN_DIR = Path(__file__).resolve().parents[3] / 'sync_calimob'

# Minimal Qt stub modules so config/core import succeeds without a GUI.
qt_core = types.SimpleNamespace(
    Qt=type('Qt', (), {'AlignLeft': 0, 'AlignTop': 0}),
    QWidget=type('QWidget', (), {}),
    QVBoxLayout=type('QVBoxLayout', (), {}),
    QLabel=type('QLabel', (), {}),
    QLineEdit=type('QLineEdit', (), {}),
    QGridLayout=type('QGridLayout', (), {}),
    QUrl=type('QUrl', (), {}),
    QGroupBox=type('QGroupBox', (), {}),
    QHBoxLayout=type('QHBoxLayout', (), {}),
    QComboBox=type('QComboBox', (), {}),
    QCheckBox=type('QCheckBox', (), {}),
    QFormLayout=type('QFormLayout', (), {}),
    QIcon=type('QIcon', (), {}),
    QTableWidget=type('QTableWidget', (), {}),
    QTableWidgetItem=type('QTableWidgetItem', (), {}),
    QPushButton=type('QPushButton', (), {}),
    QInputDialog=type('QInputDialog', (), {}),
    QAbstractItemView=type('QAbstractItemView', (), {}),
    QDialog=type('QDialog', (), {}),
    QDialogButtonBox=type('QDialogButtonBox', (), {}),
    QAction=type('QAction', (), {}),
    QToolButton=type('QToolButton', (), {}),
    QSpacerItem=type('QSpacerItem', (), {}),
    QModelIndex=type('QModelIndex', (), {}),
    QFileDialog=type('QFileDialog', (), {}),
    QTimer=type('QTimer', (), {}),
)
qt = types.ModuleType('qt')
qt.core = qt_core
sys.modules['qt'] = qt
sys.modules['qt.core'] = qt_core

pyqt5 = types.ModuleType('PyQt5')
pyqt5.Qt = qt_core
sys.modules['PyQt5'] = pyqt5
sys.modules['PyQt5.Qt'] = qt_core

def _load_module(name):
    spec = importlib.util.spec_from_file_location(name, PLUGIN_DIR / (name.split('.')[-1] + '.py'))
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module

cfg = _load_module('sync_calimob.config')
core = _load_module('sync_calimob.core')
_ = getattr(core, '_', lambda x: x)
get_searchable_author = core.get_searchable_author
update_calibre_isbn_if_required = core.update_calibre_isbn_if_required


class ConfigHelpersTest(unittest.TestCase):
    def setUp(self):
        self.orig_store = dict(cfg.plugin_prefs[cfg.STORE_PLUGIN])
        self.orig_core_store = dict(core.cfg.plugin_prefs[core.cfg.STORE_PLUGIN])

    def tearDown(self):
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = self.orig_store
        core.cfg.plugin_prefs[core.cfg.STORE_PLUGIN] = self.orig_core_store

    def test_remote_feature_toggle_removed(self):
        assert not hasattr(cfg, 'show_remote_features')

    def test_update_isbn_never(self):
        book = {'calibre_isbn': '111'}
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = cfg.plugin_prefs[cfg.STORE_PLUGIN].copy()
        cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_UPDATE_ISBN] = 'NEVER'
        update_calibre_isbn_if_required(book, '222', update_isbn='NEVER')
        self.assertEqual(book['calibre_isbn'], '111')

    def test_update_isbn_always(self):
        book = {'calibre_isbn': '111'}
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = cfg.plugin_prefs[cfg.STORE_PLUGIN].copy()
        cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_UPDATE_ISBN] = 'ALWAYS'
        update_calibre_isbn_if_required(book, '222', update_isbn='ALWAYS')
        self.assertEqual(book['calibre_isbn'], '222')

    def test_update_isbn_if_missing(self):
        book = {'calibre_isbn': ''}
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = cfg.plugin_prefs[cfg.STORE_PLUGIN].copy()
        cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_UPDATE_ISBN] = 'AUTO'
        update_calibre_isbn_if_required(book, '333', update_isbn='AUTO')
        self.assertEqual(book['calibre_isbn'], '333')

    def test_http_helper_repairs_missing_dev_credentials_in_partial_store(self):
        partial_store = {
            core.cfg.KEY_REST_ENDPOINT: 'https://example.test/api',
        }
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = dict(partial_store)
        core.cfg.plugin_prefs[core.cfg.STORE_PLUGIN] = dict(partial_store)

        helper = core.HttpHelper()

        self.assertEqual(helper.devkey_token, core.cfg.DEFAULT_STORE_VALUES[core.cfg.KEY_DEV_TOKEN])
        self.assertEqual(helper.devkey_secret, core.cfg.DEFAULT_STORE_VALUES[core.cfg.KEY_DEV_SECRET])
        repaired_store = core.cfg.plugin_prefs[core.cfg.STORE_PLUGIN]
        self.assertEqual(repaired_store[core.cfg.KEY_DEV_TOKEN], core.cfg.DEFAULT_STORE_VALUES[core.cfg.KEY_DEV_TOKEN])
        self.assertEqual(repaired_store[core.cfg.KEY_DEV_SECRET], core.cfg.DEFAULT_STORE_VALUES[core.cfg.KEY_DEV_SECRET])

    def test_get_plugin_store_repair_preserves_existing_values_and_backfills_defaults(self):
        custom_store = {
            cfg.KEY_REST_ENDPOINT: 'https://custom.example/api',
            cfg.KEY_HTTP_TIMEOUT: 77,
            cfg.KEY_SYNC_FILES_ENABLED: False,
        }
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = dict(custom_store)

        repaired = cfg.get_plugin_store(repair=True)

        self.assertEqual(repaired[cfg.KEY_REST_ENDPOINT], 'https://custom.example/api')
        self.assertEqual(repaired[cfg.KEY_HTTP_TIMEOUT], 77)
        self.assertFalse(repaired[cfg.KEY_SYNC_FILES_ENABLED])
        self.assertEqual(repaired[cfg.KEY_DEV_TOKEN], cfg.DEFAULT_STORE_VALUES[cfg.KEY_DEV_TOKEN])
        self.assertEqual(repaired[cfg.KEY_DEV_SECRET], cfg.DEFAULT_STORE_VALUES[cfg.KEY_DEV_SECRET])
        self.assertEqual(repaired[cfg.KEY_V5_CLIENT_BATCH_SIZE], cfg.DEFAULT_STORE_VALUES[cfg.KEY_V5_CLIENT_BATCH_SIZE])
        self.assertEqual(repaired[cfg.KEY_DISCOVERY_CACHE_TTL], cfg.DEFAULT_STORE_VALUES[cfg.KEY_DISCOVERY_CACHE_TTL])

    def test_get_plugin_store_repair_recovers_from_non_dict_store(self):
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = 'broken-store'

        repaired = cfg.get_plugin_store(repair=True)

        self.assertIsInstance(repaired, dict)
        self.assertEqual(repaired[cfg.KEY_DEV_TOKEN], cfg.DEFAULT_STORE_VALUES[cfg.KEY_DEV_TOKEN])
        self.assertEqual(repaired[cfg.KEY_REST_ENDPOINT], cfg.DEFAULT_STORE_VALUES[cfg.KEY_REST_ENDPOINT])
        self.assertEqual(cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_DEV_SECRET], cfg.DEFAULT_STORE_VALUES[cfg.KEY_DEV_SECRET])

    def test_get_plugin_store_without_repair_does_not_mutate_partial_store(self):
        partial_store = {
            cfg.KEY_REST_ENDPOINT: 'https://readonly.example/api',
        }
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = dict(partial_store)

        loaded = cfg.get_plugin_store(repair=False)

        self.assertEqual(loaded, partial_store)
        self.assertNotIn(cfg.KEY_DEV_TOKEN, cfg.plugin_prefs[cfg.STORE_PLUGIN])


class SearchableAuthorTest(unittest.TestCase):
    def test_unknown_author_blank(self):
        self.assertEqual(get_searchable_author(_('Unknown')), '')

    def test_simple_name_trim(self):
        self.assertEqual(get_searchable_author('John Doe'), 'John Doe')

    def test_ln_fn_reordering(self):
        original = core.tweaks.get('author_sort_copy_method')
        core.tweaks['author_sort_copy_method'] = 'swap'
        try:
            result = get_searchable_author('Doe, John')
        finally:
            if original is None:
                core.tweaks.pop('author_sort_copy_method', None)
            else:
                core.tweaks['author_sort_copy_method'] = original
        self.assertEqual(result, 'John Doe')

    def test_multiple_authors(self):
        self.assertEqual(get_searchable_author('Smith, Alice & Doe, John'), 'Alice')


if __name__ == '__main__':
    unittest.main()
