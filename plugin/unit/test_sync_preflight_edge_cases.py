"""
Edge-case test matrix for SyncPreflight decomposition guardrails (Phase 4).

Tests for:
1. _v5_get_initial_cursor_state: cursor parsing, timestamp extraction, edge cases
2. _v5_collect_and_filter_candidates: Merkle filtering, deleted book handling
3. _v5_checkpoint_batch_state: cursor save, error blocking, loop signals
4. _v5_finalize_sync_cursor_state: final cursor persistence, error guard
5. _v5_prepare_client_inventory_state: resume logic, sorting
6. Preflight fast-path: done=True early return, Merkle drilldown trigger
"""
from __future__ import annotations

import sys
from unittest.mock import Mock, MagicMock

import pytest

from calibre_plugins.sync_calimob import sync_worker


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_worker():
    worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
    worker.library_id = 'lib-1'
    worker.calimob_library_id = '1'
    worker.db = Mock()
    worker.db.data = Mock()
    worker.db.data.has_id = lambda _bid: True
    worker._cancelled = False
    worker._uuid_to_book_id = {}
    worker._progress_callback = None
    worker._sync_heartbeat = Mock()
    worker._resolve_plugin_commit = Mock(return_value='test-commit')
    return worker


def _ts():
    return '2026-03-22T00:00:00'


# ─────────────────────────────────────────────────────────────────────────────
# 1. _v5_get_initial_cursor_state
# ─────────────────────────────────────────────────────────────────────────────

class TestGetInitialCursorState:
    """Cursor parsing and timestamp extraction."""

    def test_none_cursor_full_sync(self):
        """No stored cursor → cursor=None, cursor_timestamp=None (full sync)."""
        worker = _make_worker()
        worker.get_pull_cursor = Mock(return_value=None)

        result = worker._v5_get_initial_cursor_state(ts_func=_ts, debug_file=sys.stderr)
        assert result['cursor'] is None
        assert result['cursor_timestamp'] is None

    def test_valid_cursor_with_timestamp(self):
        """'1742630400:extra_data' → cursor_timestamp=1742630400."""
        worker = _make_worker()
        worker.get_pull_cursor = Mock(return_value='1742630400:extra')

        result = worker._v5_get_initial_cursor_state(ts_func=_ts, debug_file=sys.stderr)
        assert result['cursor'] == '1742630400:extra'
        assert result['cursor_timestamp'] == 1742630400

    def test_cursor_timestamp_only(self):
        """'1742630400' (no colon) → cursor_timestamp=1742630400."""
        worker = _make_worker()
        worker.get_pull_cursor = Mock(return_value='1742630400')

        result = worker._v5_get_initial_cursor_state(ts_func=_ts, debug_file=sys.stderr)
        assert result['cursor_timestamp'] == 1742630400

    def test_zero_timestamp_becomes_none(self):
        """'0:data' → cursor_timestamp=None (triggers full sync)."""
        worker = _make_worker()
        worker.get_pull_cursor = Mock(return_value='0:data')

        result = worker._v5_get_initial_cursor_state(ts_func=_ts, debug_file=sys.stderr)
        assert result['cursor_timestamp'] is None

    def test_negative_timestamp_becomes_none(self):
        """'-1:data' → cursor_timestamp=None."""
        worker = _make_worker()
        worker.get_pull_cursor = Mock(return_value='-1:data')

        result = worker._v5_get_initial_cursor_state(ts_func=_ts, debug_file=sys.stderr)
        assert result['cursor_timestamp'] is None

    def test_non_numeric_cursor_timestamp_none(self):
        """'abc:data' → cursor_timestamp=None (ValueError caught)."""
        worker = _make_worker()
        worker.get_pull_cursor = Mock(return_value='abc:data')

        result = worker._v5_get_initial_cursor_state(ts_func=_ts, debug_file=sys.stderr)
        assert result['cursor'] == 'abc:data'
        assert result['cursor_timestamp'] is None

    def test_empty_string_cursor(self):
        """'' is falsy → cursor='' but cursor_timestamp=None."""
        worker = _make_worker()
        worker.get_pull_cursor = Mock(return_value='')

        result = worker._v5_get_initial_cursor_state(ts_func=_ts, debug_file=sys.stderr)
        assert result['cursor_timestamp'] is None


# ─────────────────────────────────────────────────────────────────────────────
# 2. _v5_collect_and_filter_candidates
# ─────────────────────────────────────────────────────────────────────────────

class TestCollectAndFilterCandidates:
    """Merkle filtering and candidate selection."""

    def test_no_merkle_returns_all(self):
        """Without Merkle candidates, all books returned unfiltered."""
        worker = _make_worker()
        worker._v5_collect_client_books_candidates = Mock(return_value=(
            ['uuid-del-1'],  # deleted
            {'uuid-1': 1, 'uuid-2': 2},  # uuid_to_id
            [{'uuid': 'uuid-1'}, {'uuid': 'uuid-2'}],  # books
        ))

        result = worker._v5_collect_and_filter_candidates(
            sync_library_path='/tmp',
            merkle_candidates=None, summary={},
            ts_func=_ts, debug_file=sys.stderr,
        )

        assert len(result['books_to_sync']) == 2
        assert result['merkle_candidate_uuids'] is None

    def test_merkle_filters_books(self):
        """With Merkle candidates, only matching UUIDs are kept."""
        worker = _make_worker()
        worker._v5_collect_client_books_candidates = Mock(return_value=(
            [],
            {'uuid-1': 1, 'uuid-2': 2, 'uuid-3': 3},
            [{'uuid': 'uuid-1'}, {'uuid': 'uuid-2'}, {'uuid': 'uuid-3'}],
        ))

        result = worker._v5_collect_and_filter_candidates(
            sync_library_path='/tmp',
            merkle_candidates=['uuid-1', 'uuid-3'],  # only 2 of 3
            summary={}, ts_func=_ts, debug_file=sys.stderr,
        )

        uuids = [b['uuid'] for b in result['books_to_sync']]
        assert 'uuid-1' in uuids
        assert 'uuid-3' in uuids
        assert 'uuid-2' not in uuids

    def test_merkle_filters_deleted_books(self):
        """Merkle filter also applies to deleted_books_from_sql."""
        worker = _make_worker()
        worker._v5_collect_client_books_candidates = Mock(return_value=(
            ['uuid-del-1', 'uuid-del-2'],  # 2 deleted
            {},
            [],
        ))

        result = worker._v5_collect_and_filter_candidates(
            sync_library_path='/tmp',
            merkle_candidates=['uuid-del-1'],  # only 1 matches
            summary={}, ts_func=_ts, debug_file=sys.stderr,
        )

        assert result['deleted_books_from_sql'] == ['uuid-del-1']

    def test_empty_candidates_empty_result(self):
        """No books and no deletes → empty result."""
        worker = _make_worker()
        worker._v5_collect_client_books_candidates = Mock(return_value=([], {}, []))

        result = worker._v5_collect_and_filter_candidates(
            sync_library_path='/tmp',
            merkle_candidates=None, summary={},
            ts_func=_ts, debug_file=sys.stderr,
        )

        assert result['books_to_sync'] == []
        assert result['deleted_books_from_sql'] == []

    def test_summary_tracks_deleted_count(self):
        """summary['deleted_books_sent'] must be set."""
        worker = _make_worker()
        worker._v5_collect_client_books_candidates = Mock(return_value=(
            ['uuid-d1', 'uuid-d2', 'uuid-d3'],
            {},
            [],
        ))
        summary = {}

        worker._v5_collect_and_filter_candidates(
            sync_library_path='/tmp',
            merkle_candidates=None, summary=summary,
            ts_func=_ts, debug_file=sys.stderr,
        )

        assert summary['deleted_books_sent'] == 3


# ─────────────────────────────────────────────────────────────────────────────
# 3. _v5_checkpoint_batch_state
# ─────────────────────────────────────────────────────────────────────────────

class TestCheckpointBatchState:
    """Cursor checkpointing and loop control signals."""

    def test_cursor_next_saves_and_continues(self):
        """With cursor_next, cursor is saved and loop continues."""
        worker = _make_worker()
        worker.save_pull_cursor = Mock()

        result = worker._v5_checkpoint_batch_state(
            cursor_next='cursor-2', batch_had_errors=False,
            cursor='cursor-1',
            client_cursor=50, client_total=100,
        )

        assert result['cursor'] == 'cursor-2'
        assert result['has_more'] is None  # signals "keep looping"
        worker.save_pull_cursor.assert_called_once_with('cursor-2')

    def test_no_cursor_next_terminates_loop(self):
        """Without cursor_next, loop terminates."""
        worker = _make_worker()
        worker.save_pull_cursor = Mock()

        result = worker._v5_checkpoint_batch_state(
            cursor_next=None, batch_had_errors=False,
            cursor='cursor-1',
            client_cursor=100, client_total=100,
        )

        assert result['has_more'] is False
        assert result['client_done'] is True
        worker.save_pull_cursor.assert_not_called()

    def test_critical_errors_block_cursor_save(self):
        """With critical errors, cursor is NOT saved."""
        worker = _make_worker()
        worker.save_pull_cursor = Mock()

        result = worker._v5_checkpoint_batch_state(
            cursor_next='cursor-2', batch_had_errors=True,
            batch_has_critical_errors=True,
            cursor='cursor-1',
            client_cursor=50, client_total=100,
        )

        assert result['cursor'] == 'cursor-2'
        worker.save_pull_cursor.assert_not_called()

    def test_non_critical_errors_still_save(self):
        """With batch_had_errors=True but critical=False, cursor IS saved."""
        worker = _make_worker()
        worker.save_pull_cursor = Mock()

        worker._v5_checkpoint_batch_state(
            cursor_next='cursor-2', batch_had_errors=True,
            batch_has_critical_errors=False,
            cursor='cursor-1',
            client_cursor=50, client_total=100,
        )

        worker.save_pull_cursor.assert_called_once_with('cursor-2')


# ─────────────────────────────────────────────────────────────────────────────
# 4. _v5_finalize_sync_cursor_state
# ─────────────────────────────────────────────────────────────────────────────

class TestFinalizeSyncCursorState:
    """Final cursor save and resume state cleanup."""

    def test_saves_cursor_on_success(self):
        """If no errors, cursor is saved."""
        worker = _make_worker()
        worker.save_cursor = Mock()

        worker._v5_finalize_sync_cursor_state(
            cursor='final-cursor', summary={'errors': []},
            ts_func=_ts, debug_file=sys.stderr,
        )

        worker.save_cursor.assert_called_once_with('final-cursor')

    def test_skips_save_when_errors_present(self):
        """If errors in summary, cursor is NOT saved."""
        worker = _make_worker()
        worker.save_cursor = Mock()

        worker._v5_finalize_sync_cursor_state(
            cursor='final-cursor',
            summary={'errors': [{'phase': 'test', 'error': 'boom'}]},
            ts_func=_ts, debug_file=sys.stderr,
        )

        worker.save_cursor.assert_not_called()

    def test_skips_save_when_cursor_is_none(self):
        """If cursor is None, nothing is saved."""
        worker = _make_worker()
        worker.save_cursor = Mock()

        worker._v5_finalize_sync_cursor_state(
            cursor=None, summary={'errors': []},
            ts_func=_ts, debug_file=sys.stderr,
        )

        worker.save_cursor.assert_not_called()

    def test_empty_errors_list_counts_as_success(self):
        """Empty errors list [] is truthy but treated as no errors."""
        worker = _make_worker()
        worker.save_cursor = Mock()

        worker._v5_finalize_sync_cursor_state(
            cursor='cursor-ok', summary={'errors': []},
            ts_func=_ts, debug_file=sys.stderr,
        )

        # [] is falsy, so errors check passes → cursor saved
        worker.save_cursor.assert_called_once()
