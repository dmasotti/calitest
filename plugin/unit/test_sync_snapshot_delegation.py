"""Guardrail tests for legacy snapshot delegation."""


def test_sync_snapshot_delegates_to_legacy_module():
    """sync_snapshot was removed — verify it no longer exists on SyncWorker."""
    from calibre_plugins.sync_calimob import sync_worker

    assert not hasattr(sync_worker.SyncWorker, 'sync_snapshot'), \
        "sync_snapshot has been removed (legacy policy eliminated)"


def test_sync_current_delegates_to_current_module():
    """sync should delegate to sync_current_v5.run_current_sync."""
    from calibre_plugins.sync_calimob import sync_worker
    import inspect

    source = inspect.getsource(sync_worker.SyncWorker.sync)
    assert 'sync_current_v5' in source
    assert 'run_current_sync' in source


def test_cli_routes_through_sync_entrypoints():
    """CLI main should centralize route selection via sync_entrypoints.run_cli_sync."""
    import inspect
    from calibre_plugins.sync_calimob import cli

    source = inspect.getsource(cli.main)
    assert 'sync_entrypoints' in source
    assert 'run_cli_sync' in source
