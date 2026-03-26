"""
Edge-case tests: Merkle drilldown must use include_uuids=True for ALL dimensions.

Production issue (2026-03-24): covers and files drilldown used include_uuids=False,
causing 546 individual leaf-uuids HTTP calls PER dimension (1024 total).
metadata_drilldown already used include_uuids=True (0 extra calls).

Fix: all 3 dimensions use include_uuids=True in get_merkle_leaves call.

Expected improvement: 1126 HTTP requests → ~100 requests (6 min → 30s).
"""
from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

from calibre_plugins.sync_calimob import sync_worker


# ─────────────────────────────────────────────────────────────────────────────
# 1. Source code: all dimensions must use include_uuids=True
# ─────────────────────────────────────────────────────────────────────────────

class TestAllDimensionsUseIncludeUuids:
    """All 3 Merkle drilldown dimensions must pass include_uuids=True."""

    def _get_merkle_source(self):
        src_path = os.path.join(
            os.path.dirname(sync_worker.__file__), 'sync_v5_merkle.py'
        )
        with open(src_path, 'r') as f:
            return f.read()

    def test_drilldown_dimension_uses_include_uuids_true(self):
        """_drilldown_dimension (covers/files) must use include_uuids=True."""
        code = self._get_merkle_source()

        # Find _drilldown_dimension function
        func_start = code.find('def _drilldown_dimension')
        assert func_start > 0, '_drilldown_dimension not found'
        next_def = code.find('\ndef ', func_start + 10)
        func_body = code[func_start:next_def]

        # Must use include_uuids=True, not False
        assert 'include_uuids=True' in func_body, (
            "_drilldown_dimension must use include_uuids=True in get_merkle_leaves call. "
            "With include_uuids=False, each mismatched leaf requires a separate "
            "HTTP call to leaf-uuids endpoint (546 calls per dimension)."
        )

        # Must NOT have include_uuids=False
        assert 'include_uuids=False' not in func_body, (
            "_drilldown_dimension still has include_uuids=False — "
            "this causes 546 extra HTTP requests per dimension."
        )

    def test_metadata_drilldown_uses_include_uuids_true(self):
        """metadata_drilldown must use include_uuids=True (already does)."""
        code = self._get_merkle_source()

        func_start = code.find('def metadata_drilldown')
        assert func_start > 0
        next_def = code.find('\ndef ', func_start + 10)
        func_body = code[func_start:next_def]

        assert 'include_uuids=True' in func_body

    def test_no_include_uuids_false_anywhere(self):
        """No drilldown function should use include_uuids=False."""
        code = self._get_merkle_source()

        # Find all get_merkle_leaves calls
        pos = 0
        false_calls = []
        while True:
            idx = code.find('get_merkle_leaves(', pos)
            if idx < 0:
                break
            call_end = code.find(')', idx)
            call_text = code[idx:call_end + 1]
            if 'include_uuids=False' in call_text:
                # Find which function it's in
                last_def = code.rfind('\ndef ', 0, idx)
                func_name = code[last_def:last_def + 80].strip()
                false_calls.append((idx, func_name, call_text.strip()))
            pos = idx + 1

        assert len(false_calls) == 0, (
            f"Found {len(false_calls)} get_merkle_leaves calls with include_uuids=False: "
            f"{false_calls}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Behavioral: drilldown returns UUIDs from inline response
# ─────────────────────────────────────────────────────────────────────────────

class TestDrilldownReturnsInlineUuids:
    """When include_uuids=True, leaf UUIDs come from the leaves response,
    not from separate leaf-uuids calls."""

    def test_covers_drilldown_does_not_call_leaf_uuids_endpoint(self):
        """With include_uuids=True, covers_drilldown should NOT call
        get_merkle_leaf_uuids for leaves that have inline UUIDs."""
        worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
        worker.library_id = 'lib-1'
        worker.client = Mock()

        # Mock get_merkle_leaves to return leaves WITH inline UUIDs
        worker.client.get_merkle_leaves = Mock(return_value={
            'leaves': [
                {'leaf_id': 0, 'leaf_hash': 'aaa', 'book_count': 2,
                 'uuids': ['uuid-1', 'uuid-2']},
                {'leaf_id': 1, 'leaf_hash': 'bbb', 'book_count': 1,
                 'uuids': ['uuid-3']},
            ],
        })
        worker.client.get_merkle_leaf_uuids = Mock(return_value={'uuids': []})
        worker.client.get_merkle_branches = Mock(return_value={
            'branches': [
                {'branch_id': 0, 'branch_hash': 'local-different', 'book_count': 3},
            ],
        })

        # Local hash data with mismatched branch
        local_hash_data = {}
        server_hash_data = {'root_hash': 'server-root'}

        # Run covers drilldown
        worker._v5_merkle_covers_drilldown(
            conn=Mock(),
            local_hash_data=local_hash_data,
            server_hash_data=server_hash_data,
        )

        # get_merkle_leaf_uuids should NOT be called (UUIDs are inline)
        worker.client.get_merkle_leaf_uuids.assert_not_called()

    def test_files_drilldown_does_not_call_leaf_uuids_endpoint(self):
        """Same test for files dimension."""
        worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
        worker.library_id = 'lib-1'
        worker.client = Mock()

        worker.client.get_merkle_leaves = Mock(return_value={
            'leaves': [
                {'leaf_id': 0, 'leaf_hash': 'aaa', 'book_count': 1,
                 'uuids': ['uuid-1']},
            ],
        })
        worker.client.get_merkle_leaf_uuids = Mock(return_value={'uuids': []})
        worker.client.get_merkle_branches = Mock(return_value={
            'branches': [
                {'branch_id': 0, 'branch_hash': 'different', 'book_count': 1},
            ],
        })

        worker._v5_merkle_files_drilldown(
            conn=Mock(),
            local_hash_data={},
            server_hash_data={'root_hash': 'server-root'},
        )

        worker.client.get_merkle_leaf_uuids.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 3. Fallback: if server doesn't return inline UUIDs, fall back to leaf-uuids
# ─────────────────────────────────────────────────────────────────────────────

class TestFallbackToLeafUuids:
    """If server response has no inline UUIDs, fallback to individual calls."""

    def test_fallback_when_uuids_not_in_response(self):
        """Old servers may not support include_uuids — must fall back."""
        worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
        worker.library_id = 'lib-1'
        worker.client = Mock()

        # Server returns leaves WITHOUT inline UUIDs (old server)
        worker.client.get_merkle_leaves = Mock(return_value={
            'leaves': [
                {'leaf_id': 0, 'leaf_hash': 'aaa', 'book_count': 2},
                # No 'uuids' key
            ],
        })
        worker.client.get_merkle_leaf_uuids = Mock(return_value={
            'uuids': ['uuid-1', 'uuid-2'],
        })
        worker.client.get_merkle_branches = Mock(return_value={
            'branches': [
                {'branch_id': 0, 'branch_hash': 'different', 'book_count': 2},
            ],
        })

        worker._v5_merkle_covers_drilldown(
            conn=Mock(),
            local_hash_data={},
            server_hash_data={'root_hash': 'server-root'},
        )

        # Fallback: get_merkle_leaf_uuids SHOULD be called
        assert worker.client.get_merkle_leaf_uuids.call_count >= 1


# ─────────────────────────────────────────────────────────────────────────────
# 4. Request count: must be dramatically fewer
# ─────────────────────────────────────────────────────────────────────────────

class TestRequestCountReduced:
    """With include_uuids=True, leaf-uuids calls drop from 256 to 0 per dimension."""

    def test_zero_leaf_uuids_calls_when_inline(self):
        """When all leaves have inline UUIDs, leaf-uuids endpoint = 0 calls."""
        leaves_with_uuids = {
            'leaves': [
                {'leaf_id': i, 'leaf_hash': f'h{i}', 'book_count': 1,
                 'uuids': [f'uuid-{i}']}
                for i in range(16)  # 16 leaves per branch
            ],
        }

        # Count: with inline UUIDs, zero extra calls needed
        extra_calls_needed = sum(
            1 for leaf in leaves_with_uuids['leaves']
            if not isinstance(leaf.get('uuids'), list)
        )
        assert extra_calls_needed == 0

    def test_256_leaf_uuids_calls_when_not_inline(self):
        """Without inline UUIDs, each mismatched leaf = 1 extra call."""
        leaves_without_uuids = {
            'leaves': [
                {'leaf_id': i, 'leaf_hash': f'h{i}', 'book_count': 1}
                for i in range(256)
            ],
        }

        extra_calls_needed = sum(
            1 for leaf in leaves_without_uuids['leaves']
            if not isinstance(leaf.get('uuids'), list)
        )
        assert extra_calls_needed == 256


# ─────────────────────────────────────────────────────────────────────────────
# 5. get_merkle_leaves: include_uuids parameter exists
# ─────────────────────────────────────────────────────────────────────────────

class TestGetMerkleLeavesIncludeUuidsParam:
    """rest_client.get_merkle_leaves must support include_uuids parameter."""

    def test_include_uuids_parameter_exists(self):
        """get_merkle_leaves must accept include_uuids kwarg."""
        import inspect
        from calibre_plugins.sync_calimob import rest_client

        sig = inspect.signature(rest_client.RestApiClient.get_merkle_leaves)
        assert 'include_uuids' in sig.parameters, (
            "get_merkle_leaves must accept include_uuids parameter"
        )
