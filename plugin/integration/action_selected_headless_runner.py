#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""Headless runtime runner for selected/single book plugin actions.

Executed with calibre-debug:
  calibre-debug -e tests/plugin/integration/headless_action_selected_runner.py
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import importlib
import json
import os
import sys
import types
from types import SimpleNamespace


def _bootstrap_plugin_package(project_root):
    plugin_root = os.path.join(project_root, 'sync_calimob')
    if not os.path.isdir(plugin_root):
        raise RuntimeError('sync_calimob folder not found at %s' % plugin_root)

    if 'calibre_plugins' not in sys.modules:
        sys.modules['calibre_plugins'] = types.ModuleType('calibre_plugins')

    if 'calibre_plugins.sync_calimob' not in sys.modules:
        pkg = types.ModuleType('calibre_plugins.sync_calimob')
        pkg.__path__ = [plugin_root]
        pkg.PLUGIN_VERSION = 'headless-e2e'
        sys.modules['calibre_plugins.sync_calimob'] = pkg
        sys.modules['calibre_plugins'].sync_calimob = pkg

    return plugin_root


def _install_runtime_stubs(library_uuid='lib-uuid'):
    calls = {
        'prefetch': None,
        'push_sync_selected': None,
        'apply_restore': None,
        'push_restore': None,
        'errors': [],
    }

    class _FakeClient(object):
        def __init__(self, *_a, **_k):
            pass

        def is_configured(self):
            return True

        def get_versions(self, *_a, **_k):
            return {'versions': [{'version_id': 1}]}

    class _FakeProgressDialog(object):
        def __init__(self, *_a, **_k):
            pass

        def show(self):
            return None

        def update_progress(self, *_a, **_k):
            return None

        def show_summary(self, *_a, **_k):
            return None

    class _FakeWorker(object):
        def __init__(self, *_a, **_k):
            pass

        def prefetch_selected_remote(self, book_ids):
            calls['prefetch'] = list(book_ids)

        def _apply_update(self, item, skip_cover=False):
            calls['apply_restore'] = {'item': dict(item), 'skip_cover': bool(skip_cover)}
            return 42, True

        def push_sync(self, _progress_callback, full_sync=False, allowed_book_ids=None, use_upsert=False):
            payload = {
                'full_sync': bool(full_sync),
                'allowed_book_ids': list(allowed_book_ids or []),
                'use_upsert': bool(use_upsert),
            }
            if allowed_book_ids == [42]:
                calls['push_restore'] = payload
            else:
                calls['push_sync_selected'] = payload
            return {'errors': [], 'books_synced': len(payload['allowed_book_ids'])}

    rest_mod = types.ModuleType('calibre_plugins.sync_calimob.rest_client')
    rest_mod.RestApiClient = _FakeClient
    sys.modules['calibre_plugins.sync_calimob.rest_client'] = rest_mod

    worker_mod = types.ModuleType('calibre_plugins.sync_calimob.sync_worker')
    worker_mod.SyncWorker = _FakeWorker
    sys.modules['calibre_plugins.sync_calimob.sync_worker'] = worker_mod

    progress_mod = types.ModuleType('calibre_plugins.sync_calimob.sync_progress_dialog')
    progress_mod.SyncProgressDialog = _FakeProgressDialog
    sys.modules['calibre_plugins.sync_calimob.sync_progress_dialog'] = progress_mod

    lib_mod = types.ModuleType('calibre_plugins.sync_calimob.library_utils')
    lib_mod.get_calibre_library_id = lambda _db: library_uuid
    sys.modules['calibre_plugins.sync_calimob.library_utils'] = lib_mod

    return calls


def main():
    project_root = os.environ.get('CALIMOB_PROJECT_ROOT') or os.path.abspath(
        os.path.join(os.path.dirname(__file__), '../../..')
    )
    _bootstrap_plugin_package(project_root)

    cfg = importlib.import_module('calibre_plugins.sync_calimob.config')
    action_mod = importlib.import_module('calibre_plugins.sync_calimob.action')
    calibre_gui2 = importlib.import_module('calibre.gui2')

    library_uuid = 'lib-uuid'
    cfg.plugin_prefs = {
        cfg.STORE_LIBRARY_MAPPINGS: {
            library_uuid: {
                cfg.KEY_CALIMOB_LIBRARY_ID: '77',
                cfg.KEY_SYNC_ENABLED: True,
            }
        }
    }

    calls = _install_runtime_stubs(library_uuid=library_uuid)

    calibre_gui2.question_dialog = lambda *a, **k: True
    calibre_gui2.error_dialog = lambda *a, **k: calls['errors'].append({'title': a[1] if len(a) > 1 else '', 'msg': a[2] if len(a) > 2 else ''})
    calibre_gui2.info_dialog = lambda *a, **k: None

    class _FakeVersionRestoreDialog(object):
        Accepted = 1

        def __init__(self, *_a, **_k):
            self.restored_item = {'id': 42, 'uuid': 'book-uuid-42', 'title': 'Restored'}

        def exec(self):
            return self.Accepted

    action_mod.VersionRestoreDialog = _FakeVersionRestoreDialog
    cfg.get_cached_book_uuid = lambda *_a, **_k: 'book-uuid-42'

    act = action_mod.SyncCalimobAction.__new__(action_mod.SyncCalimobAction)
    db = SimpleNamespace(get_metadata=lambda *_a, **_k: SimpleNamespace(uuid='book-uuid-from-db'))
    act.gui = SimpleNamespace(current_db=db)

    # Scenario 1: sync selected books
    act.get_selected_book_ids = lambda: [11, 22]
    act.sync_selected_with_calimob()

    # Scenario 2: restore selected book version and push it
    act.get_selected_book_ids = lambda: [42]
    act.restore_version_for_selected()

    ok = (
        calls['prefetch'] == [11, 22]
        and calls['push_sync_selected'] == {
            'full_sync': True,
            'allowed_book_ids': [11, 22],
            'use_upsert': True,
        }
        and calls['apply_restore'] is not None
        and calls['apply_restore']['item'].get('uuid') == 'book-uuid-42'
        and calls['push_restore'] == {
            'full_sync': True,
            'allowed_book_ids': [42],
            'use_upsert': False,
        }
        and not calls['errors']
    )

    print(json.dumps({
        'ok': bool(ok),
        'calls': calls,
    }))
    return 0 if ok else 1


if __name__ == '__main__':
    raise SystemExit(main())
