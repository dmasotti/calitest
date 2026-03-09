"""Tests for heavy hash/payload debug logging gates."""

import inspect


def test_compute_metadata_signature_does_not_log_hash_payload_by_default(monkeypatch):
    from calibre_plugins.sync_calimob import sync_worker

    worker = sync_worker.SyncWorker(gui=None, db=None, library_id='lib', calimob_library_id='1')

    calls = []
    monkeypatch.delenv('CALIMOB_DEBUG_HASH', raising=False)
    monkeypatch.setattr(sync_worker, 'calimob_debug', lambda msg, **kwargs: calls.append(msg))
    monkeypatch.setattr(sync_worker.sync_utils, 'build_metadata_hash_payload', lambda item: {'k': 'v'})
    monkeypatch.setattr(sync_worker.sync_utils, 'compute_metadata_hash', lambda *args, **kwargs: 'h')

    result = worker._compute_metadata_signature({'uuid': 'u-1'}, {}, None)

    assert result == 'h'
    assert not any('HASH_INPUT_CLIENT' in str(msg) for msg in calls)


def test_compute_metadata_signature_logs_hash_payload_when_enabled(monkeypatch):
    from calibre_plugins.sync_calimob import sync_worker

    worker = sync_worker.SyncWorker(gui=None, db=None, library_id='lib', calimob_library_id='1')

    calls = []
    monkeypatch.setenv('CALIMOB_DEBUG_HASH', '1')
    monkeypatch.setattr(sync_worker, 'calimob_debug', lambda msg, **kwargs: calls.append(msg))
    monkeypatch.setattr(sync_worker.sync_utils, 'build_metadata_hash_payload', lambda item: {'k': 'v'})
    monkeypatch.setattr(sync_worker.sync_utils, 'compute_metadata_hash', lambda *args, **kwargs: 'h')

    result = worker._compute_metadata_signature({'uuid': 'u-1'}, {}, None)

    assert result == 'h'
    assert any('HASH_INPUT_CLIENT' in str(msg) for msg in calls)


def test_collect_local_changes_payload_log_is_guarded():
    from calibre_plugins.sync_calimob import sync_worker

    source = inspect.getsource(sync_worker.SyncWorker._collect_local_changes)
    assert 'if self._is_hash_debug_enabled()' in source
    assert 'Payload ready to send for book' in source
