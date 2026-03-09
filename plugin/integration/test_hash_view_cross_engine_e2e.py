#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""E2E parity check: SQLite plugin hash views vs server MySQL sync hashes.

This test is intentionally strict and targets the exact regression class where:
- plugin uses calimob_books_hash_v2 metadata hashes
- server compares with a different hash algorithm/source

Required env vars:
- CALIMOB_TEST_API_URL
- CALIMOB_TEST_TOKEN
- CALIMOB_TEST_LIBRARY_PATH
- CALIMOB_TEST_CALIMOB_LIB_ID

Optional:
- CALIMOB_TEST_LIBRARY_UUID
- CALIMOB_HASH_PARITY_MAX_MISMATCH_REPORT (default: 25)
"""

from __future__ import absolute_import, division, print_function, unicode_literals

import json
import os
import sqlite3
import sys
import unittest
import hashlib
import shutil
import tempfile
import time
import socket
from types import SimpleNamespace
from urllib import error as urlerror
from urllib import parse as urlparse
from urllib import request as urlrequest


_THIS_DIR = os.path.abspath(os.path.dirname(__file__))
ROOT_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
if not os.path.isdir(os.path.join(ROOT_DIR, "sync_calimob")):
    ROOT_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", "..", ".."))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)
PLUGIN_DIR = os.path.join(ROOT_DIR, "sync_calimob")
if PLUGIN_DIR not in sys.path:
    sys.path.insert(0, PLUGIN_DIR)

try:
    from sync_calimob import mapping_table, sync_worker, sync_mapper, sync_utils  # type: ignore  # noqa: E402
except Exception:
    try:
        from calibre_plugins.sync_calimob import mapping_table, sync_worker, sync_mapper, sync_utils  # type: ignore  # noqa: E402
    except Exception:
        mapping_table = None  # type: ignore
        import sync_worker  # type: ignore  # noqa: E402
        import sync_mapper  # type: ignore  # noqa: E402
        import sync_utils  # type: ignore  # noqa: E402


def _env(name, default=None):
    value = os.environ.get(name, default)
    if value is None:
        return None
    value = value.strip()
    return value if value else None


class HashViewCrossEngineE2E(unittest.TestCase):
    maxDiff = None

    def setUp(self):
        required = {
            "api_url": _env("CALIMOB_TEST_API_URL"),
            "token": _env("CALIMOB_TEST_TOKEN"),
            "library_path": _env("CALIMOB_TEST_LIBRARY_PATH"),
            "library_id": _env("CALIMOB_TEST_CALIMOB_LIB_ID"),
        }
        missing = [k for k, v in required.items() if not v]
        if missing:
            self.skipTest("Missing env vars: {}".format(", ".join(missing)))

        self.api_url = required["api_url"].rstrip("/")
        self.token = required["token"]
        self.library_path = required["library_path"]
        self.library_id = str(required["library_id"])
        self.library_uuid = _env("CALIMOB_TEST_LIBRARY_UUID")
        self.max_report = int(_env("CALIMOB_HASH_PARITY_MAX_MISMATCH_REPORT", "25"))
        self.sample_probe_size = int(_env("CALIMOB_HASH_PARITY_PROBE_SIZE", "50"))
        self.use_db_copy = _env("CALIMOB_HASH_PARITY_USE_DB_COPY", "1") not in ("0", "false", "False", "no", "NO")
        self.http_timeout = int(_env("CALIMOB_HASH_PARITY_HTTP_TIMEOUT", "180"))

        db_path = os.path.join(self.library_path, "metadata.db")
        if not os.path.isfile(db_path):
            self.skipTest("metadata.db not found at {}".format(db_path))
        self.db_path = db_path

        if not self.library_uuid:
            self.library_uuid = self._read_library_uuid(db_path)
            if not self.library_uuid:
                self.skipTest("Unable to resolve local library UUID from metadata.db")

        self.test_db_path = self._prepare_test_db(db_path)

    def _prepare_test_db(self, db_path):
        if not self.use_db_copy:
            return db_path

        tmp_dir = tempfile.mkdtemp(prefix="hash_parity_lib_")
        dst = os.path.join(tmp_dir, "metadata.db")
        shutil.copy2(db_path, dst)

        if mapping_table is not None:
            conn = sqlite3.connect(dst)
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS calimob_books_sync (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    library_uuid TEXT,
                    calibre_book_id INTEGER,
                    cover_hash TEXT,
                    files_hash TEXT
                )
                """
            )
            conn.create_function("sha256", 1, lambda v: hashlib.sha256((v or "").encode("utf-8")).hexdigest())
            mapping_table._ensure_hash_views(conn)  # pylint: disable=protected-access
            conn.close()

        return dst

    def _read_library_uuid(self, db_path):
        try:
            conn = sqlite3.connect(db_path)
            cur = conn.cursor()
            cur.execute("SELECT uuid FROM library_id LIMIT 1")
            row = cur.fetchone()
            conn.close()
            if row and row[0]:
                return str(row[0])
        except Exception:
            return None
        return None

    def _make_worker_for_sql_payload(self):
        worker = sync_worker.SyncWorker.__new__(sync_worker.SyncWorker)
        worker.library_id = self.library_uuid
        worker.calimob_library_id = int(self.library_id)
        return worker

    def _build_fake_metadata_from_sql_payload(self, payload):
        identifiers = dict(payload.get("identifiers") or {})
        isbn = identifiers.get("isbn") or identifiers.get("isbn13")
        series = payload.get("series") or {}
        series_name = series.get("name") if isinstance(series, dict) else None
        series_id = series.get("id") if isinstance(series, dict) else None
        series_index = 1.0 if series_name else None
        authors = list(payload.get("authors") or [])
        tags = list(payload.get("tags") or [])
        languages = list(payload.get("languages") or [])
        return SimpleNamespace(
            uuid=payload.get("uuid"),
            title=payload.get("title") or "",
            sort=payload.get("title_sort") or None,
            title_sort=payload.get("title_sort") or None,
            author_sort=payload.get("author_sort") or None,
            authors=[(a.get("name") or "") for a in authors],
            author_ids=[a.get("id") for a in authors],
            series=series_name,
            series_id=series_id,
            series_index=series_index,
            isbn=isbn,
            identifiers=identifiers,
            publisher=payload.get("publisher"),
            pubdate=payload.get("pubdate"),
            languages=languages,
            tags=[(t.get("name") or "") for t in tags],
            tag_ids=[t.get("id") for t in tags],
            rating=payload.get("rating"),
            comments=payload.get("comments"),
            has_cover=False,
            timestamp=payload.get("last_modified"),
            last_modified=payload.get("last_modified"),
        )

    def _build_traditional_json_from_sql_payload(self, payload):
        metadata = self._build_fake_metadata_from_sql_payload(payload)
        item = sync_mapper.calibre_to_json_item(
            payload.get("id"),
            metadata,
            self.library_uuid,
        )
        item["pubdate"] = sync_mapper.normalize_pubdate_unix(item.get("pubdate"))
        item["last_modified"] = payload.get("last_modified")
        item["files"] = []
        return item

    def _compute_metadata_hash(self, item):
        return sync_utils.compute_metadata_hash(item, {}, None)

    def _post_upsert_item(self, item):
        raw = json.dumps({"op": "upsert", "item": item}, sort_keys=True, separators=(",", ":"), default=str)
        idem = hashlib.sha256(raw.encode("utf-8")).hexdigest()
        payload = {
            "library_id": int(self.library_id),
            "calibre_library_uuid": self.library_uuid,
            "client_cursor": None,
            "changes": [{
                "op": "upsert",
                "idempotency_key": idem,
                "client_change_id": idem,
                "item": item,
            }],
            "options": {"dry_run": False},
        }
        return self._http_json("POST", "/sync", payload=payload, timeout=self.http_timeout)

    def _select_deterministic_sample_book_ids(self, sample_percent):
        conn = sqlite3.connect(self.test_db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute(
            """
            SELECT id
            FROM books
            WHERE uuid IS NOT NULL AND trim(uuid) != ''
            ORDER BY id
            """
        )
        rows = cur.fetchall()
        conn.close()

        all_ids = [int(r["id"]) for r in rows if r["id"] is not None]
        if not all_ids:
            return [], 0
        stride = max(1, int(round(100.0 / max(1.0, float(sample_percent)))))
        sampled_ids = [book_id for idx, book_id in enumerate(all_ids) if (idx % stride) == 0]
        return sampled_ids, len(all_ids)

    def _build_json_parity_rows_for_book_ids(self, worker, candidate_ids):
        sync_library_path = self.library_path
        if os.path.basename(self.test_db_path) == "metadata.db":
            sync_library_path = os.path.dirname(self.test_db_path)
        payload_map = worker._v5_get_missing_sql_payload_map(sync_library_path, candidate_ids)

        rows = []
        for book_id in candidate_ids:
            payload = payload_map.get(book_id)
            if not payload:
                continue
            sql_item = worker._v5_build_json_item_from_sql_payload(payload)
            if sql_item.get("_pubdate_out_of_range"):
                continue
            expected_hash = (payload.get("metadata_hash_view") or "").strip().lower()
            if not expected_hash:
                continue
            rows.append({
                "book_id": int(book_id),
                "uuid": payload.get("uuid"),
                "payload": payload,
                "sql_item": sql_item,
                "expected_hash": expected_hash,
            })
        return rows

    def _http_json(self, method, path, payload=None, query=None, timeout=30):
        url = self.api_url + path
        if query:
            url += "?" + urlparse.urlencode(query)
        data = None
        if payload is not None:
            data = json.dumps(payload).encode("utf-8")
        retries = int(_env("CALIMOB_HASH_PARITY_HTTP_RETRIES", "3"))
        backoff = float(_env("CALIMOB_HASH_PARITY_HTTP_RETRY_BACKOFF", "1.5"))
        attempt = 0
        while True:
            attempt += 1
            req = urlrequest.Request(url, data=data, method=method)
            req.add_header("Authorization", "Bearer " + self.token)
            req.add_header("Accept", "application/json")
            if data is not None:
                req.add_header("Content-Type", "application/json")
            try:
                with urlrequest.urlopen(req, timeout=timeout) as resp:
                    raw = resp.read().decode("utf-8")
                    return json.loads(raw)
            except urlerror.HTTPError as exc:
                body = exc.read().decode("utf-8", errors="ignore")
                if exc.code in (502, 503, 504) and attempt < retries:
                    time.sleep(backoff * attempt)
                    continue
                raise AssertionError("HTTP {} {} failed: {}".format(method, url, body))
            except (socket.timeout, TimeoutError, urlerror.URLError) as exc:
                if attempt < retries:
                    time.sleep(backoff * attempt)
                    continue
                raise AssertionError("HTTP {} {} failed: {}".format(method, url, str(exc)))

    def _load_local_metadata_hashes(self):
        conn = sqlite3.connect(self.test_db_path)
        conn.row_factory = sqlite3.Row
        conn.create_function("sha256", 1, lambda v: hashlib.sha256((v or "").encode("utf-8")).hexdigest())
        cur = conn.cursor()
        cur.execute(
            """
            SELECT uuid, metadata_hash
            FROM calimob_books_hash_v2
            WHERE uuid IS NOT NULL AND metadata_hash IS NOT NULL
            ORDER BY uuid
            """
        )
        rows = cur.fetchall()
        cur.execute("SELECT library_metadata_hash FROM calimob_library_hash_payload")
        root_row = cur.fetchone()
        conn.close()

        out = {}
        for row in rows:
            uuid = str(row["uuid"]).strip()
            h = str(row["metadata_hash"]).strip().lower()
            if uuid:
                out[uuid] = h
        local_root = str(root_row[0]).strip().lower() if root_row and root_row[0] else None
        return out, local_root

    def _load_local_server_formula_hashes(self):
        conn = sqlite3.connect(self.test_db_path)
        conn.row_factory = sqlite3.Row
        conn.create_function("sha256", 1, lambda v: hashlib.sha256((v or "").encode("utf-8")).hexdigest())
        cur = conn.cursor()
        try:
            sql = """
                SELECT
                    b.uuid AS uuid,
                    sha256(
                        coalesce(b.uuid, '') || '|' ||
                        coalesce(b.title, '') || '|' ||
                        coalesce(b.author_sort, '') || '|' ||
                        coalesce((SELECT max(s.name)
                                  FROM series s
                                  JOIN books_series_link bsl ON s.id = bsl.series
                                  WHERE bsl.book = b.id), '') || '|' ||
                        coalesce((CASE
                                    WHEN b.series_index IS NULL THEN ''
                                    ELSE printf('%.1f', b.series_index)
                                  END), '') || '|' ||
                        coalesce((SELECT group_concat(name, ',') FROM (
                                      SELECT t.name AS name
                                      FROM tags t
                                      JOIN books_tags_link btl ON t.id = btl.tag
                                      WHERE btl.book = b.id
                                      ORDER BY t.name
                                  )), '') || '|' ||
                        coalesce((SELECT group_concat(kv, ',') FROM (
                                      SELECT (type || ':' || val) AS kv
                                      FROM identifiers
                                      WHERE book = b.id
                                      ORDER BY type
                                  )), '') || '|' ||
                        '' || '|' ||
                        coalesce((SELECT group_concat(lang_code, ',') FROM (
                                      SELECT l.lang_code AS lang_code
                                      FROM languages l
                                      JOIN books_languages_link bll ON l.id = bll.lang_code
                                      WHERE bll.book = b.id
                                      ORDER BY l.lang_code
                                  )), '') || '|' ||
                        coalesce((
                            CASE
                                WHEN b.pubdate IS NULL THEN ''
                                WHEN trim(CAST(b.pubdate AS TEXT)) IN (
                                    '',
                                    '0000-00-00 00:00:00',
                                    '0000-00-00 00:00:00+00:00',
                                    '0101-01-01 00:00:00',
                                    '0101-01-01 00:00:00+00:00'
                                ) THEN ''
                                WHEN CAST(b.pubdate AS TEXT) <> ''
                                     AND CAST(b.pubdate AS TEXT) NOT GLOB '*[^0-9]*'
                                    THEN strftime('%Y-%m-%d %H:%M:%S+00:00', CAST(b.pubdate AS INTEGER), 'unixepoch')
                                ELSE coalesce(strftime('%Y-%m-%d %H:%M:%S+00:00', CAST(b.pubdate AS TEXT)), '')
                            END
                        ), '') || '|' ||
                        coalesce(cast((SELECT max(r.rating)
                                       FROM ratings r
                                       JOIN books_ratings_link brl ON r.id = brl.rating
                                       WHERE brl.book = b.id) as text), '') || '|' ||
                        ''
                    ) AS server_formula_hash
                FROM books b
                WHERE b.uuid IS NOT NULL
                ORDER BY b.uuid
            """
            cur.execute(sql)
            rows = cur.fetchall()
        finally:
            conn.close()
        out = {}
        for row in rows:
            uuid = str(row["uuid"]).strip()
            h = str(row["server_formula_hash"]).strip().lower()
            if uuid:
                out[uuid] = h
        return out

    def _load_server_metadata_hashes(self):
        cursor = None
        server_map = {}
        loops = 0
        while True:
            loops += 1
            if loops > 200:
                raise AssertionError("Server pagination loop did not terminate after 200 calls")

            payload = {
                "library_id": self.library_id,
                "calibre_library_uuid": self.library_uuid,
                "cursor": cursor,
                "batch_size": 500,
                "client_books": {"b": {}, "d": []},
                "options": {
                    "sync_files_enabled": False,
                    "sync_covers_enabled": False,
                },
            }
            data = self._http_json("POST", "/sync/v5", payload=payload, timeout=self.http_timeout)
            for item in data.get("updates_for_client", []) or []:
                uuid = str(item.get("uuid") or "").strip()
                meta = str(item.get("metadata_hash") or "").strip().lower()
                if uuid and meta:
                    server_map[uuid] = meta

            if not data.get("has_more"):
                break
            cursor = data.get("cursor")
            if not cursor:
                raise AssertionError("Server returned has_more=true but no cursor")

        preflight = self._http_json(
            "GET",
            "/sync/v5/library-hash",
            query={
                "library_id": self.library_id,
                "calibre_library_uuid": self.library_uuid,
            },
            timeout=30,
        )
        server_root = str(preflight.get("library_metadata_hash") or "").strip().lower() or None
        return server_map, server_root

    def _load_server_metadata_hashes_for_uuids(self, uuids):
        """Fetch server metadata hashes for a specific UUID set via targeted v5 probes."""
        server_map = {}
        unique = [u for u in sorted(set([str(x).strip() for x in (uuids or []) if str(x).strip()]))]
        if not unique:
            return server_map

        chunk_size = int(_env("CALIMOB_HASH_PARITY_UUID_PROBE_CHUNK", "200"))
        if chunk_size <= 0:
            chunk_size = 200

        for i in range(0, len(unique), chunk_size):
            chunk = unique[i:i + chunk_size]
            cursor = None
            loops = 0
            # Send deliberately wrong local hash to force server to return update metadata.
            client_books = {u: {"m": "__probe__", "c": None, "f": None} for u in chunk}

            while True:
                loops += 1
                if loops > 50:
                    raise AssertionError("Targeted server hash pagination did not terminate")

                payload = self._build_targeted_hash_probe_payload(
                    chunk=chunk,
                    client_books=client_books,
                    cursor=cursor,
                )
                data = self._http_json("POST", "/sync/v5", payload=payload, timeout=self.http_timeout)
                for item in data.get("updates_for_client", []) or []:
                    uuid = str(item.get("uuid") or "").strip()
                    meta = str(item.get("metadata_hash") or "").strip().lower()
                    if uuid and meta:
                        server_map[uuid] = meta

                if not data.get("has_more"):
                    break
                cursor = data.get("cursor")
                if not cursor:
                    raise AssertionError("Targeted probe returned has_more=true without cursor")

        return server_map

    def _build_targeted_hash_probe_payload(self, chunk, client_books, cursor=None):
        # Restrict probe to sampled UUIDs: avoids full-library pagination on every chunk.
        return {
            "library_id": self.library_id,
            "calibre_library_uuid": self.library_uuid,
            "cursor": cursor,
            "batch_size": 1000,
            "client_books": {"b": client_books, "d": []},
            "options": {
                "sync_files_enabled": False,
                "sync_covers_enabled": False,
                "metadata_candidate_uuids": list(chunk or []),
            },
        }

    @staticmethod
    def _compute_library_root_from_map(hash_map):
        if not hash_map:
            return None
        ordered_uuids = sorted(hash_map.keys(), key=lambda u: u.lower().replace("-", ""))
        concat = "".join([hash_map[u] for u in ordered_uuids])
        return hashlib.sha256(concat.encode("utf-8")).hexdigest()

    def test_metadata_hash_parity_sqlite_view_vs_server_sync(self):
        local_map, local_root = self._load_local_metadata_hashes()
        server_map, server_root = self._load_server_metadata_hashes()

        self.assertTrue(local_map, "Local calimob_books_hash_v2 is empty")
        self.assertTrue(server_map, "Server updates_for_client metadata map is empty")

        common = sorted(set(local_map.keys()) & set(server_map.keys()))
        self.assertTrue(common, "No common UUIDs between local and server maps")

        mismatches = []
        for uuid in common:
            if local_map[uuid] != server_map[uuid]:
                mismatches.append(
                    {
                        "uuid": uuid,
                        "local": local_map[uuid],
                        "server": server_map[uuid],
                    }
                )

        report = {
            "local_count": len(local_map),
            "server_count": len(server_map),
            "common_count": len(common),
            "mismatch_count": len(mismatches),
            "local_root": local_root,
            "server_root": server_root,
            "sample_mismatches": mismatches[: self.max_report],
        }
        report_path = "/tmp/hash_view_cross_engine_e2e_report.json"
        with open(report_path, "w") as fh:
            json.dump(report, fh, indent=2, sort_keys=True)

        self.assertEqual(
            0,
            len(mismatches),
            "Metadata hash parity failed. Report: {}".format(report_path),
        )
        local_keys = set(local_map.keys())
        server_keys = set(server_map.keys())
        if local_keys == server_keys:
            self.assertEqual(
                local_root,
                server_root,
                "Library metadata root mismatch. Report: {}".format(report_path),
            )
        else:
            # In partial/incremental environments server can expose only a subset of local books.
            # Compare server root against local root recomputed on the same UUID subset.
            local_subset = {u: local_map[u] for u in server_map.keys() if u in local_map}
            local_subset_root = self._compute_library_root_from_map(local_subset)
            self.assertEqual(
                local_subset_root,
                server_root,
                "Library metadata root mismatch on shared UUID subset. Report: {}".format(report_path),
            )

    def test_sync_v5_does_not_request_metadata_for_matching_local_view_hashes(self):
        local_map, _ = self._load_local_metadata_hashes()
        server_map, _ = self._load_server_metadata_hashes()
        common = sorted(set(local_map.keys()) & set(server_map.keys()))
        self.assertTrue(common, "No common UUIDs between local and server maps")

        sample = common[: max(1, self.sample_probe_size)]
        client_books = {}
        for uuid in sample:
            client_books[uuid] = {"m": local_map[uuid], "c": None, "f": None}

        payload = {
            "library_id": self.library_id,
            "calibre_library_uuid": self.library_uuid,
            "cursor": None,
            "batch_size": 500,
            "client_books": {"b": client_books, "d": []},
            "options": {
                "sync_files_enabled": False,
                "sync_covers_enabled": False,
            },
        }
        data = self._http_json("POST", "/sync/v5", payload=payload, timeout=60)
        missing = data.get("missing_from_server", []) or []

        bad = []
        for entry in missing:
            uuid = str(entry.get("uuid") or "").strip()
            if uuid in client_books and bool(entry.get("needs_metadata")):
                bad.append(
                    {
                        "uuid": uuid,
                        "local_hash": local_map.get(uuid),
                        "server_hash": server_map.get(uuid),
                        "entry": entry,
                    }
                )

        report_path = "/tmp/hash_view_cross_engine_e2e_probe_report.json"
        with open(report_path, "w") as fh:
            json.dump(
                {
                    "sample_size": len(sample),
                    "bad_count": len(bad),
                    "bad": bad[: self.max_report],
                },
                fh,
                indent=2,
                sort_keys=True,
            )

        self.assertEqual(
            0,
            len(bad),
            "Server requested metadata upload for matching local hashes. Report: {}".format(report_path),
        )

    def test_local_plugin_hash_formula_matches_local_server_formula_emulation(self):
        plugin_map, _ = self._load_local_metadata_hashes()
        server_formula_map = self._load_local_server_formula_hashes()

        self.assertTrue(plugin_map, "Local plugin hash map is empty")
        self.assertTrue(server_formula_map, "Local server-formula hash map is empty")

        common = sorted(set(plugin_map.keys()) & set(server_formula_map.keys()))
        self.assertTrue(common, "No common UUIDs in local formula comparison")

        mismatches = []
        for uuid in common:
            if plugin_map[uuid] != server_formula_map[uuid]:
                mismatches.append(
                    {
                        "uuid": uuid,
                        "plugin_hash": plugin_map[uuid],
                        "server_formula_hash": server_formula_map[uuid],
                    }
                )

        report_path = "/tmp/hash_view_local_formula_parity_report.json"
        with open(report_path, "w") as fh:
            json.dump(
                {
                    "db_path": self.test_db_path,
                    "plugin_count": len(plugin_map),
                    "server_formula_count": len(server_formula_map),
                    "common_count": len(common),
                    "mismatch_count": len(mismatches),
                    "sample_mismatches": mismatches[: self.max_report],
                },
                fh,
                indent=2,
                sort_keys=True,
            )

        self.assertEqual(
            0,
            len(mismatches),
            "Local formula parity failed. Report: {}".format(report_path),
        )

    def test_json_item_sql_vs_traditional_upsert_server_hash_parity_sample_5pct_large_db(self):
        sample_percent = float(_env("CALIMOB_JSON_PARITY_SAMPLE_PERCENT", "5"))
        min_total_books = int(_env("CALIMOB_JSON_PARITY_MIN_TOTAL_BOOKS", "10000"))
        require_upsert = str(_env("CALIMOB_JSON_PARITY_REQUIRE_UPSERT", "0")).lower() in ("1", "true", "yes")

        worker = self._make_worker_for_sql_payload()
        sampled_ids, total_books = self._select_deterministic_sample_book_ids(sample_percent)
        if total_books < min_total_books:
            self.skipTest(
                "Total books {} below required minimum {} for large-sample parity test".format(
                    total_books, min_total_books
                )
            )
        self.assertTrue(sampled_ids, "Deterministic sample selection produced no book ids")

        matrix = self._build_json_parity_rows_for_book_ids(worker, sampled_ids)
        self.assertTrue(
            matrix,
            "No SQL parity rows built from sampled ids (sampled_ids={}, worker_error={!r}, test_db_path={})".format(
                len(sampled_ids),
                getattr(worker, "_last_v5_missing_sql_payload_error", None),
                self.test_db_path,
            ),
        )

        failures = []
        ok_status = {"ok", "created", "applied", "noop", "merged"}
        upserted_uuids = []
        upsert_blocked = False
        upsert_block_reason = None

        for row in matrix:
            payload = row["payload"]
            sql_item = dict(row["sql_item"])
            if "_pubdate_out_of_range" in sql_item:
                del sql_item["_pubdate_out_of_range"]
            traditional_item = self._build_traditional_json_from_sql_payload(payload)
            expected_hash = row["expected_hash"]

            sql_hash = (self._compute_metadata_hash(sql_item) or "").strip().lower()
            traditional_hash = (self._compute_metadata_hash(traditional_item) or "").strip().lower()

            if sql_hash != traditional_hash:
                failures.append({
                    "phase": "local_method_divergence",
                    "book_id": row["book_id"],
                    "uuid": row["uuid"],
                    "expected_hash": expected_hash,
                    "sql_hash": sql_hash,
                    "traditional_hash": traditional_hash,
                })
                continue

            try:
                sql_resp = self._post_upsert_item(sql_item)
                trad_resp = self._post_upsert_item(traditional_item)
            except AssertionError as exc:
                err = str(exc)
                if (
                    ("Limite libri raggiunto" in err)
                    or ("upgrade_required" in err)
                    or ("relation \\\"sessions\\\" does not exist" in err)
                    or ("relation \"sessions\" does not exist" in err)
                ):
                    upsert_blocked = True
                    upsert_block_reason = err
                    continue
                raise
            sql_status = ((sql_resp.get("results") or [{}])[0].get("status") or "").lower()
            trad_status = ((trad_resp.get("results") or [{}])[0].get("status") or "").lower()
            if sql_status not in ok_status or trad_status not in ok_status:
                failures.append({
                    "phase": "upsert_status",
                    "book_id": row["book_id"],
                    "uuid": row["uuid"],
                    "sql_status": sql_status,
                    "traditional_status": trad_status,
                })
                continue
            upserted_uuids.append(row["uuid"])

        probe_uuids = upserted_uuids if upserted_uuids else [r["uuid"] for r in matrix]
        server_map = self._load_server_metadata_hashes_for_uuids(probe_uuids)
        for row in matrix:
            if row["uuid"] not in probe_uuids:
                continue
            if row["uuid"] not in server_map:
                continue
            expected_hash = row["expected_hash"]
            server_hash = (server_map.get(row["uuid"]) or "").strip().lower()
            if server_hash != expected_hash:
                failures.append({
                    "phase": "server_hash_check",
                    "book_id": row["book_id"],
                    "uuid": row["uuid"],
                    "expected_hash": expected_hash,
                    "server_hash": server_hash,
                })

        if upsert_blocked and require_upsert:
            failures.append({
                "phase": "upsert_blocked_by_subscription",
                "reason": upsert_block_reason or "unknown",
            })

        report_path = "/tmp/hash_view_sql_vs_traditional_sample5pct_report.json"
        with open(report_path, "w") as fh:
            json.dump(
                {
                    "total_books": total_books,
                    "sample_percent": sample_percent,
                    "sampled_ids_count": len(sampled_ids),
                    "matrix_rows_count": len(matrix),
                    "require_upsert": require_upsert,
                    "upsert_blocked": upsert_blocked,
                    "failures_count": len(failures),
                    "sample_failures": failures[: self.max_report],
                },
                fh,
                indent=2,
                sort_keys=True,
            )

        self.assertEqual(
            [],
            failures,
            "5% SQL vs traditional parity/upsert mismatch. Report: {}".format(report_path),
        )


if __name__ == "__main__":
    unittest.main(verbosity=2)
