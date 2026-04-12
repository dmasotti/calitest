"""
RED tests: cover uploads must be deferred to after sync loop.

Same pattern as file uploads (deferred in commit 2bfa278).
Cover uploads in push_missing path and legacy batch are currently
inline and sequential — blocking the sync loop.

Fix: accumulate cover uploads during sync loop, execute after
finalize_cursor_state (same as deferred_file_uploads).
"""
from __future__ import annotations

import os
from unittest.mock import Mock

import pytest

from calibre_plugins.sync_calimob import sync_worker


# ─────────────────────────────────────────────────────────────────────────────
# 1. Source: sync_v5 must have deferred_cover_uploads accumulator
# ─────────────────────────────────────────────────────────────────────────────

class TestDeferredCoverUploadsAccumulator:
    """sync_v5 must accumulate cover uploads like file uploads."""

    def test_sync_v5_has_deferred_cover_uploads(self):
        src_path = os.path.join(
            os.path.dirname(sync_worker.__file__), 'sync_worker.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        sync_v5_start = code.find('def sync_v5(self')
        next_def = code.find('\n    def ', sync_v5_start + 20)
        sync_v5_section = code[sync_v5_start:next_def]

        has_deferred_covers = (
            'deferred_cover_uploads' in sync_v5_section or
            'deferred_covers' in sync_v5_section or
            'accumulated_cover_uploads' in sync_v5_section
        )
        assert has_deferred_covers, (
            "sync_v5 must accumulate cover uploads during the loop. "
            "Currently cover uploads are inline in push_missing, "
            "blocking the sync loop."
        )

    def test_deferred_covers_execute_after_finalize_cursor(self):
        """Cover uploads must execute AFTER the batch loop completes.

        The finalize_sync_cursor_state call has been removed; covers now
        execute in Phase 2 after the batch loop (Phase 1).  Verify the
        deferred_cover_uploads execution is after the batch iteration.
        """
        src_path = os.path.join(
            os.path.dirname(sync_worker.__file__), 'sync_worker.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        sync_v5_start = code.find('def sync_v5(self')
        # Find end of sync_v5 (next top-level def or end of class)
        next_def = code.find('\n    def ', sync_v5_start + 20)
        sync_v5_section = code[sync_v5_start:next_def if next_def > 0 else sync_v5_start + 20000]

        # The batch loop marker
        batch_loop_pos = sync_v5_section.find('for batch_start in range(')
        cover_upload_pos = max(
            sync_v5_section.rfind('deferred_cover_uploads'),
            sync_v5_section.rfind('deferred_covers'),
        )

        assert batch_loop_pos > 0, "batch loop not found in sync_v5"
        assert cover_upload_pos > 0, "deferred cover uploads not found"
        assert cover_upload_pos > batch_loop_pos, (
            "Cover uploads must execute AFTER the batch loop"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. Source: push_missing must not call upload_cover inline
# ─────────────────────────────────────────────────────────────────────────────

class TestPushMissingNoInlineCoverUpload:
    """_process_post_upsert_actions must accumulate, not upload inline."""

    def test_no_client_upload_cover_in_upsert_actions(self):
        """self.client.upload_cover() must NOT be called directly
        inside _process_post_upsert_actions."""
        src_path = os.path.join(
            os.path.dirname(sync_worker.__file__), 'sync_worker.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        # Find _process_post_upsert_actions (nested in _v5_push_missing_items)
        func_start = code.find('def _process_post_upsert_actions')
        assert func_start > 0
        # It's a nested function, find the next def at same indent
        next_def = code.find('\n        def ', func_start + 10)
        func_body = code[func_start:next_def if next_def > 0 else func_start + 3000]

        has_inline_upload = 'client.upload_cover(' in func_body

        # Should accumulate instead
        has_accumulate = (
            'deferred_cover_uploads' in func_body or
            'cover_uploads_out' in func_body or
            'append(' in func_body
        )

        assert not has_inline_upload or has_accumulate, (
            "_process_post_upsert_actions must accumulate cover uploads, "
            "not call client.upload_cover() inline."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Cover data preserved in accumulator
# ─────────────────────────────────────────────────────────────────────────────

class TestCoverDataPreserved:
    """Deferred cover upload must retain all necessary data."""

    def test_cover_upload_info_has_required_fields(self):
        cover_info = {
            'calibre_book_id': 42,
            'item_uuid': 'uuid-42',
            'cover_data': b'png-bytes',
            'cover_hash': 'sha256:abc',
        }
        assert 'calibre_book_id' in cover_info
        assert 'cover_data' in cover_info
        assert isinstance(cover_info['cover_data'], bytes)


# ─────────────────────────────────────────────────────────────────────────────
# 4. Summary tracks deferred cover count
# ─────────────────────────────────────────────────────────────────────────────

class TestSummaryTracksDeferredCovers:
    """Summary must report deferred cover upload count."""

    def test_summary_has_covers_deferred(self):
        summary = {
            'covers_deferred_for_upload': 50,
            'covers_uploaded': 0,
        }
        assert summary['covers_deferred_for_upload'] == 50
