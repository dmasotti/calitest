"""Federation tests: seeder registry + Flutter v5 case_id registry stay aligned."""

from __future__ import annotations

import json
import os

import pytest

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")
MATRIX_JSON = os.path.join(FIXTURES, "sync_matrix_registry.json")
FLUTTER_JSON = os.path.join(FIXTURES, "flutter_v5_case_registry.json")


def _load(path: str) -> dict:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def test_sync_matrix_registry_has_six_scenarios():
  data = _load(MATRIX_JSON)
  assert len(data["scenarios"]) >= 6


def test_flutter_v5_registry_covers_mrk06_and_fil_ghost():
  data = _load(FLUTTER_JSON)
  entries = {e["case_id"]: e for e in data["entries"]}
  assert "MRK-06" in entries
  assert entries["MRK-06"].get("scenario") == "mrk06"
  assert "FIL-GHOST-01" in entries
  assert any(
      "sync_v5_file_lww_payload_test.dart" in f for f in entries["FIL-GHOST-01"]["files"]
  )


def test_matrix_fil_ghost_uuid_in_seeder_registry():
  data = _load(MATRIX_JSON)
  prefixed = next(s for s in data["scenarios"] if s["key"] == "cover_prefixed")
  assert "FIL-GHOST-01" in prefixed.get("case_ids", [])
  assert prefixed["uuid"] == "1bed2112-83be-4979-8e26-0e901b0b1eb1"
  assert prefixed.get("files")
