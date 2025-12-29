"""Unit tests for the persistent mapping cache helpers defined alongside the plugin."""

from __future__ import (division, absolute_import, print_function, unicode_literals)

import sys
import unittest
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[3]
PLUGIN_DIR = PROJECT_ROOT / 'sync_calimob'
sys.path.insert(0, str(PLUGIN_DIR))

from mapping_cache import (
    STORE_BOOK_UUID_CACHE,
    update_book_mapping,
    get_book_mapping_entry,
    mark_book_deleted,
    get_book_uuid_cache_for_library,
)


class TestSyncMappingCache(unittest.TestCase):
    def setUp(self):
        self.plugin_prefs = {STORE_BOOK_UUID_CACHE: {}}

    def test_update_book_mapping_persists_uuid_and_meta(self):
        updates = {
            'uuid': '11111111-2222-3333-4444-555555555555',
            'title': 'Traceable Book',
            'client_ids': {'calibre:lib-1:42': '42'},
            'cover_hash': 'sha256:abc',
            'version': 'v1',
        }
        update_book_mapping(self.plugin_prefs, 'lib-1', 42, updates)

        entry = get_book_mapping_entry(self.plugin_prefs, 'lib-1', 42)
        self.assertEqual(entry['uuid'], updates['uuid'])
        self.assertEqual(entry['title'], 'Traceable Book')
        self.assertEqual(entry['client_ids'], {'calibre:lib-1:42': '42'})
        self.assertEqual(entry['cover_hash'], 'sha256:abc')
        self.assertEqual(entry['version'], 'v1')

    def test_mark_book_deleted_updates_flags(self):
        update_book_mapping(
            self.plugin_prefs,
            'lib-1',
            99,
            {'uuid': '00000000-1111-2222-3333-444444444444'}
        )
        mark_book_deleted(
            self.plugin_prefs,
            'lib-1',
            99,
            deleted_at='2025-12-30T12:00:00Z'
        )

        entry = get_book_mapping_entry(self.plugin_prefs, 'lib-1', 99)
        self.assertEqual(entry['uuid'], '00000000-1111-2222-3333-444444444444')
        self.assertTrue(entry['is_deleted'])
        self.assertEqual(entry['deleted_at'], '2025-12-30T12:00:00Z')
        self.assertEqual(entry['last_sync_result'], 'deleted')

    def test_get_book_uuid_cache_returns_rich_entries(self):
        update_book_mapping(self.plugin_prefs, 'lib-2', 5, {'uuid': 'abc', 'title': 'T'})
        update_book_mapping(self.plugin_prefs, 'lib-2', 7, {'uuid': 'def', 'title': 'Y'})

        cache = get_book_uuid_cache_for_library(self.plugin_prefs, 'lib-2')
        self.assertIn('5', cache)
        self.assertIn('7', cache)
        self.assertEqual(cache['5']['title'], 'T')
        self.assertEqual(cache['7']['uuid'], 'def')


if __name__ == '__main__':
    unittest.main()
