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
DEFAULT_MATRIX_LIBRARY_UUID = "42a0c170-23cf-11f1-93ec-391510e4e1b1"


def load_registry(path: str = REGISTRY_PATH) -> dict[str, Any]:
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def scenario_map(registry: dict[str, Any] | None = None) -> dict[str, str]:
    reg = registry or load_registry()
    return {s["key"]: s["uuid"] for s in reg["scenarios"]}


def library_id_for_calibre_uuid(calibre_library_uuid: str) -> int:
    row = psql(
        "SELECT id FROM libraries "
        f"WHERE calibre_library_id = '{calibre_library_uuid}' LIMIT 1"
    )
    assert row, f"library not found: {calibre_library_uuid}"
    return int(row)


def merkle_leaf_hash(
    dimension: str,
    leaf_id: int,
    *,
    calibre_library_uuid: str = DEFAULT_MATRIX_LIBRARY_UUID,
) -> str:
    """Single leaf hash for one library (avoids cross-library collisions after Phase 9)."""
    lib_id = library_id_for_calibre_uuid(calibre_library_uuid)
    return psql(
        "SELECT leaf_hash FROM sync_merkle_leaves "
        f"WHERE dimension='{dimension}' AND leaf_id={leaf_id} "
        f"AND library_id={lib_id} LIMIT 1"
    )


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


def client_cover_item_hash(
    uuid: str,
    has_cover: bool,
    cover_hash: str | None,
    *,
    cover_url: str | None = None,
    cover_optimized_path: str | None = None,
) -> str:
    """Per-book cover item_hash a RAW client sends.

    Mirrors MaterializedMerkleService covers SQL: when cover_url AND
    cover_optimized_path are both NULL the server zeros the hash in the leaf
    (orphan cover — bytes absent on storage).
    """
    hc = "1" if has_cover else "0"
    if cover_url is None and cover_optimized_path is None:
        raw = ""
    else:
        raw = strip_sha256_prefix(cover_hash)
    return hashlib.sha256(f"{uuid}|{hc}|{raw}".encode()).hexdigest()


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


def assert_files_leaves_match_raw_client(
    uuids: list[str],
    *,
    calibre_library_uuid: str = DEFAULT_MATRIX_LIBRARY_UUID,
) -> None:
    """Server FILES Merkle leaves == RAW client computation for the given books."""
    if not uuids:
        raise AssertionError("no uuids to check")
    lib_id = library_id_for_calibre_uuid(calibre_library_uuid)
    in_list = ",".join(repr(u) for u in uuids)
    rows = psql(
        "SELECT b.uuid, bf.format, COALESCE(bf.tail_hash, '') "
        "FROM books b "
        "INNER JOIN books_files bf ON bf.book = b.uuid "
        "AND bf.deleted_at IS NULL AND bf.is_uploaded = 1 AND bf.tail_hash IS NOT NULL "
        f"WHERE b.library_id = {lib_id} AND b.uuid IN ({in_list})"
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
        server_leaf = merkle_leaf_hash("files", lid, calibre_library_uuid=calibre_library_uuid)
        assert server_leaf == expected, (
            f"FILES leaf {lid}: server={server_leaf[:16]}… != raw-client {expected[:16]}…"
        )


def sample_large_pool_uuids(uuids: list[str], *, max_samples: int = 32) -> list[str]:
    """Deterministic spread across a large pool (stress tiers skip full-leaf walks)."""
    if not uuids:
        return []
    if len(uuids) <= max_samples:
        return list(uuids)
    n = len(uuids)
    indices = {0, n // 4, n // 2, (3 * n) // 4, n - 1}
    step = max(1, n // max(1, max_samples - len(indices)))
    for i in range(0, n, step):
        indices.add(i)
        if len(indices) >= max_samples:
            break
    return [uuids[i] for i in sorted(indices)[:max_samples]]


def assert_metadata_hashes_present(
    uuids: list[str],
    *,
    calibre_library_uuid: str = DEFAULT_MATRIX_LIBRARY_UUID,
) -> None:
    """Each uuid has a non-empty books_hash_v2.metadata_hash (sampled stress check)."""
    if not uuids:
        raise AssertionError("no uuids to check")
    lib_id = library_id_for_calibre_uuid(calibre_library_uuid)
    in_list = ",".join(repr(u) for u in uuids)
    rows = psql(
        "SELECT b.uuid, COALESCE(h.metadata_hash,'') FROM books b "
        "LEFT JOIN books_hash_v2 h ON h.uuid = b.uuid AND h.library_id = b.library_id "
        f"AND h.user_id = b.user_id "
        f"WHERE b.library_id = {lib_id} AND b.uuid IN ({in_list}) "
        "AND b.deleted_at IS NULL"
    )
    by_uuid: dict[str, str] = {}
    for line in rows.splitlines():
        if not line.strip():
            continue
        uuid, meta_hash = line.split("\t", 1)
        by_uuid[uuid] = meta_hash.strip()

    missing = [u for u in uuids if u not in by_uuid]
    empty = [u for u in uuids if not by_uuid.get(u)]
    assert not missing, f"sample uuids not in DB: {missing[:5]}"
    assert not empty, f"sample uuids missing metadata_hash: {empty[:5]}"


def assert_sampled_metadata_leaves_match_server_view(
    sample_uuids: list[str],
    *,
    calibre_library_uuid: str = DEFAULT_MATRIX_LIBRARY_UUID,
) -> None:
    """For each Merkle leaf touched by sample_uuids, verify the FULL leaf bucket."""
    if not sample_uuids:
        raise AssertionError("no uuids to check")
    lib_id = library_id_for_calibre_uuid(calibre_library_uuid)
    for lid in sorted({leaf_id(u) for u in sample_uuids}):
        prefix = f"{lid:02x}"
        rows = psql(
            "SELECT b.uuid, h.metadata_hash FROM books b "
            "JOIN books_hash_v2 h ON h.uuid = b.uuid AND h.library_id = b.library_id "
            f"AND h.user_id = b.user_id "
            f"WHERE b.library_id = {lib_id} AND b.deleted_at IS NULL "
            f"AND LOWER(REPLACE(b.uuid::text, '-', '')) LIKE '{prefix}%' "
            "AND h.metadata_hash IS NOT NULL AND TRIM(h.metadata_hash) <> ''"
        )
        items: list[str] = []
        for line in rows.splitlines():
            if not line.strip():
                continue
            _, meta_hash = line.split("\t", 1)
            items.append(meta_hash)
        assert items, f"no metadata hashes for leaf {lid}"
        expected = hashlib.sha256("".join(sorted(items)).encode()).hexdigest()
        server_leaf = merkle_leaf_hash("metadata", lid, calibre_library_uuid=calibre_library_uuid)
        assert server_leaf == expected, (
            f"METADATA leaf {lid}: server={server_leaf[:16]}… != view {expected[:16]}…"
        )


def assert_metadata_leaves_match_server_view(
    uuids: list[str],
    *,
    calibre_library_uuid: str = DEFAULT_MATRIX_LIBRARY_UUID,
) -> None:
    """Server METADATA Merkle leaves == aggregation of books_hash_v2 per leaf bucket."""
    if not uuids:
        raise AssertionError("no uuids to check")
    lib_id = library_id_for_calibre_uuid(calibre_library_uuid)
    in_list = ",".join(repr(u) for u in uuids)
    rows = psql(
        "SELECT b.uuid, h.metadata_hash FROM books b "
        "JOIN books_hash_v2 h ON h.uuid = b.uuid AND h.library_id = b.library_id "
        f"AND h.user_id = b.user_id "
        f"WHERE b.library_id = {lib_id} AND b.uuid IN ({in_list}) "
        "AND h.metadata_hash IS NOT NULL AND TRIM(h.metadata_hash) <> ''"
    )
    buckets: dict[int, list[str]] = {}
    for line in rows.splitlines():
        if not line.strip():
            continue
        uuid, meta_hash = line.split("\t", 1)
        buckets.setdefault(leaf_id(uuid), []).append(meta_hash)

    assert buckets, "no metadata hashes for merkle check"
    for lid, items in buckets.items():
        expected = hashlib.sha256("".join(sorted(items)).encode()).hexdigest()
        server_leaf = merkle_leaf_hash("metadata", lid, calibre_library_uuid=calibre_library_uuid)
        assert server_leaf == expected, (
            f"METADATA leaf {lid}: server={server_leaf[:16]}… != view {expected[:16]}…"
        )
