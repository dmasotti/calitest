from __future__ import annotations

import sqlite3
import sys
from types import SimpleNamespace
from unittest.mock import Mock

from calibre_plugins.sync_calimob import sync_worker


class DummyDb:
    def __init__(self):
        self.data = Mock()
        self.data.has_id = lambda bid: True
        conn = sqlite3.connect(':memory:')
        self.new_api = SimpleNamespace(
            backend=SimpleNamespace(conn=conn)
        )


def _make_worker():
    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    worker.library_id = 'lib-current-bugs'
    worker.calimob_library_id = 9
    worker.db = DummyDb()
    worker._uuid_to_book_id = {}
    worker._target_debug_uuid = None
    return worker


def test_current_bug_merkle_leaf_string_uuids_must_not_be_split_char_by_char(monkeypatch):
    """
    Current bug:
    if server returns `uuids` as a string instead of list, the client iterates
    chars and produces bogus candidates (e.g. '-', 'a', ...).
    Expected: ignore non-list/tuple payload and return [].
    """
    worker = _make_worker()
    conn = sqlite3.connect(':memory:')
    conn.execute("CREATE TABLE calimob_books_hash_v2 (uuid TEXT, metadata_hash TEXT)")
    conn.execute(
        "INSERT INTO calimob_books_hash_v2 (uuid, metadata_hash) VALUES (?, ?)",
        ('ab000000-0000-4000-8000-000000000002', 'b' * 64),
    )
    conn.commit()

    class FakeClient:
        def get_merkle_branches(self, **kwargs):
            return {'branches': [{'branch_id': 10, 'branch_hash': 'f' * 64}]}

        def get_merkle_leaves(self, **kwargs):
            return {'leaves': [{'leaf_id': 171, 'leaf_hash': 'e' * 64, 'uuids': 'not-a-list'}]}

    worker.client = FakeClient()
    fake_sync_utils = SimpleNamespace(get_merkle_root=lambda _conn: {'root_hash': 'local-root'})
    monkeypatch.setitem(sys.modules, 'sync_utils', fake_sync_utils)

    candidates = worker._v5_merkle_metadata_drilldown(
        conn,
        local_hash_data={'library_metadata_hash': 'x' * 64},
        server_hash_data={'root_hash': 'server-root'},
        ts_func=lambda: 't',
    )

    assert candidates == []
