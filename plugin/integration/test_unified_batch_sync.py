#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Integration tests for unified batch sync functionality.

Tests:
1. Basic batch sync flow (PULL → PUSH interleaved)
2. Empty batches with has_more=true
3. Progress bar calculation
4. Cancellation handling (start/stop)
5. Error resilience
6. Cursor advancement
"""

from __future__ import (absolute_import, division, print_function, unicode_literals)

import unittest
import time
import sys
import os
from unittest.mock import Mock, MagicMock, patch, call

# Add plugin to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', '..', 'sync_calimob'))

from sync_worker import SyncWorker


class TestUnifiedBatchSync(unittest.TestCase):
    """Test unified batch sync implementation."""
    
    def setUp(self):
        """Set up test fixtures."""
        # Mock Calibre DB
        self.mock_db = Mock()
        self.mock_db.library_path = '/tmp/test_library'
        self.mock_db.all_ids.return_value = list(range(1, 101))  # 100 books
        
        # Mock REST client
        self.mock_client = Mock()
        
        # Create SyncWorker
        self.worker = SyncWorker(
            db=self.mock_db,
            client=self.mock_client,
            library_id='test-library-uuid',
            calimob_library_id='1'
        )
        
        # Mock methods
        self.worker.get_last_cursor = Mock(return_value=None)
        self.worker.save_cursor = Mock()
        self.worker._apply_create = Mock(return_value=1)
        self.worker._apply_update = Mock(return_value=(1, False))
        self.worker._apply_delete = Mock(return_value=1)
        self.worker._download_cover = Mock()
        self.worker.push_sync = Mock(return_value={
            'pushed': 10,
            'covers_uploaded': 5,
            'files_uploaded': 2,
            'errors': []
        })
    
    def test_basic_batch_sync_flow(self):
        """Test basic PULL → PUSH interleaved flow."""
        # Mock server responses
        batch1_response = {
            'changes': [
                {'op': 'update', 'item': {'id': 1, 'uuid': 'uuid-1', 'title': 'Book 1'}},
                {'op': 'create', 'item': {'id': 2, 'uuid': 'uuid-2', 'title': 'Book 2'}},
            ],
            'conflicts': [],
            'new_cursor': 'cursor-batch1',
            'has_more': True,
            'total_books': 100
        }
        
        batch2_response = {
            'changes': [
                {'op': 'update', 'item': {'id': 3, 'uuid': 'uuid-3', 'title': 'Book 3'}},
            ],
            'conflicts': [],
            'new_cursor': 'cursor-batch2',
            'has_more': False,
            'total_books': 100
        }
        
        self.mock_client.post_sync_pull.side_effect = [batch1_response, batch2_response]
        
        # Execute sync
        summary = self.worker.sync_unified_batches(batch_size=50)
        
        # Assertions
        self.assertEqual(summary['batches_completed'], 2)
        self.assertEqual(summary['pull_changes'], 3)
        self.assertEqual(self.mock_client.post_sync_pull.call_count, 2)
        self.assertEqual(self.worker.save_cursor.call_count, 2)
        self.assertEqual(self.worker.push_sync.call_count, 2)
        
        # Verify cursor was saved
        self.worker.save_cursor.assert_called_with('cursor-batch2')
    
    def test_empty_batch_with_has_more(self):
        """Test empty batch with has_more=true advances cursor correctly."""
        # Mock server responses: empty batch followed by data batch
        batch1_response = {
            'changes': [],
            'conflicts': [],
            'new_cursor': 'cursor-empty',
            'has_more': True,
            'total_books': 100
        }
        
        batch2_response = {
            'changes': [
                {'op': 'update', 'item': {'id': 1, 'uuid': 'uuid-1', 'title': 'Book 1'}},
            ],
            'conflicts': [],
            'new_cursor': 'cursor-batch2',
            'has_more': False,
            'total_books': 100
        }
        
        self.mock_client.post_sync_pull.side_effect = [batch1_response, batch2_response]
        
        # Execute sync
        summary = self.worker.sync_unified_batches(batch_size=50)
        
        # Assertions
        self.assertEqual(summary['batches_completed'], 1)  # Only batch 2 counted
        self.assertEqual(summary['pull_changes'], 1)
        self.assertEqual(self.mock_client.post_sync_pull.call_count, 2)
        
        # Verify cursor advanced through empty batch
        self.worker.save_cursor.assert_called_with('cursor-batch2')
    
    def test_progress_calculation(self):
        """Test progress bar calculation (0.5 pull + 0.5 push per book)."""
        # Mock server response
        batch_response = {
            'changes': [
                {'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                for i in range(1, 11)  # 10 books
            ],
            'conflicts': [],
            'new_cursor': 'cursor-final',
            'has_more': False,
            'total_books': 100
        }
        
        self.mock_client.post_sync_pull.return_value = batch_response
        
        # Track progress callbacks
        progress_calls = []
        def progress_callback(msg, current, total):
            progress_calls.append((msg, current, total))
        
        # Execute sync
        self.worker.sync_unified_batches(
            progress_callback=progress_callback,
            batch_size=50
        )
        
        # Assertions
        self.assertGreater(len(progress_calls), 0)
        
        # Check progress values
        # After PULL: 10 × 0.5 = 5 units
        # After PUSH: 10 × 0.5 = 10 units (if all pushed)
        final_progress = progress_calls[-1]
        self.assertEqual(final_progress[2], 100)  # Total estimate
        self.assertGreater(final_progress[1], 0)  # Some progress made
    
    def test_cancellation_during_sync(self):
        """Test cancellation stops sync immediately."""
        # Mock server response with many changes
        batch_response = {
            'changes': [
                {'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                for i in range(1, 201)  # 200 books
            ],
            'conflicts': [],
            'new_cursor': 'cursor-batch1',
            'has_more': True,
            'total_books': 1000
        }
        
        self.mock_client.post_sync_pull.return_value = batch_response
        
        # Cancel after 10 applies
        apply_count = [0]
        def apply_with_cancel(*args, **kwargs):
            apply_count[0] += 1
            if apply_count[0] > 10:
                self.worker._cancelled = True  # Simulate cancel button
            return apply_count[0]
        
        self.worker._apply_update = Mock(side_effect=apply_with_cancel)
        
        # Execute sync (should raise cancellation exception)
        with self.assertRaises(Exception) as ctx:
            self.worker.sync_unified_batches(batch_size=200)
        
        self.assertIn('cancel', str(ctx.exception).lower())
        
        # Verify it stopped early (not all 200 applies)
        self.assertLessEqual(apply_count[0], 20)  # Stopped quickly
    
    def test_error_resilience(self):
        """Test sync continues after non-critical errors."""
        # Mock server responses
        batch1_response = {
            'changes': [
                {'op': 'update', 'item': {'id': 1, 'uuid': 'uuid-1', 'title': 'Book 1'}},
                {'op': 'update', 'item': {'id': 2, 'uuid': 'uuid-2', 'title': 'Book 2'}},
            ],
            'conflicts': [],
            'new_cursor': 'cursor-batch1',
            'has_more': True,
            'total_books': 100
        }
        
        batch2_response = {
            'changes': [
                {'op': 'update', 'item': {'id': 3, 'uuid': 'uuid-3', 'title': 'Book 3'}},
            ],
            'conflicts': [],
            'new_cursor': 'cursor-batch2',
            'has_more': False,
            'total_books': 100
        }
        
        self.mock_client.post_sync_pull.side_effect = [batch1_response, batch2_response]
        
        # First apply fails, others succeed
        self.worker._apply_update.side_effect = [
            Exception('Network timeout'),  # Batch 1, book 1: FAIL
            (2, False),                     # Batch 1, book 2: OK
            (3, False),                     # Batch 2, book 3: OK
        ]
        
        # Execute sync
        summary = self.worker.sync_unified_batches(batch_size=50)
        
        # Assertions
        self.assertEqual(summary['batches_completed'], 2)  # Both batches completed
        self.assertEqual(len(summary['errors']), 1)  # One error logged
        self.assertIn('Network timeout', summary['errors'][0]['error'])
    
    def test_conflicts_detection(self):
        """Test conflicts are detected and logged."""
        # Mock server response with conflicts
        batch_response = {
            'changes': [
                {'op': 'update', 'item': {'id': 1, 'uuid': 'uuid-1', 'title': 'Book 1'}},
            ],
            'conflicts': [
                {
                    'id': 123,
                    'reason': 'uuid_collision',
                    'client_uuid': 'uuid-conflict',
                }
            ],
            'new_cursor': 'cursor-final',
            'has_more': False,
            'total_books': 100
        }
        
        self.mock_client.post_sync_pull.return_value = batch_response
        
        # Execute sync
        with patch('sync_logger.log') as mock_log:
            summary = self.worker.sync_unified_batches(batch_size=50)
            
            # Verify conflicts were logged
            conflict_logs = [call for call in mock_log.call_args_list 
                           if 'CONFLICTS_DETECTED' in str(call)]
            self.assertGreater(len(conflict_logs), 0)
    
    def test_cursor_persistence(self):
        """Test cursor is saved after each successful batch."""
        # Mock server responses
        batches = [
            {
                'changes': [{'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}],
                'conflicts': [],
                'new_cursor': f'cursor-batch{i}',
                'has_more': i < 3,
                'total_books': 100
            }
            for i in range(1, 4)
        ]
        
        self.mock_client.post_sync_pull.side_effect = batches
        
        # Execute sync
        summary = self.worker.sync_unified_batches(batch_size=50)
        
        # Assertions
        self.assertEqual(summary['batches_completed'], 3)
        
        # Verify cursor saved after each batch
        cursor_calls = [call[0][0] for call in self.worker.save_cursor.call_args_list]
        self.assertEqual(cursor_calls, ['cursor-batch1', 'cursor-batch2', 'cursor-batch3'])
    
    def test_total_errors_in_summary(self):
        """Test total_errors is populated for UI error detection."""
        # Mock server response
        batch_response = {
            'changes': [
                {'op': 'update', 'item': {'id': 1, 'uuid': 'uuid-1', 'title': 'Book 1'}},
            ],
            'conflicts': [],
            'new_cursor': 'cursor-final',
            'has_more': False,
            'total_books': 100
        }
        
        self.mock_client.post_sync_pull.return_value = batch_response
        
        # Apply fails
        self.worker._apply_update.side_effect = Exception('Test error')
        
        # Execute sync
        summary = self.worker.sync_unified_batches(batch_size=50)
        
        # Assertions
        self.assertIn('total_errors', summary)
        self.assertIsInstance(summary['total_errors'], list)
        self.assertEqual(len(summary['total_errors']), 1)


class TestCancellationCheckpoints(unittest.TestCase):
    """Test cancellation checkpoints are called at right times."""
    
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
        
        self.worker.get_last_cursor = Mock(return_value=None)
        self.worker.save_cursor = Mock()
        self.worker._download_cover = Mock()
        self.worker.push_sync = Mock(return_value={'pushed': 0, 'errors': []})
    
    def test_checkpoint_at_batch_start(self):
        """Test cancellation is checked at start of each batch."""
        # Set cancelled before first batch
        self.worker._cancelled = True
        
        batch_response = {
            'changes': [],
            'conflicts': [],
            'new_cursor': 'cursor',
            'has_more': False,
            'total_books': 100
        }
        
        self.mock_client.post_sync_pull.return_value = batch_response
        
        # Execute sync (should raise immediately)
        with self.assertRaises(Exception) as ctx:
            self.worker.sync_unified_batches(batch_size=50)
        
        self.assertIn('cancel', str(ctx.exception).lower())
        
        # Verify no server calls were made (cancelled before API call)
        self.assertEqual(self.mock_client.post_sync_pull.call_count, 0)
    
    def test_checkpoint_during_apply_loop(self):
        """Test cancellation during apply changes loop."""
        batch_response = {
            'changes': [
                {'op': 'update', 'item': {'id': i, 'uuid': f'uuid-{i}', 'title': f'Book {i}'}}
                for i in range(1, 11)  # 10 books
            ],
            'conflicts': [],
            'new_cursor': 'cursor',
            'has_more': False,
            'total_books': 100
        }
        
        self.mock_client.post_sync_pull.return_value = batch_response
        
        # Cancel after 5 applies
        apply_count = [0]
        def apply_with_cancel(*args, **kwargs):
            apply_count[0] += 1
            if apply_count[0] == 5:
                self.worker._cancelled = True
            return (apply_count[0], False)
        
        self.worker._apply_update = Mock(side_effect=apply_with_cancel)
        
        # Execute sync (should raise after 5 applies)
        with self.assertRaises(Exception) as ctx:
            self.worker.sync_unified_batches(batch_size=50)
        
        self.assertIn('cancel', str(ctx.exception).lower())
        self.assertEqual(apply_count[0], 5)  # Stopped at checkpoint
    
    def test_checkpoint_during_cover_download(self):
        """Test cancellation during cover download loop."""
        batch_response = {
            'changes': [
                {
                    'op': 'update',
                    'item': {
                        'id': i,
                        'uuid': f'uuid-{i}',
                        'title': f'Book {i}',
                        'cover': {'has_cover': True}
                    }
                }
                for i in range(1, 11)  # 10 books with covers
            ],
            'conflicts': [],
            'new_cursor': 'cursor',
            'has_more': False,
            'total_books': 100
        }
        
        self.mock_client.post_sync_pull.return_value = batch_response
        self.worker._apply_update = Mock(return_value=(1, False))
        
        # Cancel after 3 cover downloads
        download_count = [0]
        def download_with_cancel(*args, **kwargs):
            download_count[0] += 1
            if download_count[0] == 3:
                self.worker._cancelled = True
        
        self.worker._download_cover = Mock(side_effect=download_with_cancel)
        
        # Execute sync (should raise after 3 downloads)
        with self.assertRaises(Exception) as ctx:
            self.worker.sync_unified_batches(batch_size=50)
        
        self.assertIn('cancel', str(ctx.exception).lower())
        self.assertEqual(download_count[0], 3)  # Stopped at checkpoint


if __name__ == '__main__':
    unittest.main()
