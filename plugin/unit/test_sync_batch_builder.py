"""
Unit tests for sync_batch_builder.py — batch payload construction.

Covers:
  sb01: Build batch from 20 entries → correct payload structure
  sb02: Batch with deleted books → 'd' array populated
  sb03: Hash prefix stripping ("sha256:abc" → "abc")
  sb04: Empty hash_data → empty 'b', empty 'd'
  sb05: Batched payloads (batch_size) → generator yields correct chunks
  sb06: Deleted UUIDs only in first batch when using batch_size
  sb07: None/missing hash fields → preserved as None
  sb08: Mixed prefixed and bare hashes
  sb09: Sort order follows Merkle leaf ordering
"""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

# Load sync_batch_builder via importlib (avoids calibre __init__ imports)
_plugin_root = Path(__file__).resolve().parents[3] / 'sync_calimob'
sys.path.insert(0, str(_plugin_root))

# Load sync_leaf_ordering first (dependency)
_leaf_path = _plugin_root / 'sync_leaf_ordering.py'
_leaf_spec = importlib.util.spec_from_file_location('sync_leaf_ordering', str(_leaf_path))
sync_leaf_ordering = importlib.util.module_from_spec(_leaf_spec)
sys.modules['sync_leaf_ordering'] = sync_leaf_ordering
_leaf_spec.loader.exec_module(sync_leaf_ordering)

# Now load sync_batch_builder
_bb_path = _plugin_root / 'sync_batch_builder.py'
_bb_spec = importlib.util.spec_from_file_location('sync_batch_builder', str(_bb_path))
sync_batch_builder = importlib.util.module_from_spec(_bb_spec)
_bb_spec.loader.exec_module(sync_batch_builder)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _make_hash_data(n, prefix=True):
    """Build hash_data dict with n entries.

    If prefix=True, hashes include 'sha256:' prefix.
    """
    data = {}
    for i in range(n):
        uuid = f'aaaaaaaa-bbbb-cccc-dddd-{i:012d}'
        h = f'{i:064x}'
        ph = f'sha256:{h}' if prefix else h
        data[uuid] = {
            'm': ph,
            'c': ph if i % 2 == 0 else None,
            'f': ph if i % 3 == 0 else None,
        }
    return data


# ── Tests ────────────────────────────────────────────────────────────────────

class TestBuildSyncV5Payload:

    def test_sb01_20_entries_correct_structure(self):
        """Build batch from 20 entries → payload has 'b' dict with 20 keys and 'd' list."""
        hd = _make_hash_data(20)
        payload = sync_batch_builder.build_sync_v5_payload(hd)

        assert isinstance(payload, dict)
        assert 'b' in payload
        assert 'd' in payload
        assert len(payload['b']) == 20
        assert isinstance(payload['d'], list)
        assert payload['d'] == []

        # Each entry must have m, c, f keys
        for uuid, entry in payload['b'].items():
            assert 'm' in entry
            assert 'c' in entry
            assert 'f' in entry

    def test_sb02_deleted_books_populate_d_array(self):
        """Batch with deleted books → 'd' array contains the deleted UUIDs."""
        hd = _make_hash_data(5)
        deleted = ['del-uuid-1', 'del-uuid-2', 'del-uuid-3']
        payload = sync_batch_builder.build_sync_v5_payload(hd, deleted_uuids=deleted)

        assert payload['d'] == deleted
        assert len(payload['b']) == 5

    def test_sb03_hash_prefix_stripping(self):
        """sha256: prefix must be stripped from all hash values."""
        hd = {
            'uuid-1': {
                'm': 'sha256:aabbccdd',
                'c': 'sha256:11223344',
                'f': 'sha256:55667788',
            }
        }
        payload = sync_batch_builder.build_sync_v5_payload(hd)

        entry = payload['b']['uuid-1']
        assert entry['m'] == 'aabbccdd'
        assert entry['c'] == '11223344'
        assert entry['f'] == '55667788'

    def test_sb04_empty_hash_data(self):
        """Empty hash_data → empty 'b' and 'd'."""
        payload = sync_batch_builder.build_sync_v5_payload({})
        assert payload['b'] == {}
        assert payload['d'] == []

    def test_sb05_batched_payloads_generator(self):
        """batch_size splits into multiple payloads via generator."""
        hd = _make_hash_data(25)
        batches = list(sync_batch_builder.build_sync_v5_payload(hd, batch_size=10))

        assert len(batches) == 3  # 10 + 10 + 5
        total_books = sum(len(b['b']) for b in batches)
        assert total_books == 25

    def test_sb06_deleted_only_in_first_batch(self):
        """When using batch_size, deleted UUIDs appear only in the first batch."""
        hd = _make_hash_data(20)
        deleted = ['del-1', 'del-2']
        batches = list(sync_batch_builder.build_sync_v5_payload(
            hd, deleted_uuids=deleted, batch_size=10
        ))

        assert batches[0]['d'] == deleted
        assert batches[1]['d'] == []

    def test_sb07_none_hash_fields_preserved(self):
        """None hash values pass through without error."""
        hd = {
            'uuid-1': {'m': None, 'c': None, 'f': None}
        }
        payload = sync_batch_builder.build_sync_v5_payload(hd)

        entry = payload['b']['uuid-1']
        assert entry['m'] is None
        assert entry['c'] is None
        assert entry['f'] is None

    def test_sb08_mixed_prefixed_and_bare_hashes(self):
        """Mix of sha256:-prefixed and bare hashes both work correctly."""
        hd = {
            'uuid-1': {'m': 'sha256:aabb', 'c': 'bare1234', 'f': None},
            'uuid-2': {'m': 'noprefixhash', 'c': 'sha256:ccdd', 'f': 'sha256:eeff'},
        }
        payload = sync_batch_builder.build_sync_v5_payload(hd)

        assert payload['b']['uuid-1']['m'] == 'aabb'
        assert payload['b']['uuid-1']['c'] == 'bare1234'
        assert payload['b']['uuid-2']['m'] == 'noprefixhash'
        assert payload['b']['uuid-2']['c'] == 'ccdd'
        assert payload['b']['uuid-2']['f'] == 'eeff'

    def test_sb09_sort_order_follows_merkle_leaf(self):
        """UUIDs in the payload 'b' dict should be ordered by Merkle leaf."""
        hd = _make_hash_data(50, prefix=False)
        payload = sync_batch_builder.build_sync_v5_payload(hd)

        uuids_in_payload = list(payload['b'].keys())
        expected_order = sync_leaf_ordering.sort_by_merkle_leaf(list(hd.keys()))
        assert uuids_in_payload == expected_order


class TestStripHashPrefix:

    def test_strips_sha256_prefix(self):
        assert sync_batch_builder._strip_hash_prefix('sha256:abc123') == 'abc123'

    def test_bare_hash_unchanged(self):
        assert sync_batch_builder._strip_hash_prefix('abc123') == 'abc123'

    def test_none_returns_none(self):
        assert sync_batch_builder._strip_hash_prefix(None) is None

    def test_empty_string_returns_empty(self):
        assert sync_batch_builder._strip_hash_prefix('') == ''

    def test_non_string_returns_as_is(self):
        assert sync_batch_builder._strip_hash_prefix(42) == 42
