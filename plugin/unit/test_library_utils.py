"""Unit tests for library_utils.py - Pure functions without external dependencies."""

import os
import sqlite3
import types
from pathlib import Path

import pytest
from unittest.mock import Mock, patch

# Import library_utils functions
import importlib.util

plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'
library_utils_path = plugin_path / 'library_utils.py'
spec = importlib.util.spec_from_file_location('library_utils', str(library_utils_path))
library_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(library_utils)


def _create_metadata_db(path, library_id='test-uuid-123', name='Test Library'):
    db_path = Path(path) / 'metadata.db'
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute('CREATE TABLE IF NOT EXISTS library_id (uuid TEXT)')
    cur.execute('CREATE TABLE IF NOT EXISTS preferences (key TEXT, val TEXT)')
    if library_id is not None:
        cur.execute('INSERT INTO library_id (uuid) VALUES (?)', (library_id,))
    if name is not None:
        cur.execute('INSERT INTO preferences (key, val) VALUES (\'library_name\', ?)', (f'"{name}"',))
    conn.commit()
    conn.close()
    return str(path)


class TestReadLibraryMetadata:
    """Test _read_library_metadata() function."""

    def test_with_metadata_db(self, tmp_path):
        library_id = 'test-uuid-123'
        name = 'Test Library'
        _create_metadata_db(tmp_path, library_id=library_id, name=name)

        info = library_utils._read_library_metadata(str(tmp_path))

        assert info['id'] == library_id
        assert info['name'] == name
        assert info['path'] == str(tmp_path)

    def test_without_metadata_db(self, tmp_path):
        info = library_utils._read_library_metadata(str(tmp_path))

        assert info['id'] is not None
        assert info['name'] is not None
        assert info['path'] == str(tmp_path)

    def test_without_library_id(self, tmp_path):
        name = 'Test Library'
        _create_metadata_db(tmp_path, library_id=None, name=name)

        info = library_utils._read_library_metadata(str(tmp_path))

        assert info['id'] is not None
        assert info['name'] == name


class TestNormalizePath:
    """Test _normalize_path() function."""

    def test_absolute_path(self):
        path = '/tmp/test/library'
        normalized = library_utils._normalize_path(path)

        assert normalized == os.path.abspath(path)

    def test_home_expansion(self):
        path = '~/test/library'
        normalized = library_utils._normalize_path(path)

        assert normalized == os.path.abspath(os.path.expanduser(path))

    def test_none_path(self):
        normalized = library_utils._normalize_path(None)
        assert normalized is None

    def test_empty_path(self):
        normalized = library_utils._normalize_path('')
        assert normalized is None


class TestGetCalibreLibraryId:
    """Test get_calibre_library_id() function."""

    def test_with_valid_db(self, tmp_path):
        _create_metadata_db(tmp_path, library_id='test-uuid-123')
        db = Mock()
        db.library_path = str(tmp_path)

        library_id = library_utils.get_calibre_library_id(db)

        assert library_id == 'test-uuid-123'

    def test_without_library_id(self, tmp_path):
        _create_metadata_db(tmp_path, library_id=None)
        db = Mock()
        db.library_path = str(tmp_path)

        library_id = library_utils.get_calibre_library_id(db)

        assert library_id is not None


class TestGetCalibreLibraryName:
    """Test get_calibre_library_name() function."""

    def test_with_name_in_db(self, tmp_path):
        name = 'Test Library'
        _create_metadata_db(tmp_path, name=name)
        db = Mock()
        db.library_path = str(tmp_path)

        library_name = library_utils.get_calibre_library_name(db)

        assert library_name == name

    def test_without_name(self, tmp_path):
        _create_metadata_db(tmp_path, name=None)
        db = Mock()
        db.library_path = str(tmp_path)

        library_name = library_utils.get_calibre_library_name(db)

        assert library_name is not None


class TestGetCalibreLibraryIdFromPath:
    """Test get_calibre_library_id_from_path() function."""

    def test_with_valid_path(self, tmp_path):
        _create_metadata_db(tmp_path, library_id='test-uuid-123')

        library_id = library_utils.get_calibre_library_id_from_path(str(tmp_path))

        assert library_id == 'test-uuid-123'

    def test_with_invalid_path(self):
        library_id = library_utils.get_calibre_library_id_from_path('/nonexistent/path')
        assert library_id is not None


class TestCanonicalizeUuid:
    def test_compact_uuid_becomes_canonical(self):
        compact = 'a149568969474a4d80109d00901ab13e'
        canonical = library_utils.canonicalize_uuid(compact)
        assert canonical == 'a1495689-6947-4a4d-8010-9d00901ab13e'

    def test_hyphenated_uuid_returns_lowercase(self):
        value = 'A1495689-6947-4A4D-8010-9D00901AB13E'
        canonical = library_utils.canonicalize_uuid(value)
        assert canonical == 'a1495689-6947-4a4d-8010-9d00901ab13e'

    def test_invalid_uuid_returns_trimmed(self):
        value = 'not-a-valid-uuid'
        canonical = library_utils.canonicalize_uuid(value)
        assert canonical == value

    def test_blank_uuid_returns_none(self):
        assert library_utils.canonicalize_uuid('') is None
        assert library_utils.canonicalize_uuid(None) is None


class TestGetAllCalibreLibraries:
    def _make_gui(self, paths=None):
        gui = types.SimpleNamespace()
        gui.library_paths = paths or []
        gui.library_manager = None
        gui.current_db = None
        return gui

    def test_returns_known_libraries(self, tmp_path):
        lib_one = tmp_path / 'lib-one'
        lib_two = tmp_path / 'lib-two'
        lib_one.mkdir()
        lib_two.mkdir()
        _create_metadata_db(lib_one, library_id='uuid-one', name='Lib One')
        _create_metadata_db(lib_two, library_id='uuid-two', name='Lib Two')

        gui = self._make_gui(paths=[str(lib_one), str(lib_two)])
        libs = library_utils.get_all_calibre_libraries(gui)

        assert len(libs) == 2
        assert any(lib['id'] == 'uuid-one' for lib in libs)
        assert any(lib['id'] == 'uuid-two' for lib in libs)

    def test_uses_config_fallback(self, monkeypatch, tmp_path):
        fallback = tmp_path / 'fallback'
        fallback.mkdir()
        _create_metadata_db(fallback, library_id='uuid-fallback', name='Fallback Lib')

        gui = self._make_gui(paths=[])
        gui.current_db = types.SimpleNamespace(library_path=str(fallback))
        libs = library_utils.get_all_calibre_libraries(gui)

        assert len(libs) == 1
        assert libs[0]['id'] == library_utils.canonicalize_uuid('uuid-fallback')
