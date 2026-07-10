"""Federation tests: seeder + Flutter + plugin case_id registries stay aligned."""

from __future__ import annotations

import json
import os
from collections import defaultdict

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
MATRIX_JSON = os.path.join(FIXTURES, "sync_matrix_registry.json")
FLUTTER_JSON = os.path.join(FIXTURES, "flutter_v5_case_registry.json")
PLUGIN_JSON = os.path.join(FIXTURES, "plugin_v5_case_registry.json")

# Seeded scenarios that must have BEH + INT/E2E federation (Sprint 5 gate).
P0_REQUIRE_BEH_AND_INT = frozenset(
    {
        "FIL-GHOST-01",
        "MRK-06",
        "H4-COVER",
        "FIL-OK",
        "COV-GHOST-01",
    }
)

# E2E case_ids may inherit BEH from these related matrix rows (shared Flutter tests).
RELATED_BEH: dict[str, list[str]] = {
    "H4-COVER": ["FIL-GHOST-01"],
    "COV-GHOST-01": ["FIL-GHOST-01"],
    "MRK-06": ["FIL-GHOST-01"],
}

# Seeded baselines covered only by server seed + HTTP phases (no Flutter row yet).
SEEDER_ONLY_CASE_IDS = frozenset({"COV-BASE", "COV-NONE", "RLY-META"})

# HTTP/device conductors that count as INT for matrix E2E case_ids.
INT_CONDUCTOR_SOURCES = {
    "COV-BASE": ["test_phase0_seeded_books_match_scenarios"],
    "COV-NONE": ["test_phase0_seeded_books_match_scenarios"],
    "RLY-META": ["test_phase5a_metadata_only_client_keeps_other_clients_covers_and_files"],
    "FIL-GHOST-01": ["test_phase7b_mrk06_two_sync_pulls_file_then_converges"],
    "MRK-06": [
        "test_phase7b_mrk06_two_sync_pulls_file_then_converges",
        "test_phase7c_emulator_mrk06_files_converge",
        "test_phase8_3way_plugin_emulator_mrk06",
        "test_plugin_headless_sync_matrix_mrk06_two_sync",
    ],
    "H4-COVER": ["test_phase1b_emulator_single_device_convergence"],
    "FIL-OK": [
        "test_phase7a_server_files_leaves_match_raw_client",
        "test_phase7d_emulator_filok_epub_bytes_on_disk",
    ],
    "COV-GHOST-01": ["test_phase1b_emulator_single_device_convergence"],
}


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _seeder_case_ids(matrix: dict) -> set[str]:
    ids: set[str] = set()
    for s in matrix["scenarios"]:
        ids.add(s["case_id"])
        ids.update(s.get("case_ids") or [])
    return ids


def _coverage_index() -> dict[str, dict[str, list[str]]]:
    """case_id → {BEH: [...], INT: [...]} source labels."""
    matrix = _load(MATRIX_JSON)
    flutter_list = _load(FLUTTER_JSON)["entries"]
    plugin_list = _load(PLUGIN_JSON)["entries"]

    idx: dict[str, dict[str, list[str]]] = defaultdict(
        lambda: {"BEH": [], "INT": []}
    )

    for s in matrix["scenarios"]:
        for cid in {s["case_id"], *(s.get("case_ids") or [])}:
            idx[cid]["INT"].append(f"seeder:{s['key']}")

    for e in flutter_list:
        cid = e["case_id"]
        for f in e.get("files", []):
            if "integration_test" in f:
                idx[cid]["INT"].append(f"flutter:{f}")
            else:
                idx[cid]["BEH"].append(f"flutter:{f}")
        if e.get("layer") == "BEH" and not idx[cid]["BEH"]:
            idx[cid]["BEH"].append(f"flutter:{cid}")

    for e in plugin_list:
        cid = e["matrix_case_id"]
        bucket = "BEH" if e.get("layer") == "BEH" else "INT"
        idx[cid][bucket].append(f"plugin:{e['plugin_case_id']}")

    for cid, related in RELATED_BEH.items():
        for rel in related:
            idx[cid]["BEH"].extend(idx.get(rel, {}).get("BEH", []))

    for cid, sources in INT_CONDUCTOR_SOURCES.items():
        idx[cid]["INT"].extend(sources)

    return dict(idx)


def test_sync_matrix_registry_has_six_scenarios():
    data = _load(MATRIX_JSON)
    assert len(data["scenarios"]) >= 6


def test_plugin_v5_registry_maps_a01_to_mrk01_and_d01_to_mrk05():
    data = _load(PLUGIN_JSON)
    by_plugin = {e["plugin_case_id"]: e for e in data["entries"]}
    assert by_plugin["A01_meta_match_covers_diverge_calls_cover_drilldown"][
        "matrix_case_id"
    ] == "MRK-01"
    assert (
        by_plugin["D01_covers_drilldown_enqueue_when_batch_missing_zero"][
            "matrix_case_id"
        ]
        == "MRK-05"
    )
    assert by_plugin["headless_sync_matrix_mrk06"]["matrix_case_id"] == "MRK-06"


def test_flutter_v5_registry_covers_mrk06_and_fil_ghost():
    data = _load(FLUTTER_JSON)
    entries = {e["case_id"]: e for e in data["entries"]}
    assert "MRK-06" in entries
    assert entries["MRK-06"].get("scenario") == "mrk06"
    assert "FIL-GHOST-01" in entries
    assert any(
        "sync_v5_file_lww_payload_test.dart" in f
        for f in entries["FIL-GHOST-01"]["files"]
    )


def test_flutter_v5_registry_fil_ok_has_filok_scenario():
    data = _load(FLUTTER_JSON)
    entries = {e["case_id"]: e for e in data["entries"]}
    assert "FIL-OK" in entries
    assert entries["FIL-OK"].get("scenario") == "filok"
    assert "web_sync_service_v5_test.dart" in " ".join(entries["FIL-OK"]["files"])


def test_flutter_v5_web_sync_beh_coverage_count():
    """Sprint 4: 48 BEH tests federated in v5_web_sync_test_case_ids.dart."""
    data = _load(FLUTTER_JSON)
    beh_files = {
        f for e in data["entries"] if e.get("layer") == "BEH" for f in e.get("files", [])
    }
    assert "test/sync/web_sync_service_v5_test.dart" in beh_files


def test_matrix_fil_ghost_uuid_in_seeder_registry():
    data = _load(MATRIX_JSON)
    prefixed = next(s for s in data["scenarios"] if s["key"] == "cover_prefixed")
    assert "FIL-GHOST-01" in prefixed.get("case_ids", [])
    assert prefixed["uuid"] == "1bed2112-83be-4979-8e26-0e901b0b1eb1"
    assert prefixed.get("files")


def test_seeder_case_ids_appear_in_flutter_or_plugin_registry():
    """Every seeded case_id must be federated in Flutter or plugin registry."""
    matrix = _load(MATRIX_JSON)
    flutter_ids = {e["case_id"] for e in _load(FLUTTER_JSON)["entries"]}
    plugin_ids = {e["matrix_case_id"] for e in _load(PLUGIN_JSON)["entries"]}
    missing = []
    for cid in sorted(_seeder_case_ids(matrix)):
        if cid in SEEDER_ONLY_CASE_IDS:
            continue
        if cid not in flutter_ids and cid not in plugin_ids:
            missing.append(cid)
    assert not missing, f"unfederated seeder case_ids: {missing}"


def test_p0_case_ids_have_beh_and_int_coverage():
    """Sprint 5: P0 matrix rows need ≥1 BEH and ≥1 INT/E2E source."""
    idx = _coverage_index()
    gaps = []
    for cid in sorted(P0_REQUIRE_BEH_AND_INT):
        beh = idx.get(cid, {}).get("BEH", [])
        int_ = idx.get(cid, {}).get("INT", [])
        if not beh:
            gaps.append(f"{cid}: missing BEH")
        if not int_:
            gaps.append(f"{cid}: missing INT/E2E")
    assert not gaps, "\n".join(gaps)


def test_mrk05_has_plugin_beh_rows():
    """MRK-05 closure gap — plugin D* matrix (BEH only until server INT lands)."""
    data = _load(PLUGIN_JSON)
    mrk05 = [e for e in data["entries"] if e["matrix_case_id"] == "MRK-05"]
    assert len(mrk05) >= 5
