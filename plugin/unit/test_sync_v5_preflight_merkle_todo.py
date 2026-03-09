"""
Test-first contracts for sync v5 preflight unification and metadata Merkle drill-down.

These tests intentionally describe target behavior and should fail until
the implementation is completed.
"""
from pathlib import Path
import importlib.util


PLUGIN_ROOT = Path(__file__).resolve().parents[3] / "sync_calimob"
SYNC_WORKER = PLUGIN_ROOT / "sync_worker.py"
REST_CLIENT = PLUGIN_ROOT / "rest_client.py"


def _read_sync_worker() -> str:
    return SYNC_WORKER.read_text(encoding="utf-8")


def _load_rest_client_module():
    spec = importlib.util.spec_from_file_location("rest_client", str(REST_CLIENT))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_fast_path_uses_single_preflight_get_library_hash_only():
    """
    TODO target:
    - client preflight must use ONE GET (/api/sync/v5/library-hash)
    - no separate get_merkle_root preflight call in sync_v5 fast path.
    """
    code = _read_sync_worker()

    anchor = "Fast path: check library hash before full sync"
    start = code.find(anchor)
    assert start > 0, "sync_v5 fast path section not found"

    section = code[start:start + 7000]
    assert "self.client.get_library_hash(" in section
    assert "self.client.get_merkle_root(" not in section


def test_sync_v5_has_metadata_merkle_drilldown_hook():
    """
    TODO target:
    - when root/hash mismatch, client must run metadata Merkle drill-down
      (branch -> leaf -> candidate UUIDs) before full sync.
    """
    code = _read_sync_worker()
    assert "_v5_merkle_metadata_drilldown(" in code


def test_rest_client_exposes_merkle_drilldown_endpoints():
    """
    TODO target:
    RestApiClient must expose dedicated methods for metadata drill-down:
    - get_merkle_branches(...)
    - get_merkle_leaves(...)
    """
    rest_client = _load_rest_client_module()
    client = rest_client.RestApiClient("http://test.local", "token")

    assert hasattr(client, "get_merkle_branches")
    assert hasattr(client, "get_merkle_leaves")


def test_rest_client_merkle_branches_uses_expected_endpoint_shape():
    """
    TODO target:
    branch call must use /sync/v5/merkle/branches with
    library_id + dimension=metadata.
    """
    rest_client = _load_rest_client_module()
    client = rest_client.RestApiClient("http://test.local", "token")

    assert hasattr(client, "get_merkle_branches"), "Missing get_merkle_branches method"

    called = {}

    def fake_get(path, params=None, **kwargs):
        called["path"] = path
        called["params"] = params or {}
        return {"root_hash": "a" * 64, "branch_count": 0, "branches": []}

    client.get = fake_get
    response = client.get_merkle_branches(library_id=12, dimension="metadata")

    assert response is not None
    assert called["path"] == "/sync/v5/merkle/branches"
    assert called["params"]["library_id"] == 12
    assert called["params"]["dimension"] == "metadata"


def test_rest_client_merkle_leaves_uses_expected_endpoint_shape():
    """
    TODO target:
    leaf call must use /sync/v5/merkle/leaves with
    library_id + dimension=metadata + branch_id.
    """
    rest_client = _load_rest_client_module()
    client = rest_client.RestApiClient("http://test.local", "token")

    assert hasattr(client, "get_merkle_leaves"), "Missing get_merkle_leaves method"

    called = {}

    def fake_get(path, params=None, **kwargs):
        called["path"] = path
        called["params"] = params or {}
        return {"branch_id": 3, "leaf_count": 0, "leaves": []}

    client.get = fake_get
    response = client.get_merkle_leaves(library_id=12, dimension="metadata", branch_id=3)

    assert response is not None
    assert called["path"] == "/sync/v5/merkle/leaves"
    assert called["params"]["library_id"] == 12
    assert called["params"]["dimension"] == "metadata"
    assert called["params"]["branch_id"] == 3


def test_todo_sync_v5_has_covers_merkle_drilldown_hook_not_implemented_yet():
    """
    TODO RED TEST (expected to fail now):
    next milestone requires dedicated Merkle drill-down for covers dimension.
    """
    code = _read_sync_worker()
    assert "_v5_merkle_covers_drilldown(" in code


def test_todo_sync_v5_has_files_merkle_drilldown_hook_not_implemented_yet():
    """
    TODO RED TEST (expected to fail now):
    next milestone requires dedicated Merkle drill-down for files dimension.
    """
    code = _read_sync_worker()
    assert "_v5_merkle_files_drilldown(" in code


def test_todo_sync_v5_uses_dimension_specific_merkle_roots_from_preflight():
    """
    TODO RED TEST (expected to fail now):
    plugin should read and compare dedicated roots from preflight payload:
    - metadata_merkle_root
    - covers_merkle_root
    - files_merkle_root
    """
    code = _read_sync_worker()
    assert "metadata_merkle_root" in code
    assert "covers_merkle_root" in code
    assert "files_merkle_root" in code


def test_todo_sync_v5_invokes_covers_merkle_path_when_covers_enabled_and_mismatch():
    """
    TODO RED TEST (expected to fail now):
    when covers sync is enabled and covers hash mismatches, a covers Merkle
    drill-down path should be invoked before broad sync.
    """
    code = _read_sync_worker()
    assert "_v5_merkle_covers_drilldown(" in code
    assert "sync_covers_enabled" in code
    assert "library_covers_hash" in code


def test_todo_sync_v5_invokes_files_merkle_path_when_files_enabled_and_mismatch():
    """
    TODO RED TEST (expected to fail now):
    when files sync is enabled and files hash mismatches, a files Merkle
    drill-down path should be invoked before broad sync.
    """
    code = _read_sync_worker()
    assert "_v5_merkle_files_drilldown(" in code
    assert "sync_files_enabled" in code
    assert "library_files_hash" in code
