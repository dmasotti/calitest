from __future__ import absolute_import, division, print_function, unicode_literals

from tests.plugin.integration.test_hash_view_cross_engine_e2e import HashViewCrossEngineE2E


def test_targeted_hash_probe_payload_includes_metadata_candidate_uuids():
    case = HashViewCrossEngineE2E()
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
