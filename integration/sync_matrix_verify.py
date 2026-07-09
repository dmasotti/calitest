"""
Shared assertions for the sync convergence matrix (pytest + future plugin loop).

Loads the exported registry (SyncMatrixSeeder → JSON) and provides PG / API
helpers so Phase 0/7 tests do not duplicate SQL.
"""

from __future__ import annotations

import hashlib
import json
import os
import subprocess
from typing import Any

FIXTURES_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fixtures")
REGISTRY_PATH = os.path.join(FIXTURES_DIR, "sync_matrix_registry.json")

PG_CONTAINER = os.environ.get("SYNC_MATRIX_PG_CONTAINER", "caliweb_test_pg")
PG_DB = os.environ.get("SYNC_MATRIX_PG_DB", "caliweb_test")
PG_USER = os.environ.get("SYNC_MATRIX_PG_USER", "testuser")


def load_registry(path: str = REGISTRY_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def scenario_map(registry: dict[str, Any] | None = None) -> dict[str, str]:
    reg = registry or load_registry()
    return {s["key"]: s["uuid"] for s in reg["scenarios"]}


def scenario_by_key(key: str, registry: dict[str, Any] | None = None) -> dict[str, Any]:
    reg = registry or load_registry()
    for s in reg["scenarios"]:
        if s["key"] == key:
            return s
    raise KeyError(f"scenario key not in registry: {key}")


def psql(sql: str, container: str = PG_CONTAINER, db: str = PG_DB, user: str = PG_USER) -> str:
    return subprocess.run(
        ["docker", "exec", container, "psql", "-U", user, "-d", db, "-tAF\t", "-c", sql],
        capture_output=True,
        text=True,
        check=True,
    ).stdout.strip()


def strip_sha256_prefix(h: str | None) -> str:
    if not h:
        return ""
    return h[7:] if h.startswith("sha256:") else h


def client_file_item_hash(uuid: str, format_: str, tail_hash: str | None) -> str:
    """Per-format files item_hash: SHA256(uuid|FORMAT|tail_hash)."""
    raw = tail_hash or ""
    return hashlib.sha256(f"{uuid}|{format_.upper()}|{raw}".encode()).hexdigest()


def leaf_id(uuid: str) -> int:
    return int(uuid.replace("-", "").lower()[:2], 16)


def assert_book_files_seeded(uuid: str, *, min_rows: int = 1) -> None:
    count = psql(
        f"SELECT count(*) FROM books_files WHERE book = '{uuid}' "
        "AND is_uploaded = 1 AND deleted_at IS NULL"
    )
    assert int(count) >= min_rows, f"book {uuid} expected >= {min_rows} uploaded files, got {count}"


def assert_file_tail_hash(uuid: str, expected_tail: str, *, format_: str = "EPUB") -> None:
    row = psql(
        f"SELECT COALESCE(tail_hash,'') FROM books_files WHERE book = '{uuid}' "
        f"AND format = '{format_}' AND deleted_at IS NULL LIMIT 1"
    )
    assert row == expected_tail, f"book {uuid} tail_hash mismatch: {row!r} != {expected_tail!r}"


def assert_files_leaves_match_raw_client(uuids: list[str]) -> None:
    """Server FILES Merkle leaves == RAW client computation for the given books."""
    if not uuids:
        raise AssertionError("no uuids to check")
    in_list = ",".join(repr(u) for u in uuids)
    rows = psql(
        "SELECT b.uuid, bf.format, COALESCE(bf.tail_hash, '') "
        "FROM books b "
        "INNER JOIN books_files bf ON bf.book = b.uuid "
        "AND bf.deleted_at IS NULL AND bf.is_uploaded = 1 AND bf.tail_hash IS NOT NULL "
        f"WHERE b.uuid IN ({in_list})"
    )
    buckets: dict[int, list[str]] = {}
    for line in rows.splitlines():
        if not line.strip():
            continue
        uuid, fmt, tail = line.split("\t", 2)
        buckets.setdefault(leaf_id(uuid), []).append(
            client_file_item_hash(uuid, fmt, tail or None)
        )

    assert buckets, "no file rows for merkle check"
    for lid, items in buckets.items():
        expected = hashlib.sha256("".join(sorted(items)).encode()).hexdigest()
        server_leaf = psql(
            "SELECT leaf_hash FROM sync_merkle_leaves "
            f"WHERE dimension='files' AND leaf_id={lid}"
        )
        assert server_leaf == expected, (
            f"FILES leaf {lid}: server={server_leaf[:16]}… != raw-client {expected[:16]}…"
        )
