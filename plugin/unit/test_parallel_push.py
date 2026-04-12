"""TDD edge case matrix for parallel push upload.

The plugin currently sends batches sequentially. Parallel push splits
the changeset into N disjoint chunks and sends them via ThreadPoolExecutor.

Edge cases:
  pp01: parallel_workers=1 → sequential (no-op, backward compatible)
  pp02: parallel_workers=3 with 9 batches → 3 threads × 3 batches each
  pp03: parallel_workers=3 with 2 batches → only 2 threads used
  pp04: parallel_workers=3 with 0 batches → no work, no threads
  pp05: one thread fails → error reported, others complete successfully
  pp06: all threads fail → all errors collected
  pp07: results from all threads merged in correct order
  pp08: cancel_check called between batches → raises on cancel
  pp09: parallel_workers > batch_count → clamped to batch_count
"""
from __future__ import annotations

import json
import os
import sys
import time
from concurrent.futures import Future
from unittest.mock import MagicMock, patch, call
from types import SimpleNamespace

import pytest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'sync_calimob'))

from calibre_plugins.sync_calimob.parallel_push import ParallelPushExecutor


def _make_batch(n, prefix='b'):
    """Build a list of n fake change dicts."""
    return [{'op': 'upsert', 'item': {'uuid': f'{prefix}-{i}'}, 'idempotency_key': f'k-{prefix}-{i}'} for i in range(n)]


def _make_send_fn(delay=0, fail_on_chunk=None):
    """Return a mock send function that records calls and optionally fails."""
    results_store = []

    def send_batch(batch, client_cursor=None):
        if delay:
            time.sleep(delay)
        batch_id = batch[0]['item']['uuid'] if batch else 'empty'
        if fail_on_chunk is not None and batch_id.startswith(fail_on_chunk):
            raise RuntimeError(f'Simulated failure on {batch_id}')
        result = {
            'results': [{'status': 'applied', 'client_change_id': c['idempotency_key']} for c in batch],
            'new_cursor': f'cursor-{batch_id}',
        }
        results_store.append(result)
        return result

    return send_batch, results_store


class TestParallelPushExecutor:

    def test_pp01_single_worker_sequential(self):
        batches = [_make_batch(5, f'chunk{i}') for i in range(3)]
        send_fn, store = _make_send_fn()
        executor = ParallelPushExecutor(parallel_workers=1)
        results, errors = executor.execute(batches, send_fn)
        assert len(results) == 15  # 3 batches × 5 items
        assert len(errors) == 0
        assert len(store) == 3  # called 3 times

    def test_pp02_three_workers_nine_batches(self):
        batches = [_make_batch(2, f'chunk{i}') for i in range(9)]
        send_fn, store = _make_send_fn()
        executor = ParallelPushExecutor(parallel_workers=3)
        results, errors = executor.execute(batches, send_fn)
        assert len(results) == 18
        assert len(errors) == 0

    def test_pp03_three_workers_two_batches(self):
        batches = [_make_batch(3, f'chunk{i}') for i in range(2)]
        send_fn, store = _make_send_fn()
        executor = ParallelPushExecutor(parallel_workers=3)
        results, errors = executor.execute(batches, send_fn)
        assert len(results) == 6
        assert len(errors) == 0

    def test_pp04_zero_batches(self):
        send_fn, store = _make_send_fn()
        executor = ParallelPushExecutor(parallel_workers=3)
        results, errors = executor.execute([], send_fn)
        assert len(results) == 0
        assert len(errors) == 0
        assert len(store) == 0

    def test_pp05_one_thread_fails_others_succeed(self):
        batches = [_make_batch(2, f'chunk{i}') for i in range(3)]
        send_fn, store = _make_send_fn(fail_on_chunk='chunk1')
        executor = ParallelPushExecutor(parallel_workers=3)
        results, errors = executor.execute(batches, send_fn)
        # chunk0 and chunk2 succeed (4 results), chunk1 fails
        assert len(results) == 4
        assert len(errors) == 1
        assert 'chunk1' in errors[0]

    def test_pp06_all_threads_fail(self):
        batches = [_make_batch(2, f'fail{i}') for i in range(3)]
        send_fn, store = _make_send_fn(fail_on_chunk='fail')
        executor = ParallelPushExecutor(parallel_workers=3)
        results, errors = executor.execute(batches, send_fn)
        assert len(results) == 0
        assert len(errors) == 3

    def test_pp07_results_merged_in_order(self):
        batches = [_make_batch(2, f'chunk{i}') for i in range(4)]
        send_fn, store = _make_send_fn()
        executor = ParallelPushExecutor(parallel_workers=2)
        results, errors = executor.execute(batches, send_fn)
        # Results should be in batch order: chunk0, chunk1, chunk2, chunk3
        ids = [r['client_change_id'] for r in results]
        assert ids == [
            'k-chunk0-0', 'k-chunk0-1',
            'k-chunk1-0', 'k-chunk1-1',
            'k-chunk2-0', 'k-chunk2-1',
            'k-chunk3-0', 'k-chunk3-1',
        ]

    def test_pp08_cancel_check(self):
        batches = [_make_batch(2, f'chunk{i}') for i in range(4)]
        send_fn, store = _make_send_fn()
        call_count = [0]

        def cancel_check():
            call_count[0] += 1
            if call_count[0] >= 3:
                raise InterruptedError('User cancelled')

        executor = ParallelPushExecutor(parallel_workers=1, cancel_check=cancel_check)
        with pytest.raises(InterruptedError):
            executor.execute(batches, send_fn)
        # Should have processed some batches before cancel
        assert len(store) >= 2

    def test_pp09_workers_clamped_to_batch_count(self):
        batches = [_make_batch(3, 'only')]
        send_fn, store = _make_send_fn()
        executor = ParallelPushExecutor(parallel_workers=10)
        results, errors = executor.execute(batches, send_fn)
        assert len(results) == 3
        assert len(errors) == 0
