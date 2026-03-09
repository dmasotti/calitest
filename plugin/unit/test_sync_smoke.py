"""Smoke test to verify sync_v5 doesn't have obvious errors."""
import pytest


def test_sync_v5_has_required_variables():
    """Verify sync_v5 code doesn't reference undefined variables."""
    from calibre_plugins.sync_calimob import sync_worker
    import inspect
    
    # Get sync_v5 source code
    source = inspect.getsource(sync_worker.SyncWorker.sync_v5)
    
    # Check that sync_library_path is defined before use
    lines = source.split('\n')
    sync_library_path_defined = False
    sync_library_path_used = False
    
    for i, line in enumerate(lines):
        if 'sync_library_path =' in line:
            sync_library_path_defined = True
        if 'sync_library_path' in line and '=' not in line:
            sync_library_path_used = True
            if not sync_library_path_defined:
                pytest.fail(
                    f"sync_library_path used at line {i} before being defined:\n{line}"
                )
    
    assert sync_library_path_defined or not sync_library_path_used, \
        "sync_library_path is used but never defined"
