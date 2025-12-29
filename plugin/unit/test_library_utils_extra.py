import json
import os
import platform
import sqlite3
from pathlib import Path

import pytest

from calibre_plugins.sync_calimob import library_utils


def test_canonicalize_uuid_handles_compact():
    short_uuid = 'a' * 32
    normalized = library_utils.canonicalize_uuid(short_uuid)
    assert normalized == 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


def test_canonicalize_uuid_returns_original_when_invalid():
    invalid = 'not-a-uuid'
    assert library_utils.canonicalize_uuid(invalid) == invalid


def test_normalize_path_expands_tilde(tmp_path, monkeypatch):
    sample = tmp_path / 'foo'
    monkeypatch.setenv('HOME', str(tmp_path))
    value = library_utils._normalize_path('~/foo/bar')
    assert os.path.isabs(value)


def test_read_library_metadata_without_db(tmp_path):
    info = library_utils._read_library_metadata(str(tmp_path))
    assert info['id'] is not None
    assert len(info['id']) == 32
    assert info['name'] == os.path.basename(os.path.abspath(str(tmp_path)))


def test_read_library_metadata_reads_db(tmp_path):
    db_path = tmp_path / 'metadata.db'
    conn = sqlite3.connect(str(db_path))
    cur = conn.cursor()
    cur.execute('CREATE TABLE meta (id INTEGER PRIMARY KEY, key TEXT, value TEXT)')
    cur.execute("INSERT INTO meta (key, value) VALUES ('library_id', 'lib-uuid-123')")
    cur.execute("INSERT INTO meta (key, value) VALUES ('library_name', 'Test Library')")
    conn.commit()
    conn.close()

    info = library_utils._read_library_metadata(str(tmp_path))
    assert info['id'] == 'lib-uuid-123'
    assert info['name'] == 'Test Library'


def test_find_config_dirs_linux(tmp_path, monkeypatch):
    monkeypatch.setattr(platform, 'system', lambda: 'Linux')
    monkeypatch.setattr(Path, 'home', classmethod(lambda cls: Path(tmp_path)))
    existing = tmp_path / '.config' / 'calibre'
    existing.mkdir(parents=True)
    dirs = library_utils._find_config_dirs()
    assert any('calibre' in d for d in dirs)


def test_find_recent_libs_from_config(tmp_path, monkeypatch):
    config_dir = tmp_path / 'conf'
    config_dir.mkdir()
    candidate_path = '/tmp/library'
    payload = {'recent_libraries': [candidate_path]}
    with open(config_dir / 'recent.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f)

    monkeypatch.setattr(library_utils, '_find_config_dirs', lambda: [str(config_dir)])
    found = library_utils._find_recent_libs_from_config()
    assert candidate_path in found


def test_find_config_dirs_windows(tmp_path, monkeypatch):
    monkeypatch.setattr(platform, 'system', lambda: 'Windows')
    monkeypatch.setenv('APPDATA', str(tmp_path / 'AppData'))
    monkeypatch.setenv('LOCALAPPDATA', str(tmp_path / 'LocalAppData'))
    for d in ('AppData', 'LocalAppData'):
        path = tmp_path / d / 'calibre'
        path.mkdir(parents=True)
    dirs = library_utils._find_config_dirs()
    assert any('calibre' in d.lower() for d in dirs)
