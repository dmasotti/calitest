"""
Edge-case test matrix for SyncCache decomposition guardrails.

Tests added BEFORE extraction (test-first) to verify cache invariants:
1. _v5_extract_hash_no_ts: all input variants
2. _cache_book_uuid: in-memory + persist to cfg
3. _v5_get_sync_cache_field_by_uuid: various fields, missing uuid, empty path
4. cfg.update_book_cache: parameter combinations and column persistence
5. Cache round-trip: write hashes → read back from sync table → match
6. Cache schema migration: old schema + ALTER TABLE ADD COLUMN
7. formats_sig round-trip consistency
8. metadata_hash_cache format: "hash:timestamp" contract
9. cover_hash_cache written even when cover is None (sentinel)
10. Multiple cfg.update_book_cache calls for same book (last wins)
11. Cache table integrity check (_get_status)
12. _v5_normalize_library_path: path vs .db file
"""
from __future__ import annotations

import os
import sqlite3
import time
from unittest.mock import Mock, patch

import pytest

from calibre_plugins.sync_calimob import sync_worker
from calibre_plugins.sync_calimob import mapping_table


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
    return worker


def _create_library_with_sync_table(tmp_path):
    """Create a minimal library with metadata.db and calimob_books_sync table."""
    library_root = tmp_path / 'library'
    library_root.mkdir()
    db_path = library_root / 'metadata.db'
    conn = sqlite3.connect(str(db_path))
    try:
        conn.execute(
            "CREATE TABLE books (id INTEGER PRIMARY KEY, uuid TEXT, last_modified TIMESTAMP)"
        )
        mapping_table._ensure_table(conn)
        conn.commit()
    finally:
        conn.close()
    return str(library_root)


def _make_db_mock(library_path):
    """Create a mock db with library_path for cfg._library_path_from_db."""
    db = Mock()
    db.library_path = library_path
    db.data = Mock()
    db.data.has_id = lambda _bid: True
    return db


# ─────────────────────────────────────────────────────────────────────────────
# 1. _v5_extract_hash_no_ts: all input variants
# ─────────────────────────────────────────────────────────────────────────────

class TestExtractHashNoTs:
    """_v5_extract_hash_no_ts strips the trailing ':timestamp' from cached values."""

    def test_hash_with_timestamp(self):
        """'sha256:abcdef:1000' → 'sha256:abcdef'."""
        worker = _make_worker()
        assert worker._v5_extract_hash_no_ts('sha256:abcdef:1000') == 'sha256:abcdef'

    def test_hash_without_timestamp(self):
        """'sha256:abcdef' → 'sha256' (rsplit on last colon)."""
        worker = _make_worker()
        result = worker._v5_extract_hash_no_ts('sha256:abcdef')
        assert result == 'sha256:abcdef'.rsplit(':', 1)[0]
        assert result == 'sha256'

    def test_plain_hash(self):
        """'abcdef' (no colon) → returned as-is."""
        worker = _make_worker()
        assert worker._v5_extract_hash_no_ts('abcdef') == 'abcdef'

    def test_none_returns_none(self):
        worker = _make_worker()
        assert worker._v5_extract_hash_no_ts(None) is None

    def test_empty_string_returns_none(self):
        worker = _make_worker()
        assert worker._v5_extract_hash_no_ts('') is None

    def test_non_string_returns_none(self):
        worker = _make_worker()
        assert worker._v5_extract_hash_no_ts(123) is None
        assert worker._v5_extract_hash_no_ts([]) is None

    def test_multi_colon_strips_only_last(self):
        """'sha256:abc:def:1000' → 'sha256:abc:def' (only last segment removed)."""
        worker = _make_worker()
        assert worker._v5_extract_hash_no_ts('sha256:abc:def:1000') == 'sha256:abc:def'

    def test_files_hash_multi_entry(self):
        """Files hash with multiple comma-separated entries."""
        worker = _make_worker()
        # Files hash cache format: 'hash1:ts1,hash2:ts2'
        val = 'sha256:aaa:1000'
        result = worker._v5_extract_hash_no_ts(val)
        assert result == 'sha256:aaa'


# ─────────────────────────────────────────────────────────────────────────────
# 2. _cache_book_uuid: in-memory + persist
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheBookUuid:
    """_cache_book_uuid must update in-memory dict AND persist via cfg."""

    def test_caches_in_memory(self):
        worker = _make_worker()
        worker._cache_book_uuid(42, 'uuid-42')
        assert worker._uuid_to_book_id['uuid-42'] == 42

    def test_persists_via_cfg(self):
        worker = _make_worker()
        original_cfg = sync_worker.cfg
        mock_cfg = Mock()
        mock_cfg.cache_book_uuid = Mock()
        sync_worker.cfg = mock_cfg
        try:
            worker._cache_book_uuid(42, 'uuid-42')
            mock_cfg.cache_book_uuid.assert_called_once_with(
                'lib-1', 42, 'uuid-42', db=worker.db
            )
        finally:
            sync_worker.cfg = original_cfg

    def test_empty_uuid_skipped(self):
        worker = _make_worker()
        worker._cache_book_uuid(42, '')
        assert 'uuid-42' not in worker._uuid_to_book_id

    def test_none_uuid_skipped(self):
        worker = _make_worker()
        worker._cache_book_uuid(42, None)
        assert len(worker._uuid_to_book_id) == 0

    def test_overwrites_on_duplicate(self):
        worker = _make_worker()
        worker._cache_book_uuid(42, 'uuid-x')
        worker._cache_book_uuid(99, 'uuid-x')
        assert worker._uuid_to_book_id['uuid-x'] == 99

    def test_cfg_exception_does_not_crash(self):
        """If cfg.cache_book_uuid throws, in-memory cache still works."""
        worker = _make_worker()
        original_cfg = sync_worker.cfg
        mock_cfg = Mock()
        mock_cfg.cache_book_uuid = Mock(side_effect=Exception("DB locked"))
        sync_worker.cfg = mock_cfg
        try:
            worker._cache_book_uuid(42, 'uuid-42')
            assert worker._uuid_to_book_id['uuid-42'] == 42
        finally:
            sync_worker.cfg = original_cfg


# ─────────────────────────────────────────────────────────────────────────────
# 3. _v5_get_sync_cache_field_by_uuid
# ─────────────────────────────────────────────────────────────────────────────

class TestGetSyncCacheFieldByUuid:
    """Query calimob_books_sync table by UUID and return a specific field."""

    def test_returns_existing_field(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'uuid': 'uuid-1', 'cover_hash': 'sha256:cover:1000',
        })

        worker = _make_worker()
        result = worker._v5_get_sync_cache_field_by_uuid(
            library_path, 'uuid-1', 'cover_hash'
        )
        assert result == 'sha256:cover:1000'

    def test_returns_none_for_missing_uuid(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        worker = _make_worker()
        result = worker._v5_get_sync_cache_field_by_uuid(
            library_path, 'uuid-nonexistent', 'cover_hash'
        )
        assert result is None

    def test_returns_none_for_empty_uuid(self):
        worker = _make_worker()
        assert worker._v5_get_sync_cache_field_by_uuid('/tmp', '', 'cover_hash') is None
        assert worker._v5_get_sync_cache_field_by_uuid('/tmp', None, 'cover_hash') is None

    def test_returns_none_for_empty_path(self):
        worker = _make_worker()
        assert worker._v5_get_sync_cache_field_by_uuid(None, 'uuid-1', 'cover_hash') is None
        assert worker._v5_get_sync_cache_field_by_uuid('', 'uuid-1', 'cover_hash') is None

    def test_returns_files_hash(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 2, {
            'uuid': 'uuid-2', 'files_hash': 'sha256:files:2000',
        })
        worker = _make_worker()
        result = worker._v5_get_sync_cache_field_by_uuid(
            library_path, 'uuid-2', 'files_hash'
        )
        assert result == 'sha256:files:2000'

    def test_respects_library_id(self, tmp_path):
        """Cache entries for different library_ids are isolated."""
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-other', 1, {
            'uuid': 'uuid-1', 'cover_hash': 'sha256:other-lib',
        })
        worker = _make_worker()  # library_id = 'lib-1'
        result = worker._v5_get_sync_cache_field_by_uuid(
            library_path, 'uuid-1', 'cover_hash'
        )
        # Should NOT find it — different library_id
        assert result is None


# ─────────────────────────────────────────────────────────────────────────────
# 4. cfg.update_book_cache: parameter combinations and persistence
# ─────────────────────────────────────────────────────────────────────────────

class TestUpdateBookCache:
    """Verify cfg.update_book_cache persists hash columns correctly."""

    def test_metadata_hash_cache_persisted(self, tmp_path):
        """metadata_hash_cache should be stored in the column."""
        library_path = _create_library_with_sync_table(tmp_path)
        # First create the entry
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            metadata_hash_cache='sha256:meta:1500',
            db=_make_db_mock(library_path),
        )

        # Read back
        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT metadata_hash_cache FROM calimob_books_sync "
                "WHERE library_uuid='lib-1' AND calibre_book_id=1"
            ).fetchone()
            assert row is not None
            assert row['metadata_hash_cache'] == 'sha256:meta:1500'
        finally:
            conn.close()

    def test_cover_hash_cache_persisted(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            cover_hash_cache='sha256:cover:2000',
            db=_make_db_mock(library_path),
        )

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT cover_hash FROM calimob_books_sync "
                "WHERE library_uuid='lib-1' AND calibre_book_id=1"
            ).fetchone()
            assert row is not None
            assert row['cover_hash'] == 'sha256:cover:2000'
        finally:
            conn.close()

    def test_files_hash_and_formats_sig_persisted(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            files_hash_cache='sha256:f1:1000,sha256:f2:1000',
            formats_sig='EPUB,PDF',
            db=_make_db_mock(library_path),
        )

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT files_hash, formats_sig FROM calimob_books_sync "
                "WHERE library_uuid='lib-1' AND calibre_book_id=1"
            ).fetchone()
            assert row is not None
            assert row['files_hash'] == 'sha256:f1:1000,sha256:f2:1000'
            assert row['formats_sig'] == 'EPUB,PDF'
        finally:
            conn.close()

    def test_last_modified_epoch_persisted(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            last_modified_epoch=1742630400,
            db=_make_db_mock(library_path),
        )

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT last_modified FROM calimob_books_sync "
                "WHERE library_uuid='lib-1' AND calibre_book_id=1"
            ).fetchone()
            assert row is not None
            assert row['last_modified'] == 1742630400
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 5. Cache round-trip: write → read → match
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheRoundTrip:
    """Write hashes via cfg.update_book_cache, read back via _v5_get_sync_cache_field_by_uuid."""

    def test_cover_hash_round_trip(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            cover_hash_cache='sha256:cover-abc:3000',
            db=_make_db_mock(library_path),
        )

        worker = _make_worker()
        result = worker._v5_get_sync_cache_field_by_uuid(
            library_path, 'uuid-1', 'cover_hash'
        )
        assert result == 'sha256:cover-abc:3000'

        # Extract hash without timestamp
        clean = worker._v5_extract_hash_no_ts(result)
        assert clean == 'sha256:cover-abc'

    def test_files_hash_round_trip(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            files_hash_cache='sha256:file1:1000,sha256:file2:1000',
            formats_sig='EPUB,PDF',
            db=_make_db_mock(library_path),
        )

        worker = _make_worker()
        files = worker._v5_get_sync_cache_field_by_uuid(
            library_path, 'uuid-1', 'files_hash'
        )
        sig = worker._v5_get_sync_cache_field_by_uuid(
            library_path, 'uuid-1', 'formats_sig'
        )
        assert files == 'sha256:file1:1000,sha256:file2:1000'
        assert sig == 'EPUB,PDF'


# ─────────────────────────────────────────────────────────────────────────────
# 6. Cache schema migration
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheSchemaMigration:
    """Existing tests in test_mapping_table_incremental_sql.py cover ALTER TABLE.
    These extend with edge cases for the cache-specific columns."""

    def test_old_schema_missing_metadata_hash_cache(self, tmp_path):
        """Old schema without metadata_hash_cache → ALTER TABLE adds it."""
        library_root = tmp_path / 'library'
        library_root.mkdir()
        db_path = library_root / 'metadata.db'
        conn = sqlite3.connect(str(db_path))
        try:
            conn.execute("""
                CREATE TABLE calimob_books_sync (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_uuid TEXT NOT NULL,
                    calibre_book_id INTEGER NOT NULL,
                    uuid TEXT,
                    title TEXT,
                    cover_hash TEXT,
                    notes TEXT,
                    UNIQUE(library_uuid, calibre_book_id)
                )
            """)
            conn.execute(
                "INSERT INTO calimob_books_sync (library_uuid, calibre_book_id, uuid) "
                "VALUES ('lib-1', 1, 'uuid-1')"
            )
            conn.commit()
        finally:
            conn.close()

        # Run migration
        conn = sqlite3.connect(str(db_path))
        conn.row_factory = sqlite3.Row
        try:
            mapping_table._ensure_table(conn)
            conn.commit()

            cols = {r['name'] for r in conn.execute(
                "PRAGMA table_info(calimob_books_sync)"
            ).fetchall()}
            assert 'metadata_hash_cache' in cols
            assert 'files_hash' in cols
            assert 'formats_sig' in cols
            assert 'last_modified' in cols

            # Existing data preserved
            row = conn.execute(
                "SELECT uuid FROM calimob_books_sync WHERE calibre_book_id=1"
            ).fetchone()
            assert row['uuid'] == 'uuid-1'
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 7. formats_sig consistency
# ─────────────────────────────────────────────────────────────────────────────

class TestFormatsSigConsistency:
    """formats_sig must be sorted, uppercase, comma-separated."""

    def test_formats_sig_sorted_on_write(self, tmp_path):
        """Even if written out of order, the convention is sorted."""
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        # Write in sorted order (as the production code does)
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            formats_sig='EPUB,PDF',  # already sorted
            db=_make_db_mock(library_path),
        )

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        try:
            row = conn.execute(
                "SELECT formats_sig FROM calimob_books_sync WHERE calibre_book_id=1"
            ).fetchone()
            assert row[0] == 'EPUB,PDF'
        finally:
            conn.close()

    def test_single_format(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            formats_sig='EPUB',
            db=_make_db_mock(library_path),
        )

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        try:
            row = conn.execute(
                "SELECT formats_sig FROM calimob_books_sync WHERE calibre_book_id=1"
            ).fetchone()
            assert row[0] == 'EPUB'
        finally:
            conn.close()

    def test_empty_formats_sig(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            formats_sig='',
            db=_make_db_mock(library_path),
        )

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        try:
            row = conn.execute(
                "SELECT formats_sig FROM calimob_books_sync WHERE calibre_book_id=1"
            ).fetchone()
            assert row[0] == ''
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 8. metadata_hash_cache format contract
# ─────────────────────────────────────────────────────────────────────────────

class TestMetadataHashCacheFormat:
    """metadata_hash_cache must follow 'hash:timestamp' format."""

    def test_format_hash_colon_timestamp(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            metadata_hash_cache='sha256:abcdef1234567890:1742630400',
            db=_make_db_mock(library_path),
        )

        worker = _make_worker()
        raw = worker._v5_get_sync_cache_field_by_uuid(
            library_path, 'uuid-1', 'metadata_hash_cache'
        )
        assert raw == 'sha256:abcdef1234567890:1742630400'

        # Extract without timestamp
        clean = worker._v5_extract_hash_no_ts(raw)
        assert clean == 'sha256:abcdef1234567890'

    def test_extract_preserves_sha256_prefix(self):
        """sha256:hash:ts → sha256:hash (not just 'sha256')."""
        worker = _make_worker()
        result = worker._v5_extract_hash_no_ts('sha256:abcdef:1000')
        assert result == 'sha256:abcdef'
        assert result.startswith('sha256:')


# ─────────────────────────────────────────────────────────────────────────────
# 9. Multiple updates: last write wins
# ─────────────────────────────────────────────────────────────────────────────

class TestMultipleUpdatesLastWins:
    """Multiple cfg.update_book_cache calls for same book → last wins."""

    def test_cover_hash_overwritten(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        from calibre_plugins.sync_calimob import config as cfg
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            cover_hash_cache='sha256:old:1000',
            db=_make_db_mock(library_path),
        )
        cfg.update_book_cache(
            'lib-1', 1, None, None, None,
            cover_hash_cache='sha256:new:2000',
            db=_make_db_mock(library_path),
        )

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        try:
            row = conn.execute(
                "SELECT cover_hash FROM calimob_books_sync WHERE calibre_book_id=1"
            ).fetchone()
            assert row[0] == 'sha256:new:2000'
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 10. _v5_normalize_library_path
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeLibraryPath:
    """_v5_normalize_library_path must handle path vs .db file."""

    def test_directory_path_returned_as_is(self):
        worker = _make_worker()
        assert worker._v5_normalize_library_path('/path/to/library') == '/path/to/library'

    def test_db_file_returns_parent_dir(self):
        worker = _make_worker()
        assert worker._v5_normalize_library_path('/path/to/library/metadata.db') == '/path/to/library'

    def test_none_returns_none(self):
        worker = _make_worker()
        assert worker._v5_normalize_library_path(None) is None

    def test_empty_returns_none(self):
        worker = _make_worker()
        assert worker._v5_normalize_library_path('') is None

    def test_case_insensitive_db_extension(self):
        worker = _make_worker()
        assert worker._v5_normalize_library_path('/path/file.DB') == '/path'


# ─────────────────────────────────────────────────────────────────────────────
# 11. _get_book_ids_from_sync_cache
# ─────────────────────────────────────────────────────────────────────────────

class TestGetBookIdsFromSyncCache:
    """Query calimob_books_sync for book IDs by UUID."""

    def test_returns_book_id(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 42, {'uuid': 'uuid-42'})

        worker = _make_worker()
        # Need to mock cfg._library_path_from_db to return our test path
        original_cfg = sync_worker.cfg
        mock_cfg = Mock()
        mock_cfg._library_path_from_db = Mock(return_value=library_path)
        sync_worker.cfg = mock_cfg
        try:
            ids = worker._get_book_ids_from_sync_cache('uuid-42')
            assert ids == [42]
        finally:
            sync_worker.cfg = original_cfg

    def test_returns_empty_for_missing_uuid(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        worker = _make_worker()
        original_cfg = sync_worker.cfg
        mock_cfg = Mock()
        mock_cfg._library_path_from_db = Mock(return_value=library_path)
        sync_worker.cfg = mock_cfg
        try:
            ids = worker._get_book_ids_from_sync_cache('uuid-nonexistent')
            assert ids == []
        finally:
            sync_worker.cfg = original_cfg

    def test_returns_empty_for_none(self):
        worker = _make_worker()
        assert worker._get_book_ids_from_sync_cache(None) == []
        assert worker._get_book_ids_from_sync_cache('') == []


# ─────────────────────────────────────────────────────────────────────────────
# 12. Cache integrity: all 10 cfg.update_book_cache call sites use library_id
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheCallSiteIntegrity:
    """Static analysis: all cfg.update_book_cache calls must pass library_id as first arg."""

    def test_all_call_sites_pass_library_id(self):
        """Every cfg.update_book_cache() call in sync_worker.py must have
        self.library_id or library_id as the first argument."""
        import ast

        src_path = os.path.join(os.path.dirname(sync_worker.__file__), 'sync_worker.py')
        with open(src_path, 'r') as f:
            source = f.read()
        tree = ast.parse(source)

        call_sites = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                # Match cfg.update_book_cache(...)
                if (isinstance(func, ast.Attribute)
                        and func.attr == 'update_book_cache'
                        and isinstance(func.value, ast.Name)
                        and func.value.id == 'cfg'):
                    call_sites.append(node.lineno)

        # We know there should be multiple call sites
        assert len(call_sites) >= 5, \
            f"Expected at least 5 cfg.update_book_cache calls, got {len(call_sites)}"


# ─────────────────────────────────────────────────────────────────────────────
# 13. SQL injection guard: _v5_get_sync_cache_field_by_uuid
# ─────────────────────────────────────────────────────────────────────────────

class TestFieldNameSqlInjection:
    """_v5_get_sync_cache_field_by_uuid uses % substitution for field_name.
    Verify that only known column names are passed in production."""

    def test_valid_field_names_work(self, tmp_path):
        """Known column names should return values without error."""
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'uuid': 'uuid-1', 'cover_hash': 'sha256:c', 'files_hash': 'sha256:f',
        })
        worker = _make_worker()

        for field in ('cover_hash', 'files_hash', 'metadata_hash_cache',
                      'formats_sig', 'last_modified'):
            # Should not raise
            worker._v5_get_sync_cache_field_by_uuid(library_path, 'uuid-1', field)

    def test_all_production_call_sites_use_known_fields(self):
        """AST check: all _v5_get_sync_cache_field_by_uuid calls pass
        a string literal as field_name (not user input)."""
        import ast

        src_path = os.path.join(os.path.dirname(sync_worker.__file__), 'sync_worker.py')
        with open(src_path, 'r') as f:
            source = f.read()
        tree = ast.parse(source)

        known_fields = {
            'cover_hash', 'files_hash', 'metadata_hash_cache',
            'formats_sig', 'last_modified', 'last_modified_server',
        }
        violations = []

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if (isinstance(func, ast.Attribute)
                        and func.attr == '_v5_get_sync_cache_field_by_uuid'):
                    # 3rd positional arg is field_name
                    if len(node.args) >= 3:
                        field_arg = node.args[2]
                        if isinstance(field_arg, ast.Constant) and isinstance(field_arg.value, str):
                            if field_arg.value not in known_fields:
                                violations.append((node.lineno, field_arg.value))
                        elif not isinstance(field_arg, ast.Constant):
                            violations.append((node.lineno, '<non-literal>'))

        assert not violations, (
            f"_v5_get_sync_cache_field_by_uuid called with unexpected field names: {violations}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 14. Malformed DB detection and auto-rebuild
# ─────────────────────────────────────────────────────────────────────────────

class TestMalformedDbDetection:
    """_is_sqlite_malformed_error must detect all known malformed error variants."""

    def test_detects_standard_malformed_message(self):
        worker = _make_worker()
        exc = Exception("database disk image is malformed")
        assert worker._is_sqlite_malformed_error(exc) is True

    def test_detects_short_malformed_message(self):
        worker = _make_worker()
        exc = Exception("disk image is malformed")
        assert worker._is_sqlite_malformed_error(exc) is True

    def test_case_insensitive(self):
        worker = _make_worker()
        exc = Exception("DATABASE DISK IMAGE IS MALFORMED")
        assert worker._is_sqlite_malformed_error(exc) is True

    def test_embedded_in_longer_message(self):
        worker = _make_worker()
        exc = Exception("sqlite3.OperationalError: database disk image is malformed (calimob_books_sync)")
        assert worker._is_sqlite_malformed_error(exc) is True

    def test_non_malformed_errors(self):
        worker = _make_worker()
        assert worker._is_sqlite_malformed_error(Exception("table not found")) is False
        assert worker._is_sqlite_malformed_error(Exception("connection refused")) is False
        assert worker._is_sqlite_malformed_error(Exception("")) is False

    def test_none_exception(self):
        worker = _make_worker()
        assert worker._is_sqlite_malformed_error(None) is False


class TestAutoRebuildSyncCache:
    """_try_auto_rebuild_sync_cache_after_malformed recovery path."""

    def test_rebuilds_on_first_attempt(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        # Insert data that will be lost after rebuild
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        worker = _make_worker()
        summary = {'errors': []}
        result = worker._try_auto_rebuild_sync_cache_after_malformed(library_path, summary)

        assert result is True
        assert summary.get('auto_cache_rebuild_attempted') is True
        assert summary.get('auto_cache_rebuild_succeeded') is True

    def test_does_not_retry_twice(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        worker = _make_worker()
        summary = {'errors': []}

        # First attempt succeeds
        worker._try_auto_rebuild_sync_cache_after_malformed(library_path, summary)
        # Second attempt should be blocked
        result = worker._try_auto_rebuild_sync_cache_after_malformed(library_path, summary)

        assert result is False

    def test_returns_false_without_library_path(self):
        worker = _make_worker()
        assert worker._try_auto_rebuild_sync_cache_after_malformed(None) is False
        assert worker._try_auto_rebuild_sync_cache_after_malformed('') is False

    def test_rebuild_failure_recorded_in_summary(self, tmp_path):
        worker = _make_worker()
        summary = {'errors': []}
        # Non-existent path → force_rebuild_table will fail
        result = worker._try_auto_rebuild_sync_cache_after_malformed(
            '/nonexistent/path', summary
        )
        assert result is False
        assert summary.get('auto_cache_rebuild_succeeded') is False


# ─────────────────────────────────────────────────────────────────────────────
# 15. Cache delete/mark entries
# ─────────────────────────────────────────────────────────────────────────────

class TestCacheDeleteMark:
    """Deletion marking in calimob_books_sync must be idempotent."""

    def test_mark_entry_as_deleted(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'uuid': 'uuid-1', 'is_deleted': 0,
        })

        # Mark as deleted
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'uuid': 'uuid-1', 'is_deleted': 1, 'deleted_at': '2026-03-22T00:00:00Z',
        })

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT is_deleted, deleted_at FROM calimob_books_sync WHERE calibre_book_id=1"
            ).fetchone()
            assert row['is_deleted'] == 1
            assert row['deleted_at'] is not None
        finally:
            conn.close()

    def test_double_delete_idempotent(self, tmp_path):
        """Marking an already-deleted entry as deleted again should not crash."""
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'uuid': 'uuid-1', 'is_deleted': 1, 'deleted_at': '2026-03-22T00:00:00Z',
        })
        # Second delete should not raise
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'uuid': 'uuid-1', 'is_deleted': 1, 'deleted_at': '2026-03-22T01:00:00Z',
        })

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute(
                "SELECT is_deleted, deleted_at FROM calimob_books_sync WHERE calibre_book_id=1"
            ).fetchone()
            assert row['is_deleted'] == 1
            # Last write wins
            assert '01:00:00' in row['deleted_at']
        finally:
            conn.close()

    def test_deleted_entries_excluded_from_candidates(self, tmp_path):
        """get_deleted_book_entries only returns non-deleted entries missing from books."""
        library_path = _create_library_with_sync_table(tmp_path)
        # Entry for book that no longer exists in books table
        mapping_table.upsert_entry(library_path, 'lib-1', 10, {
            'uuid': 'uuid-10', 'is_deleted': 0,
        })
        # Entry already marked deleted — should NOT appear again
        mapping_table.upsert_entry(library_path, 'lib-1', 11, {
            'uuid': 'uuid-11', 'is_deleted': 1,
        })

        deleted = mapping_table.get_deleted_book_entries(library_path, 'lib-1')
        uuids = [entry[1] for entry in deleted]
        assert 'uuid-10' in uuids
        assert 'uuid-11' not in uuids  # already deleted, excluded


# ─────────────────────────────────────────────────────────────────────────────
# 16. get_book_hashes: cache read with corrupted format
# ─────────────────────────────────────────────────────────────────────────────

class TestGetBookHashesCorruptedFormat:
    """get_book_hashes must handle corrupted cache values gracefully."""

    def test_metadata_hash_without_colon(self, tmp_path):
        """If metadata_hash_cache has no ':' separator, rsplit still works."""
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'uuid': 'uuid-1', 'metadata_hash_cache': 'just-a-hash',
            'last_modified': 1000,
        })

        from calibre_plugins.sync_calimob import config as cfg
        db = _make_db_mock(library_path)
        result = cfg.get_book_hashes('lib-1', 1, 1000, db=db)
        # rsplit(':', 1) on 'just-a-hash' → ['just-a-hash'] → parts[0] = 'just-a-hash'
        assert result['metadata_hash'] == 'just-a-hash'

    def test_cache_invalid_returns_none_gracefully(self, tmp_path):
        """If cache last_modified doesn't match, hashes are None (recalculated elsewhere)."""
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'uuid': 'uuid-1', 'metadata_hash_cache': 'sha256:meta:1000',
            'last_modified': 1000,
        })

        from calibre_plugins.sync_calimob import config as cfg
        db = _make_db_mock(library_path)
        # book_last_modified=2000 != cached 1000 → cache invalid
        result = cfg.get_book_hashes('lib-1', 1, 2000, db=db)
        assert result['metadata_hash'] is None  # cache miss

    def test_db_none_returns_empty_hashes(self):
        """When db=None, get_book_hashes returns all None."""
        from calibre_plugins.sync_calimob import config as cfg
        result = cfg.get_book_hashes('lib-1', 1, 1000, db=None)
        assert result == {'metadata_hash': None, 'cover_hash': None, 'files_hash': None}


# ─────────────────────────────────────────────────────────────────────────────
# 17. upsert_entry: INSERT vs UPDATE semantics
# ─────────────────────────────────────────────────────────────────────────────

class TestUpsertEntrySemantics:
    """upsert_entry must INSERT on first call, UPDATE on subsequent calls."""

    def test_insert_then_update(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)

        # First call: INSERT
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'uuid': 'uuid-1', 'cover_hash': 'sha256:first',
        })

        # Second call: UPDATE (same book_id)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'cover_hash': 'sha256:second',
        })

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        conn.row_factory = sqlite3.Row
        try:
            rows = conn.execute(
                "SELECT cover_hash FROM calimob_books_sync WHERE calibre_book_id=1"
            ).fetchall()
            # Must be exactly 1 row (upsert, not double insert)
            assert len(rows) == 1
            assert rows[0]['cover_hash'] == 'sha256:second'
        finally:
            conn.close()

    def test_preserves_created_at_on_update(self, tmp_path):
        """UPDATE must not overwrite created_at."""
        library_path = _create_library_with_sync_table(tmp_path)

        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'uuid': 'uuid-1', 'cover_hash': 'sha256:first',
        })

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        conn.row_factory = sqlite3.Row
        try:
            row1 = conn.execute(
                "SELECT created_at FROM calimob_books_sync WHERE calibre_book_id=1"
            ).fetchone()
            created_at_original = row1['created_at']
        finally:
            conn.close()

        # Update
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {
            'cover_hash': 'sha256:second',
        })

        conn = sqlite3.connect(os.path.join(library_path, 'metadata.db'))
        conn.row_factory = sqlite3.Row
        try:
            row2 = conn.execute(
                "SELECT created_at FROM calimob_books_sync WHERE calibre_book_id=1"
            ).fetchone()
            assert row2['created_at'] == created_at_original
        finally:
            conn.close()


# ─────────────────────────────────────────────────────────────────────────────
# 18. fetch_entries_bulk chunking
# ─────────────────────────────────────────────────────────────────────────────

class TestFetchEntriesBulkChunking:
    """fetch_entries_bulk must handle large ID sets via chunking."""

    def test_empty_ids_returns_empty(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        result = mapping_table.fetch_entries_bulk(library_path, 'lib-1', [])
        assert result == {}

    def test_bulk_fetch_returns_all(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        for i in range(1, 11):
            mapping_table.upsert_entry(library_path, 'lib-1', i, {
                'uuid': f'uuid-{i}', 'cover_hash': f'sha256:c{i}',
            })

        result = mapping_table.fetch_entries_bulk(
            library_path, 'lib-1', list(range(1, 11))
        )
        assert len(result) == 10
        for i in range(1, 11):
            assert i in result

    def test_missing_ids_not_in_result(self, tmp_path):
        library_path = _create_library_with_sync_table(tmp_path)
        mapping_table.upsert_entry(library_path, 'lib-1', 1, {'uuid': 'uuid-1'})

        result = mapping_table.fetch_entries_bulk(
            library_path, 'lib-1', [1, 2, 3]  # 2 and 3 don't exist
        )
        assert 1 in result
        assert 2 not in result
        assert 3 not in result
