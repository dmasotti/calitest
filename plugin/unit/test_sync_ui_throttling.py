"""Tests for UI event throttling in sync hot paths."""

import inspect
from unittest.mock import patch


def test_collect_local_changes_uses_throttled_ui_events():
    from calibre_plugins.sync_calimob import sync_worker

    source = inspect.getsource(sync_worker.SyncWorker._collect_local_changes)
    assert '_sync_heartbeat' in source
    assert 'Application.instance().processEvents()' not in source


def test_collect_local_changes_progressive_uses_throttled_ui_events():
    from calibre_plugins.sync_calimob import sync_worker

    source = inspect.getsource(sync_worker.SyncWorker._collect_local_changes_progressive)
    assert '_sync_heartbeat' in source
    assert 'Application.instance().processEvents()' not in source


def test_throttled_ui_events_respects_min_interval():
    from calibre_plugins.sync_calimob import sync_worker

    class _App:
        def __init__(self):
            self.calls = 0

        def processEvents(self):
            self.calls += 1

    class _Application:
        app = _App()

        @staticmethod
        def instance():
            return _Application.app

    worker = sync_worker.SyncWorker(gui=None, db=None, library_id='lib', calimob_library_id='1')
    worker._last_ui_events_ts = None

    with patch('calibre.gui2.Application', _Application), patch.object(sync_worker.time, 'monotonic', side_effect=[1.00, 1.05, 1.20]):
        worker._throttled_ui_events(min_interval_s=0.1)  # allowed
        worker._throttled_ui_events(min_interval_s=0.1)  # skipped
        worker._throttled_ui_events(min_interval_s=0.1)  # allowed

    assert _Application.app.calls == 2
