"""Integration tests for plugin/server metadata hash comparison in SyncWorker."""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import sys
from pathlib import Path

# Add plugin to path
plugin_path = Path(__file__).parent.parent.parent.parent / "sync_calimob"
sys.path.insert(0, str(plugin_path))

import sync_worker
from sync_worker import SyncWorker


def _build_worker(local_ts):
    mock_db = Mock()
    mock_db.library_path = "/tmp/test_library"
    mock_db.data = Mock()
    mock_db.data.has_id.return_value = True
    mock_db.set_metadata = Mock()

    metadata = SimpleNamespace(
        last_modified=datetime.fromtimestamp(local_ts, tz=timezone.utc),
        title="Local title",
        author_sort="",
        rating=None,
    )
    mock_db.get_metadata.return_value = metadata

    worker = SyncWorker(
        db=mock_db,
        client=Mock(),
        library_id="lib-uuid",
        calimob_library_id="1",
    )

    worker._resolve_local_book_id = Mock(return_value=42)
    worker._write_custom_columns = Mock()
    worker._cache_book_uuid = Mock()
    worker._should_download_cover = Mock(return_value=(False, "no_download"))
    worker._download_cover = Mock()

    return worker, mock_db


def _mock_mapper(monkeypatch):
    def _json_item_to_calibre(item, _db, **kwargs):
        _ = kwargs
        lm = item.get("last_modified")
        lm_dt = datetime.fromtimestamp(int(lm), tz=timezone.utc) if lm else None
        return {
            "title": item.get("title", "Server title"),
            "last_modified": lm_dt,
            "rating": item.get("rating"),
        }

    monkeypatch.setattr(sync_worker.sync_mapper, "json_item_to_calibre", _json_item_to_calibre)
    monkeypatch.setattr(
        sync_worker.sync_mapper,
        "calibre_to_json_item",
        lambda *args, **kwargs: {
            "id": "42",
            "uuid": "uuid-42",
            "title": "Local title",
            "authors": [],
            "tags": [],
            "identifiers": {},
            "cover": {},
            "files": [],
        },
    )


def test_apply_update_skips_set_metadata_when_cached_hash_matches_server(monkeypatch):
    server_hash = "a" * 64
    worker, mock_db = _build_worker(local_ts=1000)
    _mock_mapper(monkeypatch)

    update_calls = []
    monkeypatch.setattr(
        sync_worker.cfg,
        "get_book_mapping_entry",
        lambda *args, **kwargs: {
            "metadata_hash_cache": f"{server_hash}:1000",
            "notes": {"book_cache": {"last_modified_server": 999}},
        },
    )
    monkeypatch.setattr(
        sync_worker.cfg,
        "update_book_cache",
        lambda *args, **kwargs: update_calls.append(kwargs),
    )
    worker._compute_metadata_signature = Mock(return_value="local-signature")

    item = {
        "id": 42,
        "uuid": "uuid-42",
        "title": "Server title",
        "last_modified": 1000,
        "metadata_hash": server_hash,
        "cover": {"has_cover": False},
        "files": [],
    }

    book_id, changed = worker._apply_update(item, skip_cover=True)

    assert book_id == 42
    assert changed is False
    mock_db.set_metadata.assert_not_called()
    assert update_calls
    assert update_calls[-1].get("metadata_hash_cache") == f"{server_hash}:1000"


def test_apply_update_applies_when_cached_hash_timestamp_is_stale(monkeypatch):
    server_hash = "b" * 64
    worker, mock_db = _build_worker(local_ts=1000)
    _mock_mapper(monkeypatch)

    update_calls = []
    monkeypatch.setattr(
        sync_worker.cfg,
        "get_book_mapping_entry",
        lambda *args, **kwargs: {
            "metadata_hash_cache": f"{server_hash}:999",
            "notes": {"book_cache": {"last_modified_server": 998}},
        },
    )
    monkeypatch.setattr(
        sync_worker.cfg,
        "update_book_cache",
        lambda *args, **kwargs: update_calls.append(kwargs),
    )
    worker._compute_metadata_signature = Mock(return_value="local-signature")

    item = {
        "id": 42,
        "uuid": "uuid-42",
        "title": "Server updated title",
        "last_modified": 1001,
        "metadata_hash": server_hash,
        "cover": {"has_cover": False},
        "files": [],
    }

    book_id, changed = worker._apply_update(item, skip_cover=True)

    assert book_id == 42
    assert changed is True
    mock_db.set_metadata.assert_called_once()
    assert update_calls
    assert update_calls[-1].get("metadata_hash_cache") == f"{server_hash}:1001"


def test_apply_update_calculates_local_hash_when_cache_missing(monkeypatch):
    server_hash = "c" * 64
    worker, mock_db = _build_worker(local_ts=1000)
    _mock_mapper(monkeypatch)

    update_calls = []
    monkeypatch.setattr(
        sync_worker.cfg,
        "get_book_mapping_entry",
        lambda *args, **kwargs: {"metadata_hash_cache": None, "notes": {}},
    )
    monkeypatch.setattr(
        sync_worker.cfg,
        "update_book_cache",
        lambda *args, **kwargs: update_calls.append(kwargs),
    )
    worker._compute_metadata_signature = Mock(return_value=server_hash)

    item = {
        "id": 42,
        "uuid": "uuid-42",
        "title": "Server title",
        "last_modified": 1000,
        "metadata_hash": server_hash,
        "cover": {"has_cover": False},
        "files": [],
    }

    book_id, changed = worker._apply_update(item, skip_cover=True)

    assert book_id == 42
    assert changed is False
    assert worker._compute_metadata_signature.called
    mock_db.set_metadata.assert_not_called()
    assert update_calls
    assert update_calls[-1].get("metadata_hash_cache") == f"{server_hash}:1000"
