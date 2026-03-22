"""
RED contract tests for sync_apply.py (Phase 5).

These tests define the TARGET API of SyncApplier as a standalone class.
They MUST FAIL before extraction and PASS after.

Design principles enforced:
- SyncApplier receives all dependencies via constructor (no globals)
- db.set_metadata, db.get_metadata accessed only via injected callables
- cfg access only via injected callable
- sync_mapper access only via injected callable
- Cover download delegated via injected callable (no Qt dependency)
- Each method has a clear return contract
"""
from __future__ import annotations

import sys
from unittest.mock import Mock

import pytest


# ─────────────────────────────────────────────────────────────────────────────
# Contract: module must exist and export SyncApplier
# ─────────────────────────────────────────────────────────────────────────────

class TestSyncApplyModuleExists:
    """sync_apply.py must exist and export SyncApplier."""

    def test_import_sync_apply(self):
        from calibre_plugins.sync_calimob import sync_apply
        assert hasattr(sync_apply, 'SyncApplier')

    def test_sync_applier_is_class(self):
        from calibre_plugins.sync_calimob.sync_apply import SyncApplier
        assert isinstance(SyncApplier, type)


# ─────────────────────────────────────────────────────────────────────────────
# Contract: constructor accepts dependency injection
# ─────────────────────────────────────────────────────────────────────────────

class TestSyncApplierConstructor:
    """SyncApplier must accept all dependencies via constructor kwargs."""

    def test_constructor_accepts_required_deps(self):
        from calibre_plugins.sync_calimob.sync_apply import SyncApplier

        applier = SyncApplier(
            db=Mock(),
            library_id='lib-1',
            cfg=Mock(),
            sync_mapper=Mock(),
        )
        assert applier is not None

    def test_constructor_accepts_optional_deps(self):
        from calibre_plugins.sync_calimob.sync_apply import SyncApplier

        applier = SyncApplier(
            db=Mock(),
            library_id='lib-1',
            cfg=Mock(),
            sync_mapper=Mock(),
            status_tag_mappings={},
            progress_percent_column=None,
            favorite_column=None,
            download_cover_fn=Mock(),
            should_download_cover_fn=Mock(),
            check_cancelled_fn=Mock(),
        )
        assert applier is not None


# ─────────────────────────────────────────────────────────────────────────────
# Contract: apply_update return type
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyUpdateReturnContract:
    """apply_update must return (book_id, was_modified) tuple."""

    def _make_applier(self):
        from calibre_plugins.sync_calimob.sync_apply import SyncApplier

        db = Mock()
        db.data = Mock()
        db.data.has_id = Mock(return_value=True)
        mi = Mock()
        mi.title = 'Test'
        mi.last_modified = Mock()
        mi.last_modified.timestamp = Mock(return_value=1000.0)
        mi.last_modified.__ne__ = Mock(return_value=True)
        db.get_metadata = Mock(return_value=mi)
        db.set_metadata = Mock()

        sm = Mock()
        sm.UNDEFINED_DATE = Mock()
        sm.json_item_to_calibre = Mock(return_value={'title': 'Server'})
        sm.calibre_to_json_item = Mock(return_value={'title': 'Local', 'cover': {}})

        cfg = Mock()
        cfg.get_book_mapping_entry = Mock(return_value={})
        cfg.update_book_cache = Mock()

        return SyncApplier(
            db=db,
            library_id='lib-1',
            cfg=cfg,
            sync_mapper=sm,
            status_tag_mappings={},
            download_cover_fn=Mock(),
            should_download_cover_fn=Mock(return_value=(False, 'skip')),
            check_cancelled_fn=Mock(),
        )

    def test_returns_tuple(self):
        applier = self._make_applier()
        result = applier.apply_update({'uuid': 'uuid-1', 'title': 'X', 'last_modified': 2000})
        assert isinstance(result, tuple)
        assert len(result) == 2

    def test_returns_book_id_and_bool(self):
        applier = self._make_applier()
        book_id, modified = applier.apply_update({'uuid': 'uuid-1', 'title': 'X', 'last_modified': 2000})
        assert isinstance(modified, bool)


# ─────────────────────────────────────────────────────────────────────────────
# Contract: apply_update does NOT call db.get_metadata via globals
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyUpdateNoGlobals:
    """SyncApplier must not access sync_worker.cfg or sync_worker.sync_mapper."""

    def test_no_global_cfg_access(self):
        """SyncApplier must use injected cfg, not module-level cfg."""
        import os
        from calibre_plugins.sync_calimob import sync_apply

        src_path = os.path.join(os.path.dirname(sync_apply.__file__), 'sync_apply.py')
        with open(src_path, 'r') as f:
            code = f.read()

        # Should not have bare 'cfg.' calls (only self._cfg or self.cfg)
        lines = code.split('\n')
        violations = []
        for i, line in enumerate(lines, 1):
            stripped = line.strip()
            if stripped.startswith('#') or stripped.startswith('"""') or stripped.startswith("'''"):
                continue
            # Match 'cfg.something(' but not 'self.cfg.' or 'self._cfg.' or '_get_cfg()'
            if 'cfg.' in stripped and 'self.' not in stripped.split('cfg.')[0]:
                # Exclude imports and comments
                if 'import' not in stripped and '#' not in stripped.split('cfg.')[0]:
                    violations.append((i, stripped))

        assert not violations, (
            f"sync_apply.py has bare cfg access (should use self._cfg): {violations}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# Contract: apply_deleted returns (uuids_set, had_errors)
# ─────────────────────────────────────────────────────────────────────────────

class TestApplyDeletedContract:
    """apply_deleted must return (set_of_deleted_uuids, had_errors_bool)."""

    def test_apply_deleted_exists(self):
        from calibre_plugins.sync_calimob.sync_apply import SyncApplier
        assert hasattr(SyncApplier, 'apply_deleted')

    def test_empty_list_returns_empty_set(self):
        from calibre_plugins.sync_calimob.sync_apply import SyncApplier

        applier = SyncApplier(
            db=Mock(), library_id='lib-1',
            cfg=Mock(), sync_mapper=Mock(),
        )
        uuids, errors = applier.apply_deleted([], '/tmp', {})
        assert isinstance(uuids, set)
        assert len(uuids) == 0
        assert errors is False


# ─────────────────────────────────────────────────────────────────────────────
# Contract: normalize_file_hash is a static/class method or module function
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalizeFileHashContract:
    """normalize_file_hash must be accessible without SyncWorker."""

    def test_normalize_accessible(self):
        from calibre_plugins.sync_calimob import sync_apply
        assert hasattr(sync_apply, 'normalize_file_hash') or \
            hasattr(sync_apply.SyncApplier, 'normalize_file_hash')

    def test_normalize_adds_sha256_prefix(self):
        from calibre_plugins.sync_calimob import sync_apply
        fn = getattr(sync_apply, 'normalize_file_hash', None) or \
            getattr(sync_apply.SyncApplier, 'normalize_file_hash', None)
        if callable(fn):
            # If it's an unbound method, create instance
            try:
                result = fn('abcdef')
            except TypeError:
                applier = sync_apply.SyncApplier(
                    db=Mock(), library_id='lib-1',
                    cfg=Mock(), sync_mapper=Mock(),
                )
                result = applier.normalize_file_hash('abcdef')
            assert result == 'sha256:abcdef'
