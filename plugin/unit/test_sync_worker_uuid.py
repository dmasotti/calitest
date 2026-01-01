"""
Unit tests for SyncWorker UUID handling.
"""

from __future__ import (unicode_literals, division, absolute_import, print_function)

from unittest.mock import Mock
import importlib.util
import sys
from pathlib import Path

plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'
sync_mapper_path = plugin_path / 'sync_mapper.py'
sync_worker_path = plugin_path / 'sync_worker.py'

# Load sync_mapper first and register it for sync_worker import
spec_mapper = importlib.util.spec_from_file_location('sync_mapper', str(sync_mapper_path))
sync_mapper = importlib.util.module_from_spec(spec_mapper)
spec_mapper.loader.exec_module(sync_mapper)

# Register sync_mapper for sync_worker import (config/rest_client stubs are provided by conftest)
sys.modules['calibre_plugins.sync_calimob.sync_mapper'] = sync_mapper
sys.modules.setdefault('calibre_plugins.sync_calimob.rest_client', Mock())

spec_worker = importlib.util.spec_from_file_location('sync_worker', str(sync_worker_path))
sync_worker = importlib.util.module_from_spec(spec_worker)
spec_worker.loader.exec_module(sync_worker)
SyncWorker = sync_worker.SyncWorker


class TestSyncWorkerUuid:
    def _make_worker(self, db, library_id='test-lib'):
        worker = SyncWorker.__new__(SyncWorker)
        worker.db = db
        worker.library_id = library_id
        return worker

    def test_resolve_local_book_id_prefers_id(self):
        db = Mock()
        db.data = Mock()
        db.data.has_id = Mock(side_effect=lambda bid: bid == 10)
        worker = self._make_worker(db)

        item = {
            'id': 10,
            'uuid': '11111111-2222-3333-4444-555555555555',
        }
        assert worker._resolve_local_book_id(item) == 10

    def test_resolve_local_book_id_uses_uuid(self):
        db = Mock()
        db.data = Mock()
        db.data.has_id = Mock(side_effect=lambda bid: bid == 77)
        db.get_id_from_uuid = Mock(return_value=77)
        worker = self._make_worker(db)

        item = {
            'id': None,
            'uuid': '11111111-2222-3333-4444-555555555555',
        }
        assert worker._resolve_local_book_id(item) == 77

    def test_ensure_book_uuid_existing(self):
        db = Mock()
        db.set_metadata = Mock()
        worker = self._make_worker(db)

        metadata = Mock()
        metadata.uuid = 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee'

        assert worker._ensure_book_uuid(1, metadata) == metadata.uuid
        db.set_metadata.assert_not_called()

    def test_ensure_book_uuid_sets_when_missing(self):
        db = Mock()
        db.set_metadata = Mock()
        worker = self._make_worker(db)

        metadata = Mock()
        metadata.uuid = None

        new_uuid = worker._ensure_book_uuid(1, metadata)
        assert new_uuid
        db.set_metadata.assert_called_once()
