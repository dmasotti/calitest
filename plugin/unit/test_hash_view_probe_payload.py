from __future__ import absolute_import, division, print_function, unicode_literals

import importlib.util
from pathlib import Path


def _load_local_hash_view_case():
    integration_path = (
        Path(__file__).resolve().parents[1] / "integration" / "test_hash_view_cross_engine_e2e.py"
    )
    spec = importlib.util.spec_from_file_location("local_hash_view_cross_engine_e2e", str(integration_path))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    case_cls = module.HashViewCrossEngineE2E
    case_cls.__test__ = False
    return case_cls


def test_targeted_hash_probe_payload_includes_metadata_candidate_uuids():
    case_cls = _load_local_hash_view_case()
    case = case_cls()
    case.library_id = "2"
    case.library_uuid = "lib-uuid"

    chunk = ["u1", "u2"]
    payload = case._build_targeted_hash_probe_payload(
        chunk=chunk,
        client_books={"u1": {"m": "__probe__", "c": None, "f": None}},
        cursor="123:9",
    )

    assert payload["library_id"] == "2"
    assert payload["calibre_library_uuid"] == "lib-uuid"
    assert payload["cursor"] == "123:9"
    assert payload["options"]["metadata_candidate_uuids"] == chunk
    assert payload["options"]["sync_files_enabled"] is False
    assert payload["options"]["sync_covers_enabled"] is False
