from __future__ import annotations

import sys
import types
from types import SimpleNamespace

from PyQt5.Qt import QToolButton

if not hasattr(QToolButton, "InstantPopup"):
    QToolButton.InstantPopup = 0

from calibre_plugins.sync_calimob import action as action_mod
from calibre_plugins.sync_calimob import config as cfg


def _make_action():
    act = action_mod.SyncCalimobAction.__new__(action_mod.SyncCalimobAction)
    db = SimpleNamespace(
        get_metadata=lambda *_a, **_k: SimpleNamespace(uuid='book-uuid-from-db'),
    )
    act.gui = SimpleNamespace(current_db=db)
    return act, db


def _set_library_mapping(library_uuid='lib-uuid', calimob_library_id='77', enabled=True):
    cfg.plugin_prefs = {
        cfg.STORE_LIBRARY_MAPPINGS: {
            library_uuid: {
                cfg.KEY_CALIMOB_LIBRARY_ID: calimob_library_id,
                cfg.KEY_SYNC_ENABLED: enabled,
            }
        }
    }


def _install_runtime_stubs(
    monkeypatch,
    *,
    rest_client_cls,
    worker_cls,
    progress_dialog_cls,
    library_id='lib-uuid',
):
    rest_mod = types.ModuleType('calibre_plugins.sync_calimob.rest_client')
    rest_mod.RestApiClient = rest_client_cls
    monkeypatch.setitem(sys.modules, 'calibre_plugins.sync_calimob.rest_client', rest_mod)

    worker_mod = types.ModuleType('calibre_plugins.sync_calimob.sync_worker')
    worker_mod.SyncWorker = worker_cls
    monkeypatch.setitem(sys.modules, 'calibre_plugins.sync_calimob.sync_worker', worker_mod)

    progress_mod = types.ModuleType('calibre_plugins.sync_calimob.sync_progress_dialog')
    progress_mod.SyncProgressDialog = progress_dialog_cls
    monkeypatch.setitem(sys.modules, 'calibre_plugins.sync_calimob.sync_progress_dialog', progress_mod)

    lib_mod = types.ModuleType('calibre_plugins.sync_calimob.library_utils')
    lib_mod.get_calibre_library_id = lambda _db: library_id
    monkeypatch.setitem(sys.modules, 'calibre_plugins.sync_calimob.library_utils', lib_mod)


def test_sync_selected_with_calimob_happy_path(monkeypatch):
    act, db = _make_action()
    act.get_selected_book_ids = lambda: [11, 22]
    _set_library_mapping()

    monkeypatch.setattr('calibre.gui2.question_dialog', lambda *a, **k: True)
    errors = []
    monkeypatch.setattr('calibre.gui2.error_dialog', lambda *a, **k: errors.append((a, k)))

    progress_state = {'shown': False, 'summary': None}

    class _FakeProgressDialog:
        def __init__(self, *_a, **_k):
            pass

        def show(self):
            progress_state['shown'] = True

        def update_progress(self, *_a, **_k):
            return None

        def show_summary(self, summary):
            progress_state['summary'] = summary

    client_calls = {'is_configured': 0}

    class _FakeClient:
        def __init__(self, *_a, **_k):
            pass

        def is_configured(self):
            client_calls['is_configured'] += 1
            return True

    worker_calls = {'prefetch': None, 'push': None}

    class _FakeWorker:
        def __init__(self, _gui, _db, _library_id, _calimob_library_id):
            assert _db is db

        def prefetch_selected_remote(self, book_ids):
            worker_calls['prefetch'] = list(book_ids)

        def push_sync(self, progress_callback, full_sync=False, allowed_book_ids=None, use_upsert=False):
            _ = progress_callback
            worker_calls['push'] = {
                'full_sync': full_sync,
                'allowed_book_ids': list(allowed_book_ids or []),
                'use_upsert': use_upsert,
            }
            return {'errors': [], 'books_synced': 2}

    _install_runtime_stubs(
        monkeypatch,
        rest_client_cls=_FakeClient,
        worker_cls=_FakeWorker,
        progress_dialog_cls=_FakeProgressDialog,
        library_id='lib-uuid',
    )

    act.sync_selected_with_calimob()

    assert errors == []
    assert client_calls['is_configured'] == 1
    assert worker_calls['prefetch'] == [11, 22]
    assert worker_calls['push'] == {
        'full_sync': True,
        'allowed_book_ids': [11, 22],
        'use_upsert': True,
    }
    assert progress_state['shown'] is True
    assert progress_state['summary']['push']['books_synced'] == 2
    assert progress_state['summary']['total_errors'] == []


def test_sync_selected_with_calimob_no_selection_shows_error(monkeypatch):
    act, _db = _make_action()
    act.get_selected_book_ids = lambda: []

    class _NoopClient:
        def __init__(self, *_a, **_k):
            pass

        def is_configured(self):
            return True

    class _NoopWorker:
        def __init__(self, *_a, **_k):
            pass

    class _NoopProgress:
        def __init__(self, *_a, **_k):
            pass

    _install_runtime_stubs(
        monkeypatch,
        rest_client_cls=_NoopClient,
        worker_cls=_NoopWorker,
        progress_dialog_cls=_NoopProgress,
    )

    errors = []
    monkeypatch.setattr('calibre.gui2.error_dialog', lambda *a, **k: errors.append((a, k)))

    act.sync_selected_with_calimob()

    assert errors, 'expected an error dialog when no rows are selected'
    assert 'No Selection' in str(errors[0][0][1])


def test_restore_version_for_selected_happy_path(monkeypatch):
    act, db = _make_action()
    act.get_selected_book_ids = lambda: [42]
    _set_library_mapping()

    monkeypatch.setattr('calibre_plugins.sync_calimob.config.get_cached_book_uuid', lambda *a, **k: 'book-uuid-42')
    errors = []
    monkeypatch.setattr(action_mod, 'error_dialog', lambda *a, **k: errors.append((a, k)))
    monkeypatch.setattr('calibre.gui2.info_dialog', lambda *a, **k: None)

    client_calls = {'is_configured': 0, 'get_versions': 0}

    class _FakeClient:
        def __init__(self, *_a, **_k):
            pass

        def is_configured(self):
            client_calls['is_configured'] += 1
            return True

        def get_versions(self, *_a, **_k):
            client_calls['get_versions'] += 1
            return {'versions': [{'version_id': 1}]}

    class _FakeVersionRestoreDialog:
        Accepted = 1

        def __init__(self, *_a, **_k):
            self.restored_item = {'id': 42, 'uuid': 'book-uuid-42', 'title': 'Restored'}

        def exec(self):
            return self.Accepted

    progress_state = {'summary': None}

    class _FakeProgressDialog:
        def __init__(self, *_a, **_k):
            pass

        def show(self):
            return None

        def update_progress(self, *_a, **_k):
            return None

        def show_summary(self, summary):
            progress_state['summary'] = summary

    worker_calls = {'apply': None, 'push': None}

    class _FakeWorker:
        def __init__(self, _gui, _db, _library_id, _calimob_library_id):
            assert _db is db

        def _apply_update(self, item, skip_cover=False):
            worker_calls['apply'] = {'item': item, 'skip_cover': skip_cover}
            return 42, True

        def push_sync(self, progress_callback, full_sync=False, allowed_book_ids=None):
            _ = progress_callback
            worker_calls['push'] = {
                'full_sync': full_sync,
                'allowed_book_ids': list(allowed_book_ids or []),
            }
            return {'errors': [], 'books_synced': 1}

    monkeypatch.setattr(action_mod, 'VersionRestoreDialog', _FakeVersionRestoreDialog)
    _install_runtime_stubs(
        monkeypatch,
        rest_client_cls=_FakeClient,
        worker_cls=_FakeWorker,
        progress_dialog_cls=_FakeProgressDialog,
        library_id='lib-uuid',
    )

    act.restore_version_for_selected()

    assert errors == []
    assert client_calls['is_configured'] == 1
    assert client_calls['get_versions'] == 1
    assert worker_calls['apply']['item']['uuid'] == 'book-uuid-42'
    assert worker_calls['apply']['skip_cover'] is False
    assert worker_calls['push'] == {'full_sync': True, 'allowed_book_ids': [42]}
    assert progress_state['summary']['push']['books_synced'] == 1


def test_restore_version_for_selected_requires_exactly_one_book(monkeypatch):
    act, _db = _make_action()
    act.get_selected_book_ids = lambda: [1, 2]

    class _NoopClient:
        def __init__(self, *_a, **_k):
            pass

        def is_configured(self):
            return True

    class _NoopWorker:
        def __init__(self, *_a, **_k):
            pass

    class _NoopProgress:
        def __init__(self, *_a, **_k):
            pass

    _install_runtime_stubs(
        monkeypatch,
        rest_client_cls=_NoopClient,
        worker_cls=_NoopWorker,
        progress_dialog_cls=_NoopProgress,
    )

    errors = []
    monkeypatch.setattr(action_mod, 'error_dialog', lambda *a, **k: errors.append((a, k)))

    act.restore_version_for_selected()

    assert errors, 'expected error dialog when more than one row is selected'
    assert 'Select one book' in str(errors[0][0][1])
