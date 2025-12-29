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

    def tearDown(self):
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = self.orig_store

    def test_show_goodreads_features_default_false(self):
        assert not cfg.show_goodreads_features()

    def test_update_isbn_never(self):
        book = {'calibre_isbn': '111'}
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = cfg.plugin_prefs[cfg.STORE_PLUGIN].copy()
        cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_UPDATE_ISBN] = 'NEVER'
        update_calibre_isbn_if_required(book, '222')
        self.assertEqual(book['calibre_isbn'], '111')

    def test_update_isbn_always(self):
        book = {'calibre_isbn': '111'}
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = cfg.plugin_prefs[cfg.STORE_PLUGIN].copy()
        cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_UPDATE_ISBN] = 'ALWAYS'
        update_calibre_isbn_if_required(book, '222')
        self.assertEqual(book['calibre_isbn'], '222')

    def test_update_isbn_if_missing(self):
        book = {'calibre_isbn': ''}
        cfg.plugin_prefs[cfg.STORE_PLUGIN] = cfg.plugin_prefs[cfg.STORE_PLUGIN].copy()
        cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_UPDATE_ISBN] = 'AUTO'
        update_calibre_isbn_if_required(book, '333')
        self.assertEqual(book['calibre_isbn'], '333')


class SearchableAuthorTest(unittest.TestCase):
    def test_unknown_author_blank(self):
        self.assertEqual(get_searchable_author(_('Unknown')), '')

    def test_simple_name_trim(self):
        self.assertEqual(get_searchable_author('John Doe'), 'John Doe')

    def test_ln_fn_reordering(self):
        result = get_searchable_author('Doe, John')
        self.assertEqual(result, 'John Doe')

    def test_multiple_authors(self):
        self.assertEqual(get_searchable_author('Smith, Alice & Doe, John'), 'Alice')


if __name__ == '__main__':
    unittest.main()
