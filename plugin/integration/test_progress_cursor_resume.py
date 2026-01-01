from __future__ import annotations

from unittest.mock import Mock

import pytest

from calibre_plugins.sync_calimob import config as cfg
from calibre_plugins.sync_calimob import sync_worker


def _make_worker():
    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    worker.library_id = 'lib-123'
    worker.calimob_library_id = 9
    worker.mapping = {}
    worker._uuid_to_book_id = {}
    worker.db = Mock()
    return worker


def test_progress_cursor_saved_and_used_on_resume(monkeypatch):
    prefs = {}
    monkeypatch.setattr(cfg, 'plugin_prefs', prefs, raising=False)
    monkeypatch.setattr(cfg, 'STORE_LIBRARY_MAPPINGS', 'LibraryMappings', raising=False)

    worker = _make_worker()
    worker.client = Mock()
    worker._process_batch_results = Mock()

    def batch_gen(*_args, **_kwargs):
        yield ([{'op': 'update', 'item': {'id': 1, 'uuid': 'u1', 'title': 'T1', 'last_modified': 1}, 'idempotency_key': 'c1'}], {}, {})
        worker._cancelled = True
        yield ([{'op': 'update', 'item': {'id': 2, 'uuid': 'u2', 'title': 'T2', 'last_modified': 2}, 'idempotency_key': 'c2'}], {}, {})

    worker._collect_local_changes_progressive = Mock(side_effect=batch_gen)
    worker.client.post_sync = Mock(return_value={
        'results': [{'status': 'applied', 'client_change_id': 'c1'}],
        'progress_cursor': 'progress-1',
        'new_cursor': 'new-1',
    })
    worker.save_cursor = sync_worker.SyncWorker.save_cursor.__get__(worker, sync_worker.SyncWorker)

    summary = worker.push_sync(progress_callback=None, full_sync=False)
    assert summary['errors'], 'expected cancellation to register error'
    assert prefs.get('LibraryMappings', {}).get(worker.library_id, {}).get(cfg.KEY_LAST_SYNC_CURSOR) == 'progress-1'

    worker2 = _make_worker()
    worker2.mapping = prefs['LibraryMappings'][worker.library_id]
    worker2.client = Mock()
    worker2._process_batch_results = Mock()
    worker2._collect_local_changes_progressive = Mock(return_value=[
        ([{'op': 'update', 'item': {'id': 3, 'uuid': 'u3', 'title': 'T3', 'last_modified': 3}, 'idempotency_key': 'c3'}], {}, {}),
    ])
    worker2.client.post_sync = Mock(return_value={
        'results': [{'status': 'applied', 'client_change_id': 'c3'}],
        'progress_cursor': 'progress-2',
        'new_cursor': 'new-2',
    })
    worker2.save_cursor = sync_worker.SyncWorker.save_cursor.__get__(worker2, sync_worker.SyncWorker)

    worker2.push_sync(progress_callback=None, full_sync=False)
    _, kwargs = worker2.client.post_sync.call_args
    assert kwargs['client_cursor'] == 'progress-1'
