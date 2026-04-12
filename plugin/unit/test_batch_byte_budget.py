"""TDD edge case matrix for byte-budget batch accumulator.

The plugin currently splits changes into fixed-count batches (default 200).
This module tests a byte-budget accumulator that yields batches when
accumulated payload size exceeds a configurable threshold, adapting
naturally to payload richness.

Edge cases:
  bb01: single small book → one batch
  bb02: many small books under budget → single batch
  bb03: budget exceeded mid-batch → splits at the right point
  bb04: single book exceeds budget → still yields it (never empty batch)
  bb05: exact budget boundary → flush, next book starts new batch
  bb06: empty input → no batches
  bb07: mixed small + large books → uneven batch sizes
  bb08: budget=0 → one book per batch (degenerate case)
  bb09: all books identical size → predictable split points
"""
from __future__ import annotations

import json
import sys
import os
import pytest

# Ensure plugin package is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', '..', 'sync_calimob'))

from calibre_plugins.sync_calimob.batch_utils import BatchByteBudgetAccumulator


def _make_change(index=0, comment='', extra_tags=0):
    """Build a minimal change dict mirroring the real sync payload.

    Uses zero-padded index to keep all titles the same byte length.
    """
    title = f'Book{index:04d}'
    item = {
        'uuid': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        'title': title,
        'authors': [{'name': 'Author'}],
        'tags': [{'name': f'Tag{i:04d}'} for i in range(extra_tags)],
        'comments': comment,
    }
    raw = json.dumps({'op': 'upsert', 'item': item}, sort_keys=True, separators=(',', ':'))
    return {
        'op': 'upsert',
        'item': item,
        'idempotency_key': 'idem-' + title,
        'client_change_id': 'cid-' + title,
        '_estimated_bytes': len(raw.encode('utf-8')),
    }


def _collect_batches(changes, max_bytes):
    acc = BatchByteBudgetAccumulator(max_batch_bytes=max_bytes)
    batches = list(acc.accumulate(changes))
    return batches


class TestBatchByteBudgetAccumulator:

    def test_bb01_single_small_book(self):
        changes = [_make_change(0)]
        batches = _collect_batches(changes, max_bytes=1_000_000)
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_bb02_many_small_books_under_budget(self):
        changes = [_make_change(i) for i in range(50)]
        batches = _collect_batches(changes, max_bytes=1_000_000)
        assert len(batches) == 1
        assert len(batches[0]) == 50

    def test_bb03_budget_exceeded_splits(self):
        changes = [_make_change(i) for i in range(100)]
        single_size = changes[0]['_estimated_bytes']
        budget = single_size * 10 + 1
        batches = _collect_batches(changes, max_bytes=budget)
        assert len(batches) == 10
        for batch in batches:
            assert len(batch) == 10

    def test_bb04_single_book_exceeds_budget(self):
        big_comment = 'x' * 100_000
        changes = [_make_change(0, comment=big_comment)]
        batches = _collect_batches(changes, max_bytes=1024)
        assert len(batches) == 1
        assert len(batches[0]) == 1

    def test_bb05_exact_boundary(self):
        changes = [_make_change(i) for i in range(20)]
        single_size = changes[0]['_estimated_bytes']
        budget = single_size * 10
        batches = _collect_batches(changes, max_bytes=budget)
        assert len(batches) == 2
        assert len(batches[0]) == 10
        assert len(batches[1]) == 10

    def test_bb06_empty_input(self):
        batches = _collect_batches([], max_bytes=1_000_000)
        assert len(batches) == 0

    def test_bb07_mixed_small_and_large(self):
        changes = []
        for i in range(10):
            if i % 3 == 0:
                changes.append(_make_change(i, comment='x' * 5000, extra_tags=20))
            else:
                changes.append(_make_change(i))
        large_size = changes[0]['_estimated_bytes']
        budget = large_size * 2 + 1
        batches = _collect_batches(changes, max_bytes=budget)
        total = sum(len(b) for b in batches)
        assert total == 10
        for batch in batches:
            assert len(batch) >= 1

    def test_bb08_budget_zero_one_per_batch(self):
        changes = [_make_change(i) for i in range(5)]
        batches = _collect_batches(changes, max_bytes=0)
        assert len(batches) == 5
        for batch in batches:
            assert len(batch) == 1

    def test_bb09_all_identical_predictable_splits(self):
        changes = [_make_change(0) for _ in range(100)]
        single_size = changes[0]['_estimated_bytes']
        budget = single_size * 25
        batches = _collect_batches(changes, max_bytes=budget)
        assert len(batches) == 4
        for batch in batches:
            assert len(batch) == 25

    def test_bb10_estimated_bytes_missing_uses_json_len(self):
        """If _estimated_bytes is not pre-computed, accumulator computes it."""
        changes = [_make_change(i) for i in range(10)]
        for c in changes:
            del c['_estimated_bytes']
        batches = _collect_batches(changes, max_bytes=1_000_000)
        assert len(batches) == 1
        assert len(batches[0]) == 10
