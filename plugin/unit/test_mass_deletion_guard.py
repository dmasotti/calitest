"""Mass-deletion guard (Level B of the deletion/subscription data-safety matrix).

The plugin infers deletions from local ABSENCE (a previously-synced book whose
Calibre row vanished — sync_worker._v5_collect_client_books_candidates, the
NOT EXISTS query). That is dangerous when the local library differs from what was
synced for a NON-deletion reason (restore from an older/smaller backup, a
metadata.db rebuild/corruption, a separate cover-cache file outliving the
library): every missing book would be pushed as a deletion and wipe the cloud
copy. The guard suppresses (headless / auto-sync) or confirms (manual / GUI) a
suspiciously large absence-derived batch; small genuine deletions pass untouched.
"""
from __future__ import annotations

import pytest

from calibre_plugins.sync_calimob.sync_worker import (
    SyncWorker,
    evaluate_mass_deletion_guard,
)


def _worker(gui=None):
    """A SyncWorker with only the attributes the guard touches (no heavy init)."""
    w = object.__new__(SyncWorker)
    w.gui = gui
    w.library_id = 'lib-uuid'
    return w


class TestEvaluateMassDeletionGuard:
    def test_below_absolute_floor_passes(self):
        # 5 deletions is at the floor → never guarded, even at 100%.
        assert evaluate_mass_deletion_guard(5, 5) is False

    def test_large_fraction_above_floor_is_guarded(self):
        assert evaluate_mass_deletion_guard(950, 1000) is True

    def test_above_floor_but_tiny_fraction_passes(self):
        # 6 of 1000 = 0.6% < 20% → a legitimate handful of deletions.
        assert evaluate_mass_deletion_guard(6, 1000) is False

    def test_known_count_zero_passes(self):
        # Nothing known synced → ratio undefined → fail open (no guard).
        assert evaluate_mass_deletion_guard(100, 0) is False

    def test_just_over_threshold_is_guarded(self):
        assert evaluate_mass_deletion_guard(201, 1000) is True   # 20.1% and > 5

    def test_exactly_at_threshold_not_guarded(self):
        assert evaluate_mass_deletion_guard(200, 1000) is False  # 20.0% is not > 20%


class TestGuardBehaviour:
    def test_headless_suppresses_mass_deletion(self):
        w = _worker(gui=None)                      # auto-sync / no GUI
        summary = {}
        uuids = ['u%d' % i for i in range(950)]
        out = w._guard_mass_deletions(uuids, 1000, summary=summary)
        assert out == []
        assert summary['mass_deletion_suppressed'] == 950
        assert 'mass_deletion_confirmed' not in summary

    def test_interactive_confirmed_proceeds(self, monkeypatch):
        w = _worker(gui=object())                  # manual sync / GUI present
        monkeypatch.setattr(w, '_confirm_mass_deletion', lambda *a, **k: True)
        summary = {}
        uuids = ['u%d' % i for i in range(950)]
        out = w._guard_mass_deletions(uuids, 1000, summary=summary)
        assert out == uuids
        assert summary['mass_deletion_confirmed'] == 950
        assert 'mass_deletion_suppressed' not in summary

    def test_interactive_declined_suppresses(self, monkeypatch):
        w = _worker(gui=object())
        monkeypatch.setattr(w, '_confirm_mass_deletion', lambda *a, **k: False)
        summary = {}
        out = w._guard_mass_deletions(['u%d' % i for i in range(950)], 1000, summary=summary)
        assert out == []
        assert summary['mass_deletion_suppressed'] == 950

    def test_small_legitimate_deletion_passes_untouched(self):
        w = _worker(gui=None)
        summary = {}
        out = w._guard_mass_deletions(['a', 'b'], 1000, summary=summary)
        assert out == ['a', 'b']
        assert summary == {}                       # no guard flags

    def test_confirm_dialog_returns_false_without_gui(self):
        # The interactive confirm must default to False (→ suppress) when headless.
        w = _worker(gui=None)
        assert w._confirm_mass_deletion(950, 1000, 'msg') is False
