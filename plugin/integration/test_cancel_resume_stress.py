#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Stress tests for unified batch sync - cancellation and resume.

Tests realistic scenarios:
1. Cancel sync after N batches → resume should continue from cursor
2. Cancel during apply loop → no data corruption
3. Multiple cancel/resume cycles
4. Progress bar consistency after resume
"""

from __future__ import (absolute_import, division, print_function, unicode_literals)

import unittest
import time
import threading
from unittest.mock import Mock, MagicMock, patch

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sync_calimob'))

from sync_worker import SyncWorker


class TestCancelResume(unittest.TestCase):
    """Test cancel and resume functionality."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_db = Mock()
        self.mock_db.library_path = '/tmp/test_library'
        self.mock_client = Mock()
        
        self.worker = SyncWorker(
            db=self.mock_db,
            client=self.mock_client,
            library_id='test-library-uuid',
            calimob_library_id='1'
        )
        
        self.saved_cursors = []
        
        def save_cursor_mock(cursor):
            self.saved_cursors.append(cursor)
        
        self.worker.save_cursor = Mock(side_effect=save_cursor_mock)
        self.worker._download_cover = Mock()
        self.worker.push_sync = Mock(return_value={'pushed': 0, 'errors': []})
    
    def test_cancel_after_first_batch(self):
        """Test cancel after first batch saves cursor correctly."""
        # Mock server responses (5 batches total)
        batches = []
        for i in range(1, 6):
            batches.append({
                'changes': [
                    {'op': 'update', 'item': {'id': j, 'uuid': f'uuid-{i}-{j}', 'title': f'Book {i}-{j}'}}
                    for j in range(1, 11)  # 10 books per batch
                ],
                'conflicts': [],
                'new_cursor': f'cursor-batch{i}',
                'has_more': i < 5,
                'total_books': 50
            })
        
        self.mock_client.post_sync_pull.side_effect = batches
        self.worker._apply_update = Mock(return_value=(1, False))
        
        # Cancel after first batch completes
        batch_count = [0]
        original_save = self.worker.save_cursor
        
        def save_and_maybe_cancel(cursor):
            original_save(cursor)
            batch_count[0] += 1
            if batch_count[0] == 1:
                self.worker._cancelled = True  # Cancel after first batch saved
        
        self.worker.save_cursor = Mock(side_effect=save_and_maybe_cancel)
        
        # Execute sync (should cancel after batch 1)
        with self.assertRaises(Exception) as ctx:
            self.worker.sync_unified_batches(batch_size=50)
        
        self.assertIn('cancel', str(ctx.exception).lower())
        
        # Verify cursor was saved for batch 1
        self.assertEqual(len(self.saved_cursors), 1)
        self.assertEqual(self.saved_cursors[0], 'cursor-batch1')
        
        # Verify only 1 batch was processed
        self.assertEqual(self.mock_client.post_sync_pull.call_count, 2)  # Batch 1 + start of batch 2
    
    def test_resume_from_saved_cursor(self):
        """Test resume continues from saved cursor after cancel."""
        # FIRST RUN: Process batches 1-2, cancel
        batches_run1 = [
            {
                'changes': [{'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                           for i in range(1, 11)],
                'conflicts': [],
                'new_cursor': 'cursor-batch1',
                'has_more': True,
                'total_books': 50
            },
            {
                'changes': [{'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                           for i in range(11, 21)],
                'conflicts': [],
                'new_cursor': 'cursor-batch2',
                'has_more': True,
                'total_books': 50
            }
        ]
        
        self.mock_client.post_sync_pull.side_effect = batches_run1
        self.worker._apply_update = Mock(return_value=(1, False))
        
        # Cancel after batch 2
        batch_count = [0]
        def save_and_cancel(cursor):
            self.saved_cursors.append(cursor)
            batch_count[0] += 1
            if batch_count[0] == 2:
                self.worker._cancelled = True
        
        self.worker.save_cursor = Mock(side_effect=save_and_cancel)
        
        try:
            self.worker.sync_unified_batches(batch_size=50)
        except Exception:
            pass  # Expected cancellation
        
        # Verify 2 batches processed
        self.assertEqual(len(self.saved_cursors), 2)
        last_cursor = self.saved_cursors[-1]
        self.assertEqual(last_cursor, 'cursor-batch2')
        
        # SECOND RUN: Resume from cursor-batch2
        self.worker._cancelled = False  # Reset cancellation
        self.worker.get_last_cursor = Mock(return_value='cursor-batch2')
        
        batches_run2 = [
            {
                'changes': [{'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                           for i in range(21, 31)],
                'conflicts': [],
                'new_cursor': 'cursor-batch3',
                'has_more': False,
                'total_books': 50
            }
        ]
        
        self.mock_client.post_sync_pull.side_effect = batches_run2
        
        # Execute resume
        summary = self.worker.sync_unified_batches(batch_size=50)
        
        # Verify resumed from correct cursor
        first_call = self.mock_client.post_sync_pull.call_args_list[-1]
        self.assertEqual(first_call[1]['cursor'], 'cursor-batch2')
        
        # Verify batch 3 completed
        self.assertEqual(summary['batches_completed'], 1)
    
    def test_cancel_during_long_apply(self):
        """Test cancel during long apply operation (realistic scenario)."""
        batch_response = {
            'changes': [
                {'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                for i in range(1, 201)  # 200 books (realistic batch)
            ],
            'conflicts': [],
            'new_cursor': 'cursor-partial',
            'has_more': True,
            'total_books': 10000
        }
        
        self.mock_client.post_sync_pull.return_value = batch_response
        
        # Simulate slow apply (e.g., large metadata)
        apply_count = [0]
        def slow_apply(*args, **kwargs):
            apply_count[0] += 1
            time.sleep(0.01)  # 10ms per book (realistic for complex metadata)
            if apply_count[0] == 50:  # Cancel after 50 applies
                self.worker._cancelled = True
            return (apply_count[0], False)
        
        self.worker._apply_update = Mock(side_effect=slow_apply)
        
        start_time = time.time()
        
        # Execute sync (should cancel quickly)
        with self.assertRaises(Exception) as ctx:
            self.worker.sync_unified_batches(batch_size=200)
        
        elapsed = time.time() - start_time
        
        self.assertIn('cancel', str(ctx.exception).lower())
        
        # Verify cancelled quickly (not all 200 applies)
        self.assertLessEqual(apply_count[0], 60)  # Some buffer for checkpoint check
        
        # Verify didn't take too long (should be < 1 second)
        self.assertLess(elapsed, 1.0)  # Fast cancellation
    
    def test_no_data_corruption_on_cancel(self):
        """Test no partial data corruption when cancelled."""
        batch_response = {
            'changes': [
                {'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                for i in range(1, 51)
            ],
            'conflicts': [],
            'new_cursor': 'cursor-partial',
            'has_more': True,
            'total_books': 1000
        }
        
        self.mock_client.post_sync_pull.return_value = batch_response
        
        # Track which books were fully applied
        applied_books = []
        def track_apply(item, **kwargs):
            book_id = item['id']
            applied_books.append(book_id)
            if len(applied_books) == 25:  # Cancel halfway
                self.worker._cancelled = True
            return (book_id, False)
        
        self.worker._apply_update = Mock(side_effect=track_apply)
        
        # Execute sync (cancel mid-batch)
        try:
            self.worker.sync_unified_batches(batch_size=50)
        except Exception:
            pass  # Expected cancellation
        
        # Verify cursor NOT saved (batch incomplete)
        self.assertEqual(len(self.saved_cursors), 0)  # No cursor saved on cancel
        
        # Verify partial applies recorded (for rollback/retry)
        self.assertEqual(len(applied_books), 25)


class TestProgressBarConsistency(unittest.TestCase):
    """Test progress bar remains consistent across cancel/resume."""
    
    def setUp(self):
        """Set up test fixtures."""
        self.mock_db = Mock()
        self.mock_db.library_path = '/tmp/test_library'
        self.mock_client = Mock()
        
        self.worker = SyncWorker(
            db=self.mock_db,
            client=self.mock_client,
            library_id='test-library-uuid',
            calimob_library_id='1'
        )
        
        self.worker.save_cursor = Mock()
        self.worker._download_cover = Mock()
        self.worker.push_sync = Mock(return_value={'pushed': 10, 'errors': []})
        self.worker._apply_update = Mock(return_value=(1, False))
    
    def test_progress_resumes_correctly(self):
        """Test progress calculation resumes from correct point."""
        # First run: 2 batches (100 books each)
        batches_run1 = [
            {
                'changes': [{'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                           for i in range(1, 101)],
                'conflicts': [],
                'new_cursor': 'cursor-batch1',
                'has_more': True,
                'total_books': 1000
            },
            {
                'changes': [{'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                           for i in range(101, 201)],
                'conflicts': [],
                'new_cursor': 'cursor-batch2',
                'has_more': True,
                'total_books': 1000
            }
        ]
        
        self.mock_client.post_sync_pull.side_effect = batches_run1
        
        progress_calls_run1 = []
        def track_progress1(msg, current, total):
            progress_calls_run1.append((msg, current, total))
            if 'Batch 2' in msg and 'completed' in msg:
                self.worker._cancelled = True  # Cancel after batch 2
        
        try:
            self.worker.sync_unified_batches(
                progress_callback=track_progress1,
                batch_size=100
            )
        except Exception:
            pass
        
        # Verify progress reached ~200 units (100 books × 2 batches × 1.0 unit)
        last_progress = progress_calls_run1[-1]
        self.assertGreaterEqual(last_progress[1], 100)  # At least 100 units
        self.assertEqual(last_progress[2], 1000)  # Total estimate
        
        # Second run: Resume (should start fresh, not accumulate)
        self.worker._cancelled = False
        self.worker.get_last_cursor = Mock(return_value='cursor-batch2')
        
        batches_run2 = [
            {
                'changes': [{'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                           for i in range(201, 301)],
                'conflicts': [],
                'new_cursor': 'cursor-batch3',
                'has_more': False,
                'total_books': 1000
            }
        ]
        
        self.mock_client.post_sync_pull.side_effect = batches_run2
        
        progress_calls_run2 = []
        def track_progress2(msg, current, total):
            progress_calls_run2.append((msg, current, total))
        
        self.worker.sync_unified_batches(
            progress_callback=track_progress2,
            batch_size=100
        )
        
        # Verify progress started fresh (not accumulated from run1)
        first_progress = progress_calls_run2[0]
        self.assertLess(first_progress[1], 200)  # Didn't carry over run1 progress


if __name__ == '__main__':
    # Run with verbose output
    unittest.main(verbosity=2)
