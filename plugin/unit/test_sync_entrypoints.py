"""Behavior tests for centralized sync entrypoints."""


class _FakeWorker:
    def __init__(self):
        self.calls = []

    def sync(self, progress_callback=None, no_cache=False, full_sync=False):
        self.calls.append(('sync', progress_callback, no_cache, full_sync))
        return {'from': 'sync'}

    def full_sync(self, progress_callback=None, no_cache=False):
        self.calls.append(('full_sync', progress_callback, no_cache))
        return {'from': 'full_sync'}

    def sync_snapshot(self, since=None):
        self.calls.append(('snapshot', since))
        return {'from': 'snapshot'}

    def sync_v4(self, full_sync=False):
        self.calls.append(('v4', full_sync))
        return {'from': 'v4'}


class _Args:
    def __init__(self, snapshot=False, v4=False, full_sync=False, since=None):
        self.snapshot = snapshot
        self.v4 = v4
        self.full_sync = full_sync
        self.since = since


def test_run_ui_sync_routes_to_full_sync_when_forced():
    from calibre_plugins.sync_calimob import sync_entrypoints

    worker = _FakeWorker()
    summary = sync_entrypoints.run_ui_sync(worker, progress_callback='cb', force_full=True, no_cache=True)

    assert summary['from'] == 'full_sync'
    assert worker.calls == [('full_sync', 'cb', True)]


def test_run_ui_sync_routes_to_sync_when_not_forced():
    from calibre_plugins.sync_calimob import sync_entrypoints

    worker = _FakeWorker()
    summary = sync_entrypoints.run_ui_sync(worker, progress_callback='cb', force_full=False, no_cache=False)

    assert summary['from'] == 'sync'
    assert worker.calls == [('sync', 'cb', False, False)]


def test_run_cli_sync_snapshot_route_sets_version():
    """snapshot route removed — CLI always routes to v5 sync now."""
    from calibre_plugins.sync_calimob import sync_entrypoints

    worker = _FakeWorker()
    logs = []
    # Even with snapshot=True, the new entrypoint ignores it and routes to sync (v5)
    summary = sync_entrypoints.run_cli_sync(
        worker,
        _Args(snapshot=True, since='2026-03-01T00:00:00Z'),
        debug_print=logs.append
    )

    assert summary['from'] == 'sync'
    assert summary['sync_version'] == 'v5'
    assert any('SYNC_CURRENT_V5' in line for line in logs)


def test_run_cli_sync_v4_route_sets_version():
    """v4 route removed — CLI always routes to v5 sync now."""
    from calibre_plugins.sync_calimob import sync_entrypoints

    worker = _FakeWorker()
    logs = []
    summary = sync_entrypoints.run_cli_sync(worker, _Args(v4=True, full_sync=True), debug_print=logs.append)

    assert summary['from'] == 'sync'
    assert summary['sync_version'] == 'v5'


def test_run_cli_sync_default_current_route_sets_version():
    from calibre_plugins.sync_calimob import sync_entrypoints

    worker = _FakeWorker()
    logs = []
    summary = sync_entrypoints.run_cli_sync(worker, _Args(snapshot=False, v4=False, full_sync=True), debug_print=logs.append)

    assert summary['from'] == 'sync'
    assert summary['sync_version'] == 'v5'
    assert worker.calls == [('sync', None, False, True)]
    assert any('SYNC_CURRENT_V5' in line for line in logs)
