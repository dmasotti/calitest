"""Tests for stable-bucket Merkle hash VIEWs in plugin SQLite schema."""
import os
import sqlite3
import time
from pathlib import Path
import importlib.util

import pytest


plugin_path = Path(__file__).parent.parent.parent.parent / "sync_calimob"

spec = importlib.util.spec_from_file_location(
    "mapping_table", str(plugin_path / "mapping_table.py")
)
mapping_table = importlib.util.module_from_spec(spec)
spec.loader.exec_module(mapping_table)


def _create_calibre_schema(conn):
    cursor = conn.cursor()
    cursor.execute(
        """
        CREATE TABLE books (
            id INTEGER PRIMARY KEY,
            uuid TEXT,
            title TEXT,
            author_sort TEXT,
            series_index REAL DEFAULT 1.0,
            pubdate TEXT,
            timestamp TEXT
        )
        """
    )
    cursor.execute("CREATE TABLE authors (id INTEGER PRIMARY KEY, name TEXT)")
    cursor.execute("CREATE TABLE books_authors_link (book INTEGER, author INTEGER)")
    cursor.execute("CREATE TABLE series (id INTEGER PRIMARY KEY, name TEXT)")
    cursor.execute("CREATE TABLE books_series_link (book INTEGER, series INTEGER)")
    cursor.execute("CREATE TABLE tags (id INTEGER PRIMARY KEY, name TEXT)")
    cursor.execute("CREATE TABLE books_tags_link (book INTEGER, tag INTEGER)")
    cursor.execute("CREATE TABLE identifiers (book INTEGER, type TEXT, val TEXT)")
    cursor.execute("CREATE TABLE publishers (id INTEGER PRIMARY KEY, name TEXT)")
    cursor.execute("CREATE TABLE books_publishers_link (book INTEGER, publisher INTEGER)")
    cursor.execute("CREATE TABLE languages (id INTEGER PRIMARY KEY, lang_code TEXT)")
    cursor.execute("CREATE TABLE books_languages_link (book INTEGER, lang_code INTEGER)")
    cursor.execute("CREATE TABLE ratings (id INTEGER PRIMARY KEY, rating INTEGER)")
    cursor.execute("CREATE TABLE books_ratings_link (book INTEGER, rating INTEGER)")
    cursor.execute("CREATE TABLE comments (book INTEGER, text TEXT)")
    conn.commit()


def _seed_books(conn, count):
    cursor = conn.cursor()
    for i in range(1, count + 1):
        # Deterministic UUID-like value with spread over prefixes.
        prefix = f"{i % 256:02x}"
        uuid = f"{prefix}{i:06x}-aaaa-bbbb-cccc-{i:012x}"[-36:]
        cursor.execute(
            """
            INSERT INTO books (id, uuid, title, author_sort, series_index, pubdate)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (i, uuid, f"Book {i}", f"Author, {i}", float((i % 10) + 1), "2026-01-01"),
        )
    conn.commit()


def _leaf_hashes(conn):
    rows = conn.execute(
        "SELECT leaf_id, leaf_hash FROM calimob_merkle_leaves_v1 ORDER BY leaf_id"
    ).fetchall()
    return {row[0]: row[1] for row in rows}


def test_merkle_views_are_created(tmp_path):
    db_path = tmp_path / "metadata.db"
    conn = sqlite3.connect(str(db_path))
    _create_calibre_schema(conn)
    _seed_books(conn, 50)

    mapping_table._ensure_table(conn)

    views = {
        row[0]
        for row in conn.execute("SELECT name FROM sqlite_master WHERE type='view'").fetchall()
    }
    assert "calimob_merkle_leaves_v1" in views
    assert "calimob_merkle_branches_v1" in views
    assert "calimob_merkle_root_v1" in views

    root = conn.execute(
        "SELECT root_hash, total_books FROM calimob_merkle_root_v1"
    ).fetchone()
    assert root is not None
    assert root[0] and len(root[0]) == 64
    assert int(root[1]) == 50
    conn.close()


def test_merkle_stable_buckets_do_not_shift_on_insert(tmp_path):
    db_path = tmp_path / "metadata.db"
    conn = sqlite3.connect(str(db_path))
    _create_calibre_schema(conn)
    _seed_books(conn, 200)
    mapping_table._ensure_table(conn)

    before = _leaf_hashes(conn)

    # Insert a new book in an existing stable leaf bucket "aa".
    conn.execute(
        """
        INSERT INTO books (id, uuid, title, author_sort, series_index, pubdate)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (9999, "aa000001-aaaa-bbbb-cccc-000000000001", "Inserted", "Author, Inserted", 1.0, "2026-01-02"),
    )
    conn.commit()

    after = _leaf_hashes(conn)
    changed = {leaf for leaf in set(before) | set(after) if before.get(leaf) != after.get(leaf)}

    # Stable bucketing should localize changes to a single leaf.
    assert len(changed) <= 1
    conn.close()


@pytest.mark.skipif(
    os.getenv("CALIMOB_PLUGIN_PERF_TESTS", "0") not in ("1", "true", "yes"),
    reason="Set CALIMOB_PLUGIN_PERF_TESTS=1 to run plugin Merkle performance tests.",
)
def test_merkle_view_performance_smoke(tmp_path):
    db_path = tmp_path / "metadata.db"
    conn = sqlite3.connect(str(db_path))
    _create_calibre_schema(conn)

    books = max(5000, int(os.getenv("CALIMOB_PLUGIN_PERF_BOOKS", "10000")))
    iterations = max(1, int(os.getenv("CALIMOB_PLUGIN_PERF_ITERATIONS", "5")))
    budget_root_p95_ms = float(os.getenv("CALIMOB_PLUGIN_PERF_MERKLE_ROOT_P95_MS", "500"))
    budget_branch_p95_ms = float(os.getenv("CALIMOB_PLUGIN_PERF_MERKLE_BRANCH_P95_MS", "1000"))

    _seed_books(conn, books)
    mapping_table._ensure_table(conn)

    root_times = []
    branch_times = []
    for _ in range(iterations):
        t0 = time.perf_counter()
        root = conn.execute("SELECT root_hash, total_books FROM calimob_merkle_root_v1").fetchone()
        root_times.append((time.perf_counter() - t0) * 1000.0)
        assert root and root[0]

        t1 = time.perf_counter()
        branches = conn.execute(
            "SELECT branch_id, branch_hash, book_count FROM calimob_merkle_branches_v1 ORDER BY branch_id"
        ).fetchall()
        branch_times.append((time.perf_counter() - t1) * 1000.0)
        assert len(branches) > 0

    def _p95(values):
        vals = sorted(values)
        idx = int(round((len(vals) - 1) * 0.95))
        return vals[idx]

    root_p95 = _p95(root_times)
    branch_p95 = _p95(branch_times)

    assert root_p95 <= budget_root_p95_ms
    assert branch_p95 <= budget_branch_p95_ms
    conn.close()
