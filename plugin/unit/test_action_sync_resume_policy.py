from __future__ import annotations

import sys
import types
from datetime import datetime, timedelta

# Test environment stub: some unit runs miss pyqtSignal on qt.core / PyQt5.Qt.
qt_core = sys.modules.get('qt.core')
if qt_core is not None and not hasattr(qt_core, 'pyqtSignal'):
    setattr(qt_core, 'pyqtSignal', lambda *args, **kwargs: None)
pyqt_qt = sys.modules.get('PyQt5.Qt')
if pyqt_qt is not None and not hasattr(pyqt_qt, 'pyqtSignal'):
    setattr(pyqt_qt, 'pyqtSignal', lambda *args, **kwargs: None)
if qt_core is not None and hasattr(qt_core, 'QToolButton') and not hasattr(qt_core.QToolButton, 'InstantPopup'):
    setattr(qt_core.QToolButton, 'InstantPopup', 1)
if pyqt_qt is not None and hasattr(pyqt_qt, 'QToolButton') and not hasattr(pyqt_qt.QToolButton, 'InstantPopup'):
    setattr(pyqt_qt.QToolButton, 'InstantPopup', 1)

# action.py pulls many UI modules; stub those not needed by these policy tests.
if 'calibre_plugins.sync_calimob.dialogs' not in sys.modules:
    d = types.ModuleType('calibre_plugins.sync_calimob.dialogs')
    for name in [
        'DoAddRemoveDialog', 'DoShelfSyncDialog', 'SwitchEditionDialog',
        'PickCaliwebBookDialog', 'ActionStatus', 'ChooseShelvesToSyncDialog',
        'UpdateReadingProgressDialog',
    ]:
        setattr(d, name, type(name, (), {}))
    sys.modules['calibre_plugins.sync_calimob.dialogs'] = d

if 'calibre_plugins.sync_calimob.core' not in sys.modules:
    c = types.ModuleType('calibre_plugins.sync_calimob.core')
    for name in ['CalibreSearcher', 'HttpHelper', 'IdCaches', 'update_calibre_isbn_if_required']:
        setattr(c, name, type(name, (), {}))
    sys.modules['calibre_plugins.sync_calimob.core'] = c

from calibre_plugins.sync_calimob import action


def _make_action():
    act = action.SyncCalimobAction.__new__(action.SyncCalimobAction)
    act.gui = object()
    return act


def _pending_state(updated_at=None, cursor=2, total=10):
    state = {
        'client_cursor': cursor,
        'client_total': total,
        'server_cursor': '100:1',
    }
    if updated_at is not None:
        state['updated_at'] = updated_at
    return {'v5_client_resume': state}


def test_get_v5_resume_pending_state_returns_pending_when_valid():
    act = _make_action()
    mapping = _pending_state(updated_at=datetime.utcnow().isoformat())

    state, is_stale, age_seconds = act._get_v5_resume_pending_state(mapping)

    assert isinstance(state, dict)
    assert is_stale is False
    assert age_seconds is not None


def test_get_v5_resume_pending_state_flags_stale_when_old(monkeypatch):
    act = _make_action()
    old_ts = (datetime.utcnow() - timedelta(days=3)).isoformat()
    mapping = _pending_state(updated_at=old_ts)
    monkeypatch.setenv('CALIMOB_V5_RESUME_TTL_SECONDS', '10')

    state, is_stale, _ = act._get_v5_resume_pending_state(mapping)

    assert isinstance(state, dict)
    assert is_stale is True


def test_resolve_sync_mode_background_prefers_resume_or_full_by_staleness(monkeypatch):
    act = _make_action()
    monkeypatch.setenv('CALIMOB_V5_RESUME_TTL_SECONDS', '10')

    fresh = _pending_state(updated_at=datetime.utcnow().isoformat())
    stale = _pending_state(updated_at=(datetime.utcnow() - timedelta(days=3)).isoformat())

    mode_fresh = act._resolve_sync_mode_from_resume_state(fresh, interactive=False)
    mode_stale = act._resolve_sync_mode_from_resume_state(stale, interactive=False)

    assert mode_fresh['proceed'] is True
    assert mode_fresh['force_full'] is False
    assert mode_stale['proceed'] is True
    assert mode_stale['force_full'] is True


def test_resolve_sync_mode_interactive_fresh_user_forces_diff(monkeypatch):
    act = _make_action()
    mapping = _pending_state(updated_at=datetime.utcnow().isoformat())
    monkeypatch.setattr(action, 'question_dialog', lambda *args, **kwargs: False)

    mode = act._resolve_sync_mode_from_resume_state(mapping, interactive=True)

    assert mode['proceed'] is True
    assert mode['force_full'] is False
    assert mode['forced_diff'] is True


def test_clear_v5_resume_state_for_library_removes_only_resume_key(monkeypatch):
    act = _make_action()
    prefs = {
        action.cfg.STORE_LIBRARY_MAPPINGS: {
            'lib-1': {
                'v5_client_resume': {'client_cursor': 2, 'client_total': 10},
                action.cfg.KEY_CALIMOB_LIBRARY_ID: 9,
                action.cfg.KEY_SYNC_ENABLED: True,
            }
        }
    }
    monkeypatch.setattr(action.cfg, 'plugin_prefs', prefs)

    act._clear_v5_resume_state_for_library('lib-1')

    mapping = prefs[action.cfg.STORE_LIBRARY_MAPPINGS]['lib-1']
    assert 'v5_client_resume' not in mapping
    assert mapping[action.cfg.KEY_CALIMOB_LIBRARY_ID] == 9
    assert mapping[action.cfg.KEY_SYNC_ENABLED] is True
