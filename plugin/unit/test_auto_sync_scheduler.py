from __future__ import annotations

from calibre_plugins.sync_calimob import auto_sync


class FakeTimer:
    def __init__(self):
        self._active = False
        self.interval_ms = None

    def isActive(self):
        return self._active

    def start(self):
        self._active = True

    def stop(self):
        self._active = False

    def setInterval(self, ms):
        self.interval_ms = ms


def test_clamp_minutes():
    assert auto_sync.clamp_minutes('7') == 7
    assert auto_sync.clamp_minutes(None, default=9) == 9
    assert auto_sync.clamp_minutes(0) == 1
    assert auto_sync.clamp_minutes(999999) == 24 * 60


def test_get_set_auto_sync_settings_roundtrip():
    mappings = {}
    mappings = auto_sync.set_auto_sync_settings(
        mappings,
        'lib-1',
        key_enabled='autoSyncEnabled',
        key_minutes='autoSyncIntervalMinutes',
        enabled=True,
        minutes=15,
    )
    enabled, minutes = auto_sync.get_auto_sync_settings(
        mappings,
        'lib-1',
        key_enabled='autoSyncEnabled',
        key_minutes='autoSyncIntervalMinutes',
    )
    assert enabled is True
    assert minutes == 15


def test_apply_timer_enables_and_sets_interval():
    t = FakeTimer()
    auto_sync.apply_timer(t, True, 7)
    assert t.interval_ms == 7 * 60 * 1000
    assert t.isActive() is True


def test_apply_timer_disables():
    t = FakeTimer()
    t.start()
    auto_sync.apply_timer(t, False, 7)
    assert t.isActive() is False


def test_should_run_tick():
    assert auto_sync.should_run_tick(busy=False, any_sync_running=False, timer_active=True) is True
    assert auto_sync.should_run_tick(busy=True, any_sync_running=False, timer_active=True) is False
    assert auto_sync.should_run_tick(busy=False, any_sync_running=True, timer_active=True) is False
    assert auto_sync.should_run_tick(busy=False, any_sync_running=False, timer_active=False) is False


