from __future__ import annotations

from calibre_plugins.sync_calimob import config as cfg


def test_update_book_cache_writes_epoch_columns(monkeypatch):
    snapshot = {'notes': {}}
    captured = {}

    monkeypatch.setattr(cfg, 'get_book_mapping_entry', lambda library_id, book_id, db=None: snapshot)

    def fake_update_book_mapping(library_id, book_id, updates, db=None):
        captured.update(updates)

    monkeypatch.setattr(cfg, 'update_book_mapping', fake_update_book_mapping)

    cfg.update_book_cache(
        'lib-uuid',
        123,
        file_cache={'EPUB': {'hash': 'sha256:abc', 'mtime': 1, 'size': 2}},
        cover_hash='sha256:cover',
        last_modified='ignored-string-for-epoch-column',
        last_modified_server=999,
        metadata_hash='sha256:meta',
        last_modified_epoch=111,
        db=None,
    )

    assert 'notes' in captured
    assert captured['last_modified'] == 111
    assert captured['last_modified_server'] == 999







