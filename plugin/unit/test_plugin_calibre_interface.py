"""
Edge-case matrix for the plugin-Calibre interface layer.

Covers action methods that have no (or minimal) existing tests:
  - shutdown()               teardown timer / event filters
  - clear_sync_cache()       confirm/delete/corrupt paths
  - force_rebuild_sync_cache() confirm/rebuild/fail paths
  - fetch_conflicts()        routing + error gates
  - show_configuration()     restart-check guard
  - check_if_restart_needed()

Pattern mirrors test_action_selected_e2e.py:
  - SyncCalimobAction instantiated via __new__ (no Calibre GUI)
  - calibre.gui2 helpers and module dependencies patched in
"""
from __future__ import annotations

import sys
import types
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch

import pytest

from PyQt5.Qt import QToolButton

if not hasattr(QToolButton, "InstantPopup"):
    QToolButton.InstantPopup = 0

from calibre_plugins.sync_calimob import action as action_mod
from calibre_plugins.sync_calimob import config as cfg


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_action(library_id="lib-uuid"):
    act = action_mod.SyncCalimobAction.__new__(action_mod.SyncCalimobAction)
    db = SimpleNamespace(
        library_path="/tmp/test_library",
        get_metadata=lambda *_a, **_k: SimpleNamespace(uuid="book-uuid-from-db"),
    )
    act.gui = SimpleNamespace(
        current_db=db,
        must_restart_before_config=False,
        library_view=SimpleNamespace(viewport=lambda: SimpleNamespace(removeEventFilter=lambda _: None)),
        quit=Mock(),
    )
    act._auto_sync_timer = None
    return act, db


def _set_library_mapping(monkeypatch, library_uuid="lib-uuid", calimob_library_id="77", enabled=True):
    """Patch plugin_prefs with a real dict containing the given library mapping."""
    import calibre_plugins.sync_calimob.config as config_mod
    real_prefs = {
        config_mod.STORE_LIBRARY_MAPPINGS: {
            library_uuid: {
                config_mod.KEY_CALIMOB_LIBRARY_ID: calimob_library_id,
                config_mod.KEY_SYNC_ENABLED: enabled,
            }
        }
    }
    monkeypatch.setattr(config_mod, "plugin_prefs", real_prefs)


def _install_library_utils(monkeypatch, library_id="lib-uuid"):
    lib_mod = types.ModuleType("calibre_plugins.sync_calimob.library_utils")
    lib_mod.get_calibre_library_id = lambda _db: library_id
    monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.library_utils", lib_mod)


def _install_mapping_table(monkeypatch, *, connect_ctx=None, force_rebuild_ok=True):
    import calibre_plugins.sync_calimob as parent_pkg
    mt_mod = types.ModuleType("calibre_plugins.sync_calimob.mapping_table")
    mt_mod.sync_table = lambda conn: "calimob_books_sync"
    mt_mod.force_rebuild_table = Mock(return_value=force_rebuild_ok)
    if connect_ctx is None:
        cursor_mock = MagicMock()
        cursor_mock.rowcount = 5
        conn_mock = MagicMock()
        conn_mock.cursor.return_value = cursor_mock
        conn_mock.__enter__ = Mock(return_value=conn_mock)
        conn_mock.__exit__ = Mock(return_value=False)
        connect_ctx = lambda *_a, **_k: conn_mock
    mt_mod._connect = connect_ctx
    monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.mapping_table", mt_mod)
    monkeypatch.setattr(parent_pkg, "mapping_table", mt_mod)
    return mt_mod


def _install_rest_client(monkeypatch, *, is_configured=True, conflicts=None, raise_exc=None):
    class _FakeClient:
        def __init__(self, *_a, **_k):
            pass

        def is_configured(self):
            return is_configured

        def get_sync_conflicts(self, **_k):
            if raise_exc:
                raise raise_exc
            return {"conflicts": conflicts or []}

    rest_mod = types.ModuleType("calibre_plugins.sync_calimob.rest_client")
    rest_mod.RestApiClient = _FakeClient
    monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.rest_client", rest_mod)


def _install_worker_stub(monkeypatch):
    class _NoopWorker:
        def __init__(self, *_a, **_k):
            pass

        def resolve_conflicts(self, resolutions):
            return {"resolved": len(resolutions), "errors": []}

    worker_mod = types.ModuleType("calibre_plugins.sync_calimob.sync_worker")
    worker_mod.SyncWorker = _NoopWorker
    monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.sync_worker", worker_mod)


# ─────────────────────────────────────────────────────────────────────────────
# shutdown()
# ─────────────────────────────────────────────────────────────────────────────

class TestShutdown:
    def test_shutdown_stops_auto_sync_timer_if_present(self):
        act, _ = _make_action()
        timer = Mock()
        act._auto_sync_timer = timer
        act.shutdown()
        timer.stop.assert_called_once()

    def test_shutdown_is_safe_with_no_timer(self):
        act, _ = _make_action()
        act._auto_sync_timer = None
        act.shutdown()  # must not raise

    def test_shutdown_is_safe_when_timer_stop_raises(self):
        act, _ = _make_action()
        t = Mock()
        t.stop.side_effect = RuntimeError("timer gone")
        act._auto_sync_timer = t
        act.shutdown()  # must not raise

    def test_shutdown_removes_event_filter_from_viewport(self):
        act, _ = _make_action()
        viewport = Mock()
        act.gui.library_view = SimpleNamespace(viewport=lambda: viewport)
        act.shutdown()
        viewport.removeEventFilter.assert_called_once_with(act)

    def test_shutdown_tolerates_missing_library_view(self):
        act, _ = _make_action()
        del act.gui.library_view
        act.shutdown()  # must not raise


# ─────────────────────────────────────────────────────────────────────────────
# library_changed() + about_to_show_menu()
# ─────────────────────────────────────────────────────────────────────────────

class TestMenuRebuildOnLibraryChange:
    """Verify that switching library or opening menu triggers rebuild_menus()."""

    def test_library_changed_calls_rebuild_menus(self):
        act, db = _make_action()
        act.rebuild_menus = Mock()
        act.library_changed(db)
        act.rebuild_menus.assert_called_once()

    def test_about_to_show_menu_calls_rebuild_menus(self):
        act, _ = _make_action()
        act.rebuild_menus = Mock()
        act.about_to_show_menu()
        act.rebuild_menus.assert_called_once()

    def test_library_changed_with_none_db_does_not_crash(self):
        act, _ = _make_action()
        act.rebuild_menus = Mock()
        act.library_changed(None)
        act.rebuild_menus.assert_called_once()


# ─────────────────────────────────────────────────────────────────────────────
# rebuild_menus() gating: sync items enabled/disabled by association
# ─────────────────────────────────────────────────────────────────────────────

def _setup_rebuild_menus(monkeypatch, *, library_id="lib-uuid",
                         calimob_library_id="77", sync_enabled=True,
                         client_configured=True):
    """Prepare an action object so that rebuild_menus() can run end-to-end.

    Returns (act, created_actions) where created_actions is a list of
    (menu_text, QAction-mock) tuples captured from create_menu_action_unique.
    """
    import calibre_plugins.sync_calimob.config as config_mod
    import calibre_plugins.sync_calimob as parent_pkg

    act = action_mod.SyncCalimobAction.__new__(action_mod.SyncCalimobAction)
    db = SimpleNamespace(library_path="/tmp/test_library")
    act.gui = SimpleNamespace(
        current_db=db,
        must_restart_before_config=False,
        keyboard=SimpleNamespace(
            finalize=Mock(),
            shortcuts={},
        ),
    )
    act.menu = MagicMock()  # QMenu mock
    act.name = "sync_calimob"
    act.qaction = MagicMock()
    act._auto_sync_timer = None
    act._auto_sync_busy = False
    act._sync_status_icon_cache = {}

    # Patch library_utils to return our library_id
    _install_library_utils(monkeypatch, library_id=library_id)

    # Patch config with real dict containing mappings
    real_prefs = {
        config_mod.STORE_PLUGIN: config_mod.DEFAULT_STORE_VALUES.copy(),
    }
    if library_id and calimob_library_id:
        real_prefs[config_mod.STORE_LIBRARY_MAPPINGS] = {
            library_id: {
                config_mod.KEY_CALIMOB_LIBRARY_ID: calimob_library_id,
                config_mod.KEY_SYNC_ENABLED: sync_enabled,
            }
        }
    else:
        real_prefs[config_mod.STORE_LIBRARY_MAPPINGS] = {}
    monkeypatch.setattr(config_mod, "plugin_prefs", real_prefs)

    # Patch RestApiClient
    class _FakeClient:
        token = "tok" if client_configured else ""
        _raw_discovery_endpoint = "https://api.test" if client_configured else ""
        def __init__(self, *a, **k): pass
        def is_configured(self): return client_configured

    rest_mod = types.ModuleType("calibre_plugins.sync_calimob.rest_client")
    rest_mod.RestApiClient = _FakeClient
    monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.rest_client", rest_mod)
    monkeypatch.setattr(parent_pkg, "rest_client", rest_mod, raising=False)

    # Patch unregister_menu_actions (no-op)
    monkeypatch.setattr(action_mod, "unregister_menu_actions", lambda ia: None)

    # Capture created menu actions
    created_actions = []

    def _fake_create_action(ia, parent_menu, menu_text, image=None, tooltip=None,
                            shortcut=None, triggered=None, is_checked=None,
                            shortcut_name=None, unique_name=None,
                            favourites_menu_unique_name=None):
        ac = MagicMock()
        ac.calibre_shortcut_unique_name = menu_text
        ac._enabled = True
        ac.setEnabled = lambda v: setattr(ac, '_enabled', v)
        created_actions.append((menu_text, ac))
        return ac

    monkeypatch.setattr(action_mod, "create_menu_action_unique", _fake_create_action)

    return act, created_actions


def _sync_actions_enabled(created_actions):
    """Return dict of sync action name → enabled state."""
    sync_labels = ["Sync with calimob...", "Full Sync with calimob...",
                   "Sync in background"]
    result = {}
    for label, ac in created_actions:
        for sl in sync_labels:
            if sl.lower() in label.lower():
                result[sl] = ac._enabled
    return result


class TestRebuildMenusGating:
    """End-to-end tests: rebuild_menus() must enable/disable sync items
    based on library association, sync_enabled flag, and client config."""

    def test_associated_library_enables_sync_actions(self, monkeypatch):
        act, actions = _setup_rebuild_menus(
            monkeypatch,
            library_id="lib-1", calimob_library_id="99",
            sync_enabled=True, client_configured=True,
        )
        act.rebuild_menus()

        enabled = _sync_actions_enabled(actions)
        assert enabled, "no sync actions found in menu"
        for label, state in enabled.items():
            assert state is True, f"{label!r} should be ENABLED for associated library"

    def test_non_associated_library_disables_sync_actions(self, monkeypatch):
        act, actions = _setup_rebuild_menus(
            monkeypatch,
            library_id="lib-orphan", calimob_library_id=None,
            sync_enabled=False, client_configured=True,
        )
        act.rebuild_menus()

        enabled = _sync_actions_enabled(actions)
        assert enabled, "no sync actions found in menu"
        for label, state in enabled.items():
            assert state is False, f"{label!r} should be DISABLED for non-associated library"

    def test_sync_disabled_disables_sync_actions(self, monkeypatch):
        act, actions = _setup_rebuild_menus(
            monkeypatch,
            library_id="lib-1", calimob_library_id="99",
            sync_enabled=False, client_configured=True,
        )
        act.rebuild_menus()

        enabled = _sync_actions_enabled(actions)
        for label, state in enabled.items():
            assert state is False, f"{label!r} should be DISABLED when sync_enabled=False"

    def test_client_not_configured_disables_sync_actions(self, monkeypatch):
        act, actions = _setup_rebuild_menus(
            monkeypatch,
            library_id="lib-1", calimob_library_id="99",
            sync_enabled=True, client_configured=False,
        )
        act.rebuild_menus()

        enabled = _sync_actions_enabled(actions)
        for label, state in enabled.items():
            assert state is False, f"{label!r} should be DISABLED when client not configured"

    def test_library_switch_toggles_sync_actions(self, monkeypatch):
        """Simulate switching from associated → non-associated library."""
        import calibre_plugins.sync_calimob.config as config_mod

        # First: associated library
        act, actions1 = _setup_rebuild_menus(
            monkeypatch,
            library_id="lib-associated", calimob_library_id="10",
            sync_enabled=True, client_configured=True,
        )
        act.rebuild_menus()
        enabled1 = _sync_actions_enabled(actions1)
        for label, state in enabled1.items():
            assert state is True, f"BEFORE switch: {label!r} should be ENABLED"

        # Switch: update library_id to one without mapping
        _install_library_utils(monkeypatch, library_id="lib-not-mapped")
        actions1.clear()

        act.rebuild_menus()
        enabled2 = _sync_actions_enabled(actions1)
        for label, state in enabled2.items():
            assert state is False, f"AFTER switch to non-mapped: {label!r} should be DISABLED"

    def test_no_library_id_disables_sync_actions(self, monkeypatch):
        """If library_id is None (e.g. metadata.db unreadable), sync must be disabled."""
        act, actions = _setup_rebuild_menus(
            monkeypatch,
            library_id=None, calimob_library_id=None,
            sync_enabled=False, client_configured=True,
        )
        # Override library_utils to return None
        _install_library_utils(monkeypatch, library_id=None)
        act.rebuild_menus()

        enabled = _sync_actions_enabled(actions)
        for label, state in enabled.items():
            assert state is False, f"{label!r} should be DISABLED when library_id is None"


# ─────────────────────────────────────────────────────────────────────────────
# clear_sync_cache()
# ─────────────────────────────────────────────────────────────────────────────

class TestClearSyncCache:
    def test_clear_cache_happy_path_deletes_rows_and_shows_info(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)

        info_calls = []
        monkeypatch.setattr("calibre.gui2.question_dialog", lambda *a, **k: True)
        monkeypatch.setattr("calibre.gui2.info_dialog", lambda *a, **k: info_calls.append(a))
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected error_dialog")))
        _install_mapping_table(monkeypatch)

        act.clear_sync_cache()

        assert info_calls, "expected info_dialog after successful clear"
        # The info message should mention the deleted count
        assert "5" in str(info_calls[0])

    def test_clear_cache_does_nothing_when_user_cancels_confirm(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)

        monkeypatch.setattr("calibre.gui2.question_dialog", lambda *a, **k: False)
        deleted_calls = []
        mt_mod = _install_mapping_table(monkeypatch)
        # Override connect to detect if it's ever called
        mt_mod._connect = lambda *_a, **_k: (_ for _ in ()).throw(AssertionError("should not connect to DB"))

        act.clear_sync_cache()  # must not raise, must not touch DB

    def test_clear_cache_shows_error_when_no_library_id(self, monkeypatch):
        act, _ = _make_action()
        lib_mod = types.ModuleType("calibre_plugins.sync_calimob.library_utils")
        lib_mod.get_calibre_library_id = lambda _db: None
        monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.library_utils", lib_mod)

        errors = []
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: errors.append(a))

        act.clear_sync_cache()

        assert errors, "expected error when library_id is missing"

    def test_clear_cache_corrupted_db_offers_rebuild_and_succeeds(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)

        def _corrupt_connect(*_a, **_k):
            conn = Mock()
            cursor = Mock()
            cursor.execute.side_effect = Exception("database disk image is malformed")
            conn.cursor.return_value = cursor
            conn.commit = Mock()
            conn.__enter__ = lambda s: conn
            conn.__exit__ = Mock(return_value=False)
            return conn

        mt_mod = _install_mapping_table(monkeypatch, connect_ctx=_corrupt_connect)
        mt_mod.force_rebuild_table = Mock(return_value=True)

        question_answers = iter([True, True])  # first: confirm clear, second: confirm rebuild
        monkeypatch.setattr("calibre.gui2.question_dialog", lambda *a, **k: next(question_answers))
        info_calls = []
        monkeypatch.setattr("calibre.gui2.info_dialog", lambda *a, **k: info_calls.append(a))
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: None)

        act.clear_sync_cache()

        mt_mod.force_rebuild_table.assert_called_once()
        assert any("Rebuilt" in str(c) or "rebuilt" in str(c).lower() for c in info_calls)

    def test_clear_cache_corrupted_db_user_rejects_rebuild_shows_error(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)

        def _corrupt_connect(*_a, **_k):
            conn = Mock()
            cursor = Mock()
            cursor.execute.side_effect = Exception("database disk image is malformed")
            conn.cursor.return_value = cursor
            conn.__enter__ = lambda s: conn
            conn.__exit__ = Mock(return_value=False)
            return conn

        mt_mod = _install_mapping_table(monkeypatch, connect_ctx=_corrupt_connect)
        mt_mod.force_rebuild_table = Mock(return_value=True)

        question_answers = iter([True, False])  # confirm clear; reject rebuild
        monkeypatch.setattr("calibre.gui2.question_dialog", lambda *a, **k: next(question_answers))
        errors = []
        monkeypatch.setattr("calibre.gui2.info_dialog", lambda *a, **k: None)
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: errors.append(a))

        act.clear_sync_cache()

        # rebuild not called because user rejected
        mt_mod.force_rebuild_table.assert_not_called()
        assert errors, "expected error_dialog when corruption not resolved"

    def test_clear_cache_non_corruption_db_error_shows_error(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)

        def _error_connect(*_a, **_k):
            conn = Mock()
            cursor = Mock()
            cursor.execute.side_effect = Exception("disk full")
            conn.cursor.return_value = cursor
            conn.__enter__ = lambda s: conn
            conn.__exit__ = Mock(return_value=False)
            return conn

        _install_mapping_table(monkeypatch, connect_ctx=_error_connect)

        monkeypatch.setattr("calibre.gui2.question_dialog", lambda *a, **k: True)
        errors = []
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: errors.append(a))
        monkeypatch.setattr("calibre.gui2.info_dialog", lambda *a, **k: None)

        act.clear_sync_cache()

        assert errors, "expected error_dialog on generic DB error"
        assert "disk full" in str(errors[0])


# ─────────────────────────────────────────────────────────────────────────────
# force_rebuild_sync_cache()
# ─────────────────────────────────────────────────────────────────────────────

class TestForceRebuildSyncCache:
    def test_force_rebuild_happy_path(self, monkeypatch):
        act, _ = _make_action()
        mt_mod = _install_mapping_table(monkeypatch, force_rebuild_ok=True)

        monkeypatch.setattr("calibre.gui2.question_dialog", lambda *a, **k: True)
        info_calls = []
        monkeypatch.setattr("calibre.gui2.info_dialog", lambda *a, **k: info_calls.append(a))
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: (_ for _ in ()).throw(AssertionError("unexpected error")))

        act.force_rebuild_sync_cache()

        mt_mod.force_rebuild_table.assert_called_once_with("/tmp/test_library")
        assert info_calls, "expected info_dialog after successful rebuild"

    def test_force_rebuild_user_cancels_does_nothing(self, monkeypatch):
        act, _ = _make_action()
        mt_mod = _install_mapping_table(monkeypatch)

        monkeypatch.setattr("calibre.gui2.question_dialog", lambda *a, **k: False)

        act.force_rebuild_sync_cache()

        mt_mod.force_rebuild_table.assert_not_called()

    def test_force_rebuild_failure_shows_error(self, monkeypatch):
        act, _ = _make_action()
        mt_mod = _install_mapping_table(monkeypatch, force_rebuild_ok=False)

        monkeypatch.setattr("calibre.gui2.question_dialog", lambda *a, **k: True)
        errors = []
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: errors.append(a))
        monkeypatch.setattr("calibre.gui2.info_dialog", lambda *a, **k: None)

        act.force_rebuild_sync_cache()

        assert errors, "expected error when rebuild returns False"


# ─────────────────────────────────────────────────────────────────────────────
# fetch_conflicts()
# ─────────────────────────────────────────────────────────────────────────────

def _install_conflict_dialogs(monkeypatch, conflict_dlg_cls=None, resolution_dlg_cls=None):
    """Inject stub dialog classes via sys.modules so the lazy imports in fetch_conflicts work."""
    if conflict_dlg_cls is None:
        class _DefaultConflictDlg:
            def __init__(self, *_a, **_k):
                pass
            def exec(self):
                return 0
        conflict_dlg_cls = _DefaultConflictDlg
    if resolution_dlg_cls is None:
        class _DefaultResDlg:
            Accepted = 1
            def __init__(self, *_a, **_k):
                pass
            def exec(self):
                return 0  # not accepted
            def get_resolutions(self):
                return {}
        resolution_dlg_cls = _DefaultResDlg

    cdlg_mod = types.ModuleType("calibre_plugins.sync_calimob.conflict_dialog")
    cdlg_mod.ConflictDialog = conflict_dlg_cls
    monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.conflict_dialog", cdlg_mod)

    rdlg_mod = types.ModuleType("calibre_plugins.sync_calimob.conflict_resolution_dialog")
    rdlg_mod.ConflictResolutionDialog = resolution_dlg_cls
    monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.conflict_resolution_dialog", rdlg_mod)


class TestFetchConflicts:
    def _install_dialogs(self, monkeypatch, conflict_dlg_cls=None, resolution_dlg_cls=None):
        _install_conflict_dialogs(monkeypatch, conflict_dlg_cls, resolution_dlg_cls)

    def test_fetch_conflicts_no_library_id_shows_error(self, monkeypatch):
        act, _ = _make_action()
        lib_mod = types.ModuleType("calibre_plugins.sync_calimob.library_utils")
        lib_mod.get_calibre_library_id = lambda _db: None
        monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.library_utils", lib_mod)

        errors = []
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: errors.append(a))

        act.fetch_conflicts()

        assert errors

    def test_fetch_conflicts_library_not_associated_shows_error(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)
        # Provide a real prefs dict with empty library mappings so "lib-uuid" is not found
        import calibre_plugins.sync_calimob.config as config_mod
        monkeypatch.setattr(config_mod, "plugin_prefs", {config_mod.STORE_LIBRARY_MAPPINGS: {}})

        errors = []
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: errors.append(a))

        act.fetch_conflicts()

        assert errors
        assert "Associate" in str(errors[0]) or "associated" in str(errors[0]).lower()

    def test_fetch_conflicts_sync_disabled_shows_error(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)
        _set_library_mapping(monkeypatch, enabled=False)

        errors = []
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: errors.append(a))

        act.fetch_conflicts()

        assert errors

    def test_fetch_conflicts_client_not_configured_shows_error(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)
        _set_library_mapping(monkeypatch)
        _install_rest_client(monkeypatch, is_configured=False)
        self._install_dialogs(monkeypatch)

        errors = []
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: errors.append(a))

        act.fetch_conflicts()

        assert errors
        assert "Configur" in str(errors[0])

    def test_fetch_conflicts_empty_list_shows_conflict_dialog(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)
        _set_library_mapping(monkeypatch)
        _install_rest_client(monkeypatch, is_configured=True, conflicts=[])
        _install_worker_stub(monkeypatch)

        dialog_shown = []
        class _ConflictDlg:
            def __init__(self, _gui, conflicts):
                dialog_shown.append(conflicts)
            def exec(self):
                return 0
        self._install_dialogs(monkeypatch, conflict_dlg_cls=_ConflictDlg)
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: (_ for _ in ()).throw(AssertionError("no error expected")))

        act.fetch_conflicts()

        assert dialog_shown == [[]], "ConflictDialog should be shown with empty list"

    def test_fetch_conflicts_api_error_shows_error_dialog(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)
        _set_library_mapping(monkeypatch)
        _install_rest_client(monkeypatch, is_configured=True, raise_exc=IOError("timeout"))
        self._install_dialogs(monkeypatch)

        errors = []
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: errors.append(a))

        act.fetch_conflicts()

        assert errors
        assert "timeout" in str(errors[0])

    def test_fetch_conflicts_with_conflicts_shows_resolution_dialog(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)
        _set_library_mapping(monkeypatch)
        conflict_items = [{"id": 1, "uuid": "abc", "title": "Book A"}]
        _install_rest_client(monkeypatch, is_configured=True, conflicts=conflict_items)
        _install_worker_stub(monkeypatch)

        resolution_exec_called = []
        class _ResolutionDlg:
            Accepted = 1
            def __init__(self, _gui, conflicts):
                resolution_exec_called.append(conflicts)
            def exec(self):
                return 0  # user cancels resolution
            def get_resolutions(self):
                return {}

        class _ConflictDlg:
            def __init__(self, *_a, **_k): pass
            def exec(self): return 0

        _install_conflict_dialogs(monkeypatch, _ConflictDlg, _ResolutionDlg)
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: None)

        act.fetch_conflicts()

        assert resolution_exec_called, "resolution dialog should be offered when conflicts present"
        assert resolution_exec_called[0] == conflict_items

    def test_fetch_conflicts_resolution_accepted_triggers_worker(self, monkeypatch):
        act, _ = _make_action()
        _install_library_utils(monkeypatch)
        _set_library_mapping(monkeypatch)
        conflict_items = [{"id": 1, "uuid": "abc", "title": "Book A"}]
        _install_rest_client(monkeypatch, is_configured=True, conflicts=conflict_items)

        worker_calls = []
        class _WorkerWithResolve:
            def __init__(self, *_a, **_k): pass
            def resolve_conflicts(self, resolutions):
                worker_calls.append(resolutions)
                return {"resolved": 1, "errors": []}

        worker_mod = types.ModuleType("calibre_plugins.sync_calimob.sync_worker")
        worker_mod.SyncWorker = _WorkerWithResolve
        monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.sync_worker", worker_mod)

        class _ConflictDlg:
            def __init__(self, *_a, **_k): pass
            def exec(self): return 0

        class _ResolutionDlg:
            Accepted = 1
            def __init__(self, *_a, **_k): pass
            def exec(self): return self.Accepted
            def get_resolutions(self): return {"abc": "local"}

        _install_conflict_dialogs(monkeypatch, _ConflictDlg, _ResolutionDlg)
        info_calls = []
        monkeypatch.setattr("calibre.gui2.info_dialog", lambda *a, **k: info_calls.append(a))
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: None)

        act.fetch_conflicts()

        assert worker_calls == [{"abc": "local"}], "worker.resolve_conflicts should be called with resolutions"
        assert info_calls, "info_dialog should show after successful resolution"


# ─────────────────────────────────────────────────────────────────────────────
# show_configuration() + check_if_restart_needed()
# ─────────────────────────────────────────────────────────────────────────────

class TestShowConfiguration:
    def test_show_configuration_calls_do_user_config_when_no_restart_needed(self, monkeypatch):
        act, _ = _make_action()
        act.gui.must_restart_before_config = False

        do_config_calls = []
        act.interface_action_base_plugin = SimpleNamespace(
            do_user_config=lambda gui: do_config_calls.append(gui)
        )

        act.show_configuration()

        assert do_config_calls == [act.gui], "do_user_config should be called with gui"

    def test_show_configuration_skips_config_when_restart_needed_and_user_accepts(self, monkeypatch):
        act, _ = _make_action()
        act.gui.must_restart_before_config = True

        do_config_calls = []
        act.interface_action_base_plugin = SimpleNamespace(
            do_user_config=lambda gui: do_config_calls.append(gui)
        )
        monkeypatch.setattr("calibre.gui2.show_restart_warning", lambda msg: True, raising=False)

        act.show_configuration()

        assert do_config_calls == [], "do_user_config must NOT be called when restart required"
        act.gui.quit.assert_called_once_with(restart=True)

    def test_show_configuration_skips_config_when_restart_needed_and_user_cancels(self, monkeypatch):
        act, _ = _make_action()
        act.gui.must_restart_before_config = True

        do_config_calls = []
        act.interface_action_base_plugin = SimpleNamespace(
            do_user_config=lambda gui: do_config_calls.append(gui)
        )
        monkeypatch.setattr("calibre.gui2.show_restart_warning", lambda msg: False, raising=False)

        act.show_configuration()

        assert do_config_calls == [], "do_user_config must NOT be called when user cancels restart"
        act.gui.quit.assert_not_called()

    def test_check_if_restart_needed_returns_false_when_no_restart(self):
        act, _ = _make_action()
        act.gui.must_restart_before_config = False
        result = act.check_if_restart_needed()
        assert result is False

    def test_check_if_restart_needed_returns_true_when_user_cancels_restart(self, monkeypatch):
        act, _ = _make_action()
        act.gui.must_restart_before_config = True
        monkeypatch.setattr("calibre.gui2.show_restart_warning", lambda msg: False, raising=False)
        result = act.check_if_restart_needed()
        assert result is True

    def test_check_if_restart_needed_quits_when_user_accepts_restart(self, monkeypatch):
        act, _ = _make_action()
        act.gui.must_restart_before_config = True
        monkeypatch.setattr("calibre.gui2.show_restart_warning", lambda msg: True, raising=False)
        act.check_if_restart_needed()
        act.gui.quit.assert_called_once_with(restart=True)


# ─────────────────────────────────────────────────────────────────────────────
# Plugin-Calibre config init edge cases (get_plugin_store)
# ─────────────────────────────────────────────────────────────────────────────

class TestPluginStoreInit:
    """Edge cases for config store initialization and repair.

    These tests need a writable plugin_prefs dict (the autouse fixture provides
    a read-only MagicMock), so each test uses monkeypatch to replace plugin_prefs
    with a real dict.
    """

    def _real_prefs(self, monkeypatch):
        import calibre_plugins.sync_calimob.config as config_mod
        real = {}
        monkeypatch.setattr(config_mod, "plugin_prefs", real)
        return real, config_mod

    def test_get_plugin_store_returns_full_defaults_for_empty_prefs(self, monkeypatch):
        prefs, config_mod = self._real_prefs(monkeypatch)
        prefs[config_mod.STORE_PLUGIN] = {}
        store = config_mod.get_plugin_store(repair=True)
        for key, default in config_mod.DEFAULT_STORE_VALUES.items():
            assert key in store, f"default key {key!r} missing from repaired store"
            assert store[key] == default, f"key {key!r}: got {store[key]!r}, expected {default!r}"

    def test_get_plugin_store_repair_does_not_overwrite_user_values(self, monkeypatch):
        prefs, config_mod = self._real_prefs(monkeypatch)
        prefs[config_mod.STORE_PLUGIN] = {
            config_mod.KEY_REST_ENDPOINT: "https://my.server/api",
            config_mod.KEY_HTTP_TIMEOUT: 99,
        }
        store = config_mod.get_plugin_store(repair=True)
        assert store[config_mod.KEY_REST_ENDPOINT] == "https://my.server/api"
        assert store[config_mod.KEY_HTTP_TIMEOUT] == 99

    def test_get_plugin_store_no_repair_does_not_add_defaults(self, monkeypatch):
        prefs, config_mod = self._real_prefs(monkeypatch)
        prefs[config_mod.STORE_PLUGIN] = {config_mod.KEY_REST_ENDPOINT: "https://x/api"}
        store = config_mod.get_plugin_store(repair=False)
        # Only the key we set should be present (no backfill)
        assert config_mod.KEY_HTTP_TIMEOUT not in store

    def test_get_plugin_store_recovers_none_store(self, monkeypatch):
        prefs, config_mod = self._real_prefs(monkeypatch)
        prefs[config_mod.STORE_PLUGIN] = None
        store = config_mod.get_plugin_store(repair=True)
        assert isinstance(store, dict)
        assert config_mod.KEY_DEV_TOKEN in store

    def test_get_plugin_store_recovers_list_store(self, monkeypatch):
        prefs, config_mod = self._real_prefs(monkeypatch)
        prefs[config_mod.STORE_PLUGIN] = ["not", "a", "dict"]
        store = config_mod.get_plugin_store(repair=True)
        assert isinstance(store, dict)
        assert config_mod.KEY_REST_ENDPOINT in store

    def test_http_helper_no_crash_with_missing_dev_token_in_store(self, monkeypatch):
        """HttpHelper must not raise even if devkeyToken is absent from plugin store."""
        from calibre_plugins.sync_calimob import config as config_mod
        from calibre_plugins.sync_calimob import core as core_mod
        # Replace plugin_prefs with a real dict containing only a partial store
        partial = {config_mod.KEY_REST_ENDPOINT: "https://x/api"}
        real_prefs = {config_mod.STORE_PLUGIN: dict(partial)}
        monkeypatch.setattr(config_mod, "plugin_prefs", real_prefs)

        try:
            helper = core_mod.HttpHelper()
            assert helper.devkey_token == config_mod.DEFAULT_STORE_VALUES[config_mod.KEY_DEV_TOKEN]
        except KeyError as exc:
            pytest.fail(f"HttpHelper raised KeyError on partial store: {exc}")


# ─────────────────────────────────────────────────────────────────────────────
# Library mapping edge cases (config persistence layer)
# ─────────────────────────────────────────────────────────────────────────────

class TestLibraryMappingEdgeCases:
    def _real_prefs(self, monkeypatch):
        import calibre_plugins.sync_calimob.config as config_mod
        real = {}
        monkeypatch.setattr(config_mod, "plugin_prefs", real)
        return real, config_mod

    def test_mapping_missing_library_returns_empty_calimob_id(self, monkeypatch):
        prefs, config_mod = self._real_prefs(monkeypatch)
        prefs[config_mod.STORE_LIBRARY_MAPPINGS] = {}
        mapping = prefs.get(config_mod.STORE_LIBRARY_MAPPINGS, {}).get("nonexistent", {})
        assert mapping.get(config_mod.KEY_CALIMOB_LIBRARY_ID) is None

    def test_mapping_sync_disabled_by_default_for_new_entry(self, monkeypatch):
        prefs, config_mod = self._real_prefs(monkeypatch)
        prefs[config_mod.STORE_LIBRARY_MAPPINGS] = {
            "lib-new": {config_mod.KEY_CALIMOB_LIBRARY_ID: "5"}
        }
        mapping = prefs.get(config_mod.STORE_LIBRARY_MAPPINGS, {}).get("lib-new", {})
        # KEY_SYNC_ENABLED not set → defaults to False
        assert not mapping.get(config_mod.KEY_SYNC_ENABLED, False)

    def test_mapping_multiple_libraries_independent(self, monkeypatch):
        prefs, config_mod = self._real_prefs(monkeypatch)
        prefs[config_mod.STORE_LIBRARY_MAPPINGS] = {
            "lib-a": {config_mod.KEY_CALIMOB_LIBRARY_ID: "1", config_mod.KEY_SYNC_ENABLED: True},
            "lib-b": {config_mod.KEY_CALIMOB_LIBRARY_ID: "2", config_mod.KEY_SYNC_ENABLED: False},
        }
        mappings = prefs.get(config_mod.STORE_LIBRARY_MAPPINGS, {})
        assert mappings["lib-a"][config_mod.KEY_CALIMOB_LIBRARY_ID] == "1"
        assert mappings["lib-b"][config_mod.KEY_CALIMOB_LIBRARY_ID] == "2"
        assert mappings["lib-a"][config_mod.KEY_SYNC_ENABLED] is True
        assert mappings["lib-b"][config_mod.KEY_SYNC_ENABLED] is False

    def test_fetch_conflicts_routes_to_correct_library_calimob_id(self, monkeypatch):
        """fetch_conflicts must use the calimob_library_id for the CURRENT library, not another."""
        act, _ = _make_action()
        _install_library_utils(monkeypatch, library_id="lib-current")

        # Replace plugin_prefs with a real dict so fetch_conflicts reads the right mapping
        prefs, config_mod = self._real_prefs(monkeypatch)
        prefs[config_mod.STORE_LIBRARY_MAPPINGS] = {
            "lib-current": {cfg.KEY_CALIMOB_LIBRARY_ID: "99", cfg.KEY_SYNC_ENABLED: True},
            "lib-other": {cfg.KEY_CALIMOB_LIBRARY_ID: "1",  cfg.KEY_SYNC_ENABLED: True},
        }

        called_with = {}

        class _FakeClient:
            def __init__(self, *_a, **_k): pass
            def is_configured(self): return True
            def get_sync_conflicts(self, **kw):
                called_with.update(kw)
                return {"conflicts": []}

        rest_mod = types.ModuleType("calibre_plugins.sync_calimob.rest_client")
        rest_mod.RestApiClient = _FakeClient
        monkeypatch.setitem(sys.modules, "calibre_plugins.sync_calimob.rest_client", rest_mod)

        _install_conflict_dialogs(monkeypatch)
        monkeypatch.setattr("calibre.gui2.error_dialog", lambda *a, **k: None)

        act.fetch_conflicts()

        assert called_with.get("library_id") == "99", (
            "fetch_conflicts must use calimob_library_id='99' for 'lib-current', not '1' from 'lib-other'"
        )
