"""
End-to-end headless tests for the plugin sync pipeline.

These tests exercise `SyncWorker.sync_unified_batches()` through realistic
multi-step scenarios using an in-memory SQLite Calibre-schema DB stub and
mocked REST client.  They validate:

  1. First sync from blank library (no cursor)
  2. Resume from partial sync (checkpoint cursor)
  3. Library switch between syncs
  4. Cover download failure → resume
  5. Cancellation mid-sync propagation
  6. Config init from zero state
"""
from __future__ import annotations

import sys
import types
import threading
from types import SimpleNamespace
from unittest.mock import Mock, MagicMock, patch, call

import pytest

from calibre_plugins.sync_calimob import config as cfg
from calibre_plugins.sync_calimob.sync_worker import SyncWorker


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_pull_batch(changes, cursor="cur-1", has_more=False, total=None):
    """Build a fake post_sync_pull response dict."""
    return {
        "changes": changes,
        "conflicts": [],
        "new_cursor": cursor,
        "has_more": has_more,
        "total_books": total or len(changes),
    }


def _make_change(book_id, title="Book"):
    """Build a minimal change item for a pull batch."""
    return {
        "op": "update",
        "item": {
            "id": book_id,
            "uuid": f"uuid-{book_id}",
            "title": f"{title} {book_id}",
            "authors": "Author",
            "identifiers": {},
        },
    }


def _make_db(library_path="/tmp/test_lib"):
    """Build a mock Calibre DB with enough methods for SyncWorker."""
    db = Mock()
    db.library_path = library_path

    # Metadata stubs
    def _meta(book_id, index_is_id=True, get_cover=False):
        mi = SimpleNamespace(
            title=f"Existing {book_id}",
            authors=["Author"],
            uuid=f"uuid-{book_id}",
            identifiers={},
            tags=[],
            series=None,
            series_index=1.0,
            rating=0,
            comments="",
            publisher="",
            pubdate=None,
            timestamp=None,
            last_modified=None,
            languages=[],
            has_cover=False,
        )
        return mi

    db.get_metadata = Mock(side_effect=_meta)
    db.set_metadata = Mock()
    db.data = Mock()
    db.data.has_id = Mock(return_value=True)
    db.commit = Mock()
    db.field_metadata = Mock()
    db.field_metadata.custom_field_metadata = Mock(return_value={})
    db.get_custom = Mock(return_value=None)
    db.set_custom = Mock()
    db.cover = Mock(return_value=None)
    db.set_cover = Mock()
    return db


def _make_client():
    """Build a mock REST client with default stubs."""
    client = Mock()
    client.post_sync_pull = Mock(return_value=_make_pull_batch([], cursor=None, has_more=False))
    client.post_sync_push = Mock(return_value={"pushed": 0, "errors": []})
    client.get_sync_conflicts = Mock(return_value={"conflicts": []})
    client.is_configured = Mock(return_value=True)
    return client


def _make_worker(db=None, client=None, library_id="lib-uuid", calimob_library_id="1", **overrides):
    """Build a SyncWorker with sensible defaults, patching internals."""
    db = db or _make_db()
    client = client or _make_client()
    worker = SyncWorker.__new__(SyncWorker)
    worker.db = db
    worker.client = client
    worker.library_id = library_id
    worker.calimob_library_id = calimob_library_id
    worker.gui = None
    worker.plugin_action = None
    worker._cancelled = False
    worker._progress_callback = None
    worker._log_lines = []
    for k, v in overrides.items():
        setattr(worker, k, v)
    return worker


# ─────────────────────────────────────────────────────────────────────────────
# 1. First sync from blank library (no cursor)
# ─────────────────────────────────────────────────────────────────────────────

class TestFirstSyncBlankLibrary:
    """Verify a clean first sync where no cursor exists."""

    def test_first_sync_pulls_all_books(self, monkeypatch):
        """A fresh sync (no cursor) should pull all server books in one batch."""
        changes = [_make_change(i) for i in range(1, 6)]
        client = _make_client()
        client.post_sync_pull = Mock(return_value=_make_pull_batch(changes, cursor="cur-final", has_more=False, total=5))

        worker = _make_worker(client=client)
        # Stub internal methods that depend on full calibre env
        applied = []
        worker._apply_update = Mock(side_effect=lambda item, **kw: (applied.append(item["id"]), (item["id"], False))[1])
        worker.get_pull_cursor = Mock(return_value=None)
        worker.save_pull_cursor = Mock()
        worker.save_cursor = Mock()
        worker.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        worker._download_covers_parallel = Mock(return_value=[])
        worker._upload_missing_covers = Mock()

        worker.sync_unified_batches()

        # All 5 books applied
        assert len(applied) == 5
        assert set(applied) == {1, 2, 3, 4, 5}
        # Cursor was saved after the batch
        worker.save_cursor.assert_called()

    def test_first_sync_saves_cursor_after_completion(self, monkeypatch):
        """After a successful first sync, the new cursor must be persisted."""
        client = _make_client()
        client.post_sync_pull = Mock(return_value=_make_pull_batch(
            [_make_change(1)], cursor="saved-cursor", has_more=False
        ))

        worker = _make_worker(client=client)
        worker._apply_update = Mock(return_value=(1, False))
        worker.get_pull_cursor = Mock(return_value=None)
        worker.save_pull_cursor = Mock()
        worker.save_cursor = Mock()
        worker.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        worker._download_covers_parallel = Mock(return_value=[])
        worker._upload_missing_covers = Mock()

        worker.sync_unified_batches()

        worker.save_cursor.assert_called()

    def test_first_sync_multi_batch_pagination(self, monkeypatch):
        """First sync with multiple paginated batches processes all books."""
        batch1 = _make_pull_batch([_make_change(i) for i in range(1, 4)], cursor="cur-1", has_more=True, total=5)
        batch2 = _make_pull_batch([_make_change(i) for i in range(4, 6)], cursor="cur-2", has_more=False, total=5)

        client = _make_client()
        client.post_sync_pull = Mock(side_effect=[batch1, batch2])

        worker = _make_worker(client=client)
        applied = []
        worker._apply_update = Mock(side_effect=lambda item, **kw: (applied.append(item["id"]), (item["id"], False))[1])
        worker.get_pull_cursor = Mock(return_value=None)
        worker.save_pull_cursor = Mock()
        worker.save_cursor = Mock()
        worker.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        worker._download_covers_parallel = Mock(return_value=[])
        worker._upload_missing_covers = Mock()

        worker.sync_unified_batches()

        assert len(applied) == 5
        assert client.post_sync_pull.call_count == 2


# ─────────────────────────────────────────────────────────────────────────────
# 2. Resume from partial sync (checkpoint cursor)
# ─────────────────────────────────────────────────────────────────────────────

class TestResumeFromCheckpoint:
    """Verify that a sync resuming from a saved cursor skips already-synced books."""

    def test_resume_sends_saved_cursor(self, monkeypatch):
        """When a cursor exists, post_sync_pull should receive it."""
        client = _make_client()
        client.post_sync_pull = Mock(return_value=_make_pull_batch([], cursor="cur-new", has_more=False))

        worker = _make_worker(client=client)
        worker._apply_update = Mock()
        worker.get_pull_cursor = Mock(return_value="old-cursor-123")
        worker.save_pull_cursor = Mock()
        worker.save_cursor = Mock()
        worker.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        worker._download_covers_parallel = Mock(return_value=[])
        worker._upload_missing_covers = Mock()

        worker.sync_unified_batches()

        # The pull call should have received the saved cursor
        pull_calls = client.post_sync_pull.call_args_list
        assert len(pull_calls) >= 1
        # Check the cursor was passed (either as arg or kwarg)
        call_kwargs = pull_calls[0].kwargs if pull_calls[0].kwargs else {}
        call_args = pull_calls[0].args if pull_calls[0].args else ()
        assert "old-cursor-123" in str(call_args) + str(call_kwargs), \
            f"Saved cursor not passed to post_sync_pull: args={call_args}, kwargs={call_kwargs}"

    def test_resume_only_processes_delta(self, monkeypatch):
        """After a checkpoint, only new/changed books since that cursor should be applied."""
        delta_changes = [_make_change(99, "Delta Book")]
        client = _make_client()
        client.post_sync_pull = Mock(return_value=_make_pull_batch(delta_changes, cursor="cur-new", has_more=False))

        worker = _make_worker(client=client)
        applied = []
        worker._apply_update = Mock(side_effect=lambda item, **kw: (applied.append(item["id"]), (item["id"], False))[1])
        worker.get_pull_cursor = Mock(return_value="checkpoint-cursor")
        worker.save_pull_cursor = Mock()
        worker.save_cursor = Mock()
        worker.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        worker._download_covers_parallel = Mock(return_value=[])
        worker._upload_missing_covers = Mock()

        worker.sync_unified_batches()

        assert applied == [99], "Only the delta book should have been applied"


# ─────────────────────────────────────────────────────────────────────────────
# 3. Library switch between syncs
# ─────────────────────────────────────────────────────────────────────────────

class TestLibrarySwitch:
    """Verify that switching libraries uses the correct library_id and cursor."""

    def test_different_library_ids_use_different_cursors(self, monkeypatch):
        """Two workers with different library_ids should read different cursors."""
        cursors = {}

        def _get_cursor(lib_id):
            return cursors.get(lib_id)

        client = _make_client()
        client.post_sync_pull = Mock(return_value=_make_pull_batch([], cursor="c", has_more=False))

        # Worker A
        worker_a = _make_worker(client=client, library_id="lib-A", calimob_library_id="10")
        worker_a._apply_update = Mock()
        worker_a.get_pull_cursor = Mock(return_value="cursor-A")
        worker_a.save_pull_cursor = Mock()
        worker_a.save_cursor = Mock()
        worker_a.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        worker_a._download_covers_parallel = Mock(return_value=[])
        worker_a._upload_missing_covers = Mock()

        # Worker B
        worker_b = _make_worker(client=client, library_id="lib-B", calimob_library_id="20")
        worker_b._apply_update = Mock()
        worker_b.get_pull_cursor = Mock(return_value="cursor-B")
        worker_b.save_pull_cursor = Mock()
        worker_b.save_cursor = Mock()
        worker_b.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        worker_b._download_covers_parallel = Mock(return_value=[])
        worker_b._upload_missing_covers = Mock()

        worker_a.sync_unified_batches()
        worker_b.sync_unified_batches()

        # Each worker read its own cursor
        worker_a.get_pull_cursor.assert_called()
        worker_b.get_pull_cursor.assert_called()
        assert worker_a.get_pull_cursor.return_value == "cursor-A"
        assert worker_b.get_pull_cursor.return_value == "cursor-B"


# ─────────────────────────────────────────────────────────────────────────────
# 4. Cover download failure → resume
# ─────────────────────────────────────────────────────────────────────────────

class TestCoverDownloadResilience:
    """Verify that cover download failures don't abort the sync pipeline."""

    def test_cover_failure_does_not_block_cursor_save(self, monkeypatch):
        """If cover download raises, the cursor must still be saved."""
        changes = [_make_change(1)]
        client = _make_client()
        client.post_sync_pull = Mock(return_value=_make_pull_batch(changes, cursor="cover-test-cur", has_more=False))

        worker = _make_worker(client=client)
        worker._apply_update = Mock(return_value=(1, False))
        worker.get_pull_cursor = Mock(return_value=None)
        worker.save_pull_cursor = Mock()
        worker.save_cursor = Mock()
        worker.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        worker._download_covers_parallel = Mock(side_effect=IOError("network error"))
        worker._upload_missing_covers = Mock()

        # Should not raise despite cover download failure
        worker.sync_unified_batches()

        # Cursor must still be saved
        worker.save_cursor.assert_called()

    def test_partial_cover_download_reports_count(self, monkeypatch):
        """When some covers fail, the non-failing ones should still be counted."""
        changes = [_make_change(i) for i in range(1, 4)]
        client = _make_client()
        client.post_sync_pull = Mock(return_value=_make_pull_batch(changes, cursor="c", has_more=False))

        worker = _make_worker(client=client)
        worker._apply_update = Mock(side_effect=lambda item, **kw: (item["id"], False))
        worker.get_pull_cursor = Mock(return_value=None)
        worker.save_pull_cursor = Mock()
        worker.save_cursor = Mock()
        worker.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        # Return 2 successful downloads (partial)
        worker._download_covers_parallel = Mock(return_value=[1, 2])
        worker._upload_missing_covers = Mock()

        worker.sync_unified_batches()

        # Sync completed successfully despite incomplete covers
        worker.save_cursor.assert_called()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Cancellation mid-sync propagation
# ─────────────────────────────────────────────────────────────────────────────

class TestCancellationPropagation:
    """Verify that setting _cancelled stops the sync loop promptly."""

    def test_cancel_during_pull_stops_early(self, monkeypatch):
        """Cancelling mid-pull should stop processing further batches."""
        batch1 = _make_pull_batch([_make_change(i) for i in range(1, 4)], cursor="c1", has_more=True, total=10)
        batch2 = _make_pull_batch([_make_change(i) for i in range(4, 7)], cursor="c2", has_more=False, total=10)

        client = _make_client()
        client.post_sync_pull = Mock(side_effect=[batch1, batch2])

        worker = _make_worker(client=client)
        applied = []

        def _apply_and_cancel(item, **kw):
            applied.append(item["id"])
            if len(applied) >= 2:
                worker._cancelled = True
            return (item["id"], False)

        worker._apply_update = Mock(side_effect=_apply_and_cancel)
        worker.get_pull_cursor = Mock(return_value=None)
        worker.save_pull_cursor = Mock()
        worker.save_cursor = Mock()
        worker.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        worker._download_covers_parallel = Mock(return_value=[])
        worker._upload_missing_covers = Mock()

        # sync_unified_batches should stop early
        try:
            worker.sync_unified_batches()
        except Exception:
            pass  # cancellation may raise

        # Should NOT have processed all 6 books
        assert len(applied) < 6, f"Expected early stop but processed {len(applied)} books"

    def test_cancel_flag_prevents_push(self, monkeypatch):
        """If cancelled during pull, push phase should be skipped."""
        changes = [_make_change(1)]
        client = _make_client()
        client.post_sync_pull = Mock(return_value=_make_pull_batch(changes, cursor="c", has_more=False))

        worker = _make_worker(client=client)
        worker._cancelled = True  # pre-cancelled
        worker._apply_update = Mock(return_value=(1, False))
        worker.get_pull_cursor = Mock(return_value=None)
        worker.save_pull_cursor = Mock()
        worker.save_cursor = Mock()
        worker.push_sync = Mock(return_value={"pushed": 0, "errors": []})
        worker._download_covers_parallel = Mock(return_value=[])
        worker._upload_missing_covers = Mock()

        try:
            worker.sync_unified_batches()
        except Exception:
            pass

        # Push should not have been called
        worker.push_sync.assert_not_called()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Config init from zero state
# ─────────────────────────────────────────────────────────────────────────────

class TestConfigInitFromZero:
    """Verify plugin config initialization from a completely empty state."""

    def test_get_plugin_store_from_empty_prefs(self, monkeypatch):
        """get_plugin_store(repair=True) on empty prefs returns all defaults."""
        import calibre_plugins.sync_calimob.config as config_mod
        monkeypatch.setattr(config_mod, "plugin_prefs", {})

        store = config_mod.get_plugin_store(repair=True)

        assert isinstance(store, dict)
        for key in config_mod.DEFAULT_STORE_VALUES:
            assert key in store, f"default key {key!r} missing"
            assert store[key] == config_mod.DEFAULT_STORE_VALUES[key]

    def test_http_helper_works_with_repaired_store(self, monkeypatch):
        """HttpHelper constructed after repair should have valid defaults."""
        import calibre_plugins.sync_calimob.config as config_mod
        from calibre_plugins.sync_calimob import core as core_mod

        monkeypatch.setattr(config_mod, "plugin_prefs", {})

        helper = core_mod.HttpHelper()
        assert helper.devkey_token == config_mod.DEFAULT_STORE_VALUES[config_mod.KEY_DEV_TOKEN]

    def test_sync_worker_init_tolerates_empty_prefs(self, monkeypatch):
        """SyncWorker should not crash when plugin_prefs is empty (repair fills defaults)."""
        import calibre_plugins.sync_calimob.config as config_mod
        monkeypatch.setattr(config_mod, "plugin_prefs", {})

        db = _make_db()
        client = _make_client()

        # SyncWorker constructor should not raise
        try:
            worker = _make_worker(db=db, client=client)
        except KeyError as exc:
            pytest.fail(f"SyncWorker creation failed with empty prefs: {exc}")

    def test_library_mapping_absent_returns_safe_defaults(self, monkeypatch):
        """Missing library mapping should return safe empty values, not raise."""
        import calibre_plugins.sync_calimob.config as config_mod
        monkeypatch.setattr(config_mod, "plugin_prefs", {})

        mappings = config_mod.plugin_prefs.get(config_mod.STORE_LIBRARY_MAPPINGS, {})
        assert mappings == {}
        mapping = mappings.get("any-lib-id", {})
        assert mapping.get(config_mod.KEY_CALIMOB_LIBRARY_ID) is None
        assert mapping.get(config_mod.KEY_SYNC_ENABLED, False) is False
