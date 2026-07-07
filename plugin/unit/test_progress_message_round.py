"""The 'Preparing book' progress message used to show a stuck "batch 1"
(it read summary['batches_completed'], set only at end-of-sync, so always 0+1).
Now _v5_push_missing_items receives the real chunk batch_num and the message is
reworded for end users. This pins the format + that batch_num is reflected."""
from __future__ import annotations

from calibre_plugins.sync_calimob.progress_messages import (
    format_v5_upload_missing_message,
)


def test_message_reflects_the_real_round_and_is_user_friendly():
    msg = format_v5_upload_missing_message(
        batch_num=3, item_idx=5, total_items=336,
        item={'uuid': 'abc-123'})
    # The round advances (3), not a stuck "batch 1".
    assert msg == 'Preparing book 5/336 (round 3)'
    # No technical noise that disoriented end users.
    assert 'book_uuid' not in msg
    assert 'abc-123' not in msg


def test_round_advances_across_chunks():
    rounds = [
        format_v5_upload_missing_message(batch_num=n, item_idx=1, total_items=10,
                                         item={'uuid': 'x'})
        for n in (1, 2, 3)
    ]
    assert rounds == [
        'Preparing book 1/10 (round 1)',
        'Preparing book 1/10 (round 2)',
        'Preparing book 1/10 (round 3)',
    ]
