#!/usr/bin/env python3
"""
Real E2E bidirectional sync check (Calibre plugin <-> server).

What it validates:
1) Local -> Server push:
   - identifier propagation
   - related metadata tables presence (authors/tags/series links)
   - cover/files server-side presence checks
2) Server -> Local pull:
   - title change propagation
   - identifier change propagation
   - tag link propagation
   - local cover/files still available

Required env:
  CALIBRE_DEBUG                 (default: /Applications/calibre.app/Contents/MacOS/calibre-debug)
  CALIMOB_TEST_LIBRARY_PATH
  CALIMOB_TEST_LIBRARY_UUID
  CALIMOB_TEST_CALIMOB_LIB_ID
  CALIMOB_TEST_API_URL          (e.g. http://caliserver.test/api)
  CALIMOB_TEST_TOKEN            (must be allowed to call /api/tools/sql)
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from typing import Any, Dict


def _now() -> str:
    return time.strftime("%H:%M:%S")


def log(msg: str) -> None:
    print(f"[{_now()}] {msg}")


def fail(msg: str) -> None:
    raise RuntimeError(msg)


def require_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        fail(f"Missing env: {name}")
    return value


def run_calibre_script(calibre_debug: str, script: str, timeout: int = 240) -> str:
    with tempfile.NamedTemporaryFile(mode="w", suffix=".py", delete=False) as f:
        f.write(script)
        script_path = f.name
    try:
        result = subprocess.run(
            [calibre_debug, "-e", script_path],
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    finally:
        os.unlink(script_path)

    output = (result.stdout or "") + "\n" + (result.stderr or "")
    if result.returncode != 0:
        fail(f"calibre-debug failed ({result.returncode}):\n{output[-2000:]}")
    return output


def parse_json_block(output: str, start_marker: str, end_marker: str) -> Dict[str, Any]:
    if start_marker not in output or end_marker not in output:
        fail(f"Missing markers {start_marker}/{end_marker} in output:\n{output[-2000:]}")
    start = output.index(start_marker) + len(start_marker)
    end = output.index(end_marker)
    payload = output[start:end].strip()
    return json.loads(payload)


def sql_query(api_url: str, token: str, query: str) -> Dict[str, Any]:
    url = api_url.rstrip("/") + "/tools/sql"
    req = urllib.request.Request(
        url,
        data=json.dumps({"q": query}).encode("utf-8"),
        method="POST",
    )
    req.add_header("Authorization", f"Bearer {token}")
    req.add_header("Accept", "application/json")
    req.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            body = resp.read().decode("utf-8")
            return json.loads(body)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="ignore")
        fail(f"/api/tools/sql HTTP {exc.code}: {body[:1200]}")


def sql_rows(api_url: str, token: str, query: str) -> list[dict]:
    data = sql_query(api_url, token, query)
    rows = data.get("rows")
    if rows is None:
        fail(f"Unexpected SQL response: {json.dumps(data)[:1200]}")
    return rows


def sql_exec(api_url: str, token: str, query: str) -> int:
    data = sql_query(api_url, token, query)
    if "affected" not in data:
        fail(f"Unexpected SQL exec response: {json.dumps(data)[:1200]}")
    return int(data.get("affected") or 0)


def get_local_book_snapshot(calibre_debug: str, library_path: str) -> Dict[str, Any]:
    script = f"""
import json
from calibre.library import db
from hashlib import sha256

database = db({library_path!r})
book_ids = sorted(database.all_ids())
if not book_ids:
    print("RESULT_JSON_START")
    print(json.dumps({{"error": "no_books"}}))
    print("RESULT_JSON_END")
    raise SystemExit(0)

book_id = None
mi = None
identifiers = {{}}
formats = []
file_hashes = {{}}
for candidate in book_ids:
    c_formats = database.formats(candidate, index_is_id=True) or []
    if isinstance(c_formats, str):
        c_formats = [f.strip() for f in c_formats.split(",") if f.strip()]
    c_hashes = {{}}
    for fmt in c_formats:
        raw = database.format(candidate, fmt, as_path=False, index_is_id=True)
        if raw is None and isinstance(fmt, str):
            raw = database.format(candidate, fmt.lower(), as_path=False, index_is_id=True)
        if raw:
            c_hashes[fmt.upper()] = "sha256:" + sha256(raw).hexdigest()
    if c_hashes:
        book_id = candidate
        formats = c_formats
        file_hashes = c_hashes
        mi = database.get_metadata(book_id, index_is_id=True)
        identifiers = database.get_identifiers(book_id, index_is_id=True) or {{}}
        break

if book_id is None:
    # Fallback to first book even if file payload is empty.
    book_id = book_ids[0]
    mi = database.get_metadata(book_id, index_is_id=True)
    identifiers = database.get_identifiers(book_id, index_is_id=True) or {{}}
    formats = database.formats(book_id, index_is_id=True) or []
    if isinstance(formats, str):
        formats = [f.strip() for f in formats.split(",") if f.strip()]

cover = database.cover(book_id, index_is_id=True)
cover_hash = None
if cover:
    cover_hash = "sha256:" + sha256(cover).hexdigest()

payload = {{
    "book_id": book_id,
    "uuid": mi.uuid,
    "title": mi.title,
    "identifiers": identifiers,
    "authors": mi.authors or [],
    "tags": mi.tags or [],
    "series": mi.series,
    "publisher": mi.publisher,
    "languages": mi.languages or [],
    "formats": [f.upper() for f in formats],
    "file_hashes": file_hashes,
    "has_real_file_payload": bool(file_hashes),
    "has_cover": bool(cover),
    "cover_hash": cover_hash,
}}
print("RESULT_JSON_START")
print(json.dumps(payload))
print("RESULT_JSON_END")
"""
    out = run_calibre_script(calibre_debug, script, timeout=120)
    data = parse_json_block(out, "RESULT_JSON_START", "RESULT_JSON_END")
    if data.get("error") == "no_books":
        fail("Local library has no books")
    return data


def set_local_identifier(calibre_debug: str, library_path: str, book_id: int, key: str, val: str, title_marker: str) -> None:
    script = f"""
from calibre.library import db
database = db({library_path!r})
mi = database.get_metadata({book_id}, index_is_id=True)
mi.title = {title_marker!r}
try:
    database.set_metadata({book_id}, mi, force_changes=True, set_title=True, index_is_id=True)
except TypeError:
    database.set_metadata({book_id}, mi, force_changes=True)
database.set_identifier({book_id}, {key!r}, {val!r})
database.commit()
print("OK_SET_IDENTIFIER_AND_TITLE")
"""
    out = run_calibre_script(calibre_debug, script, timeout=120)
    if "OK_SET_IDENTIFIER_AND_TITLE" not in out:
        fail(f"Failed to set local identifier/title: {out[-1200:]}")


def run_sync_v5(
    calibre_debug: str,
    plugin_dir: str,
    library_path: str,
    library_uuid: str,
    calimob_library_id: str,
    api_url: str,
    token: str,
    clear_cursor: bool = False,
) -> Dict[str, Any]:
    reset_cursor = "worker.reset_cursor()" if clear_cursor else ""
    script = f"""
import json
import sys
import types
sys.path.insert(0, {plugin_dir!r})

# Make plugin imports work even with isolated CALIBRE_CONFIG_DIRECTORY.
if "calibre_plugins" not in sys.modules:
    calibre_plugins_pkg = types.ModuleType("calibre_plugins")
    calibre_plugins_pkg.__path__ = [{plugin_dir!r}]
    sys.modules["calibre_plugins"] = calibre_plugins_pkg
if "calibre_plugins.sync_calimob" not in sys.modules:
    sync_pkg = types.ModuleType("calibre_plugins.sync_calimob")
    sync_pkg.__path__ = [{plugin_dir!r}]
    sys.modules["calibre_plugins.sync_calimob"] = sync_pkg

from calibre.library import db
from calibre_plugins.sync_calimob import config as cfg
from calibre_plugins.sync_calimob import mapping_table
from calibre_plugins.sync_calimob.sync_worker import SyncWorker

library_path = {library_path!r}
library_uuid = {library_uuid!r}
calimob_library_id = {calimob_library_id!r}
api_url = {api_url!r}
token = {token!r}

with mapping_table._connect(library_path) as conn:
    mapping_table._ensure_table(conn)
    conn.commit()

database = db(library_path)
store = dict(cfg.plugin_prefs.get(cfg.STORE_PLUGIN, {{}}))
store[cfg.KEY_REST_ENDPOINT] = api_url
store[cfg.KEY_REST_TOKEN] = token
store[cfg.KEY_DEVICE_TOKEN] = token
store[cfg.KEY_DISCOVERY_URL] = ''
store[cfg.KEY_DISCOVERY_CACHE] = {{}}
cfg.plugin_prefs[cfg.STORE_PLUGIN] = store

worker = SyncWorker(None, database, library_uuid, calimob_library_id)
{reset_cursor}
summary = worker.sync_v5()
print("SYNC_JSON_START")
print(json.dumps(summary))
print("SYNC_JSON_END")
"""
    out = run_calibre_script(calibre_debug, script, timeout=600)
    summary = parse_json_block(out, "SYNC_JSON_START", "SYNC_JSON_END")
    return summary


def escape_sql(value: str) -> str:
    return value.replace("\\", "\\\\").replace("'", "''")


def server_mutate_for_pull(api_url: str, token: str, user_id: int, library_id: int, book_uuid: str, stamp: str) -> Dict[str, str]:
    title_marker = f"E2E_SERVER_TITLE_{stamp}"
    id_key = "e2e_server_id"
    id_val = f"E2E-SERVER-{stamp}"
    tag_name = f"e2e_server_tag_{stamp}"

    sql_exec(
        api_url,
        token,
        "UPDATE books "
        f"SET title='{escape_sql(title_marker)}', description='E2E server description {escape_sql(stamp)}', "
        "last_modified=NOW(), updated_at=NOW() "
        f"WHERE uuid='{escape_sql(book_uuid)}' AND user_id={user_id} AND library_id={library_id}",
    )

    sql_exec(
        api_url,
        token,
        "INSERT INTO books_identifiers (id, user_id, library_id, created_at, updated_at, book, type, val, uuid) "
        f"VALUES (NULL, {user_id}, {library_id}, NOW(), NOW(), '{escape_sql(book_uuid)}', '{id_key}', '{escape_sql(id_val)}', UUID()) "
        f"ON DUPLICATE KEY UPDATE val='{escape_sql(id_val)}', updated_at=NOW()",
    )

    tag_id_rows = sql_rows(
        api_url,
        token,
        f"SELECT COALESCE(MAX(id), 0) + 1 AS next_id FROM books_tags WHERE user_id={user_id} AND library_id={library_id}",
    )
    tag_id = int(tag_id_rows[0]["next_id"])

    sql_exec(
        api_url,
        token,
        "INSERT INTO books_tags (id, user_id, library_id, created_at, updated_at, name, link, uuid) "
        f"VALUES ({tag_id}, {user_id}, {library_id}, NOW(), NOW(), '{escape_sql(tag_name)}', '', UUID()) "
        f"ON DUPLICATE KEY UPDATE updated_at=NOW()",
    )

    sql_exec(
        api_url,
        token,
        "INSERT INTO books_tags_link (id, book, tag, user_id, library_id, created_at, updated_at, uuid) "
        f"VALUES (NULL, '{escape_sql(book_uuid)}', {tag_id}, {user_id}, {library_id}, NOW(), NOW(), UUID()) "
        "ON DUPLICATE KEY UPDATE updated_at=NOW()",
    )

    sql_exec(
        api_url,
        token,
        "UPDATE books SET last_modified=NOW(), updated_at=NOW() "
        f"WHERE uuid='{escape_sql(book_uuid)}' AND user_id={user_id} AND library_id={library_id}",
    )

    return {
        "title_marker": title_marker,
        "server_identifier_key": id_key,
        "server_identifier_val": id_val,
        "server_tag_name": tag_name,
    }


def server_force_missing_book(api_url: str, token: str, user_id: int, library_id: int, book_uuid: str) -> None:
    # Remove dependent rows first to force a clean "missing_from_server" push path.
    for table in [
        "books_identifiers",
        "books_files",
        "books_tags_link",
        "books_series_link",
        "books_authors_link",
    ]:
        sql_exec(
            api_url,
            token,
            f"DELETE FROM {table} WHERE book='{escape_sql(book_uuid)}' AND user_id={user_id} AND library_id={library_id}",
        )
    sql_exec(
        api_url,
        token,
        "DELETE FROM books "
        f"WHERE uuid='{escape_sql(book_uuid)}' AND user_id={user_id} AND library_id={library_id}",
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Real bidirectional E2E sync checks")
    parser.add_argument("--clear-cursor-before-pull", action="store_true", help="Reset pull cursor before server->local phase")
    parser.add_argument("--skip-server-mutation", action="store_true", help="Only run local->server checks")
    parser.add_argument("--force-missing", action="store_true", help="Delete target server book before push to force missing_from_server path")
    args = parser.parse_args()

    calibre_debug = os.getenv("CALIBRE_DEBUG", "/Applications/calibre.app/Contents/MacOS/calibre-debug")
    plugin_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "sync_calimob"))
    default_cfg = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".calibre-config"))
    os.environ.setdefault("CALIBRE_CONFIG_DIRECTORY", default_cfg)
    os.makedirs(os.environ["CALIBRE_CONFIG_DIRECTORY"], exist_ok=True)
    library_path = require_env("CALIMOB_TEST_LIBRARY_PATH")
    library_uuid = require_env("CALIMOB_TEST_LIBRARY_UUID")
    calimob_library_id = require_env("CALIMOB_TEST_CALIMOB_LIB_ID")
    api_url = require_env("CALIMOB_TEST_API_URL")
    token = require_env("CALIMOB_TEST_TOKEN")

    log("Collecting local baseline snapshot...")
    before = get_local_book_snapshot(calibre_debug, library_path)
    book_id = int(before["book_id"])
    book_uuid = before["uuid"]
    stamp = str(int(time.time()))
    local_push_key = "e2e_local_id"
    local_push_val = f"E2E-LOCAL-{stamp}"

    log(f"Target book: id={book_id} uuid={book_uuid}")
    local_push_title = f"E2E_LOCAL_TITLE_{stamp}"
    lib_rows = sql_rows(
        api_url,
        token,
        f"SELECT id, user_id, calibre_library_id FROM libraries WHERE id={int(calimob_library_id)} LIMIT 1",
    )
    if not lib_rows:
        fail(f"Library id {calimob_library_id} not found on server")
    user_id = int(lib_rows[0]["user_id"])
    library_id = int(lib_rows[0]["id"])

    if args.force_missing:
        log("Deleting target book on server to force push path...")
        server_force_missing_book(api_url, token, user_id, library_id, book_uuid)

    log(f"Setting local identifier {local_push_key}={local_push_val} and title marker...")
    set_local_identifier(calibre_debug, library_path, book_id, local_push_key, local_push_val, local_push_title)

    log("Running sync (local -> server push)...")
    push_summary = run_sync_v5(
        calibre_debug,
        plugin_dir,
        library_path,
        library_uuid,
        calimob_library_id,
        api_url,
        token,
        clear_cursor=False,
    )
    if push_summary.get("errors"):
        fail(f"Push sync completed with errors: {json.dumps(push_summary.get('errors'))[:1200]}")

    log("Validating server-side push checks (identifiers + related tables + cover/files)...")
    has_real_file_payload = bool(before.get("has_real_file_payload"))
    push_checks = {
        "identifier_local_push": bool(
            sql_rows(
                api_url,
                token,
                "SELECT 1 AS ok FROM books_identifiers "
                f"WHERE book='{escape_sql(book_uuid)}' AND type='{local_push_key}' AND val='{escape_sql(local_push_val)}' "
                f"AND user_id={user_id} AND library_id={library_id} LIMIT 1",
            )
        ),
        "title_local_push": bool(
            sql_rows(
                api_url,
                token,
                "SELECT 1 AS ok FROM books "
                f"WHERE uuid='{escape_sql(book_uuid)}' AND user_id={user_id} AND library_id={library_id} "
                f"AND title='{escape_sql(local_push_title)}' LIMIT 1",
            )
        ),
        "authors_link_exists": bool(
            sql_rows(
                api_url,
                token,
                "SELECT 1 AS ok FROM books_authors_link "
                f"WHERE book='{escape_sql(book_uuid)}' AND user_id={user_id} AND library_id={library_id} LIMIT 1",
            )
        ),
        "tags_link_exists": bool(
            sql_rows(
                api_url,
                token,
                "SELECT 1 AS ok FROM books_tags_link "
                f"WHERE book='{escape_sql(book_uuid)}' AND user_id={user_id} AND library_id={library_id} LIMIT 1",
            )
        ),
        "series_link_exists_or_empty": True,
        "files_rows_exist": bool(
            sql_rows(
                api_url,
                token,
                "SELECT 1 AS ok FROM books_files "
                f"WHERE book='{escape_sql(book_uuid)}' AND user_id={user_id} AND library_id={library_id} LIMIT 1",
            )
        ),
        "cover_present_in_books": bool(
            sql_rows(
                api_url,
                token,
                "SELECT 1 AS ok FROM books "
                f"WHERE uuid='{escape_sql(book_uuid)}' AND user_id={user_id} AND library_id={library_id} "
                "AND (has_cover=1 OR cover_url IS NOT NULL OR cover_optimized_hash IS NOT NULL OR cover_original_hash IS NOT NULL) "
                "LIMIT 1",
            )
        ),
    }
    if not has_real_file_payload:
        push_checks["files_rows_exist"] = True
    series_link_rows = sql_rows(
        api_url,
        token,
        "SELECT 1 AS ok FROM books_series_link "
        f"WHERE book='{escape_sql(book_uuid)}' AND user_id={user_id} AND library_id={library_id} LIMIT 1",
    )
    if not series_link_rows and before.get("series"):
        push_checks["series_link_exists_or_empty"] = False

    failed_push_checks = [k for k, v in push_checks.items() if not v]

    pull_checks: Dict[str, Any] = {}
    mutate_info: Dict[str, str] = {}

    if not args.skip_server_mutation:
        log("Mutating server metadata for pull phase (title + identifier + tag)...")
        mutate_info = server_mutate_for_pull(api_url, token, user_id, library_id, book_uuid, stamp)

        log("Running sync (server -> local pull)...")
        pull_summary = run_sync_v5(
            calibre_debug,
            plugin_dir,
            library_path,
            library_uuid,
            calimob_library_id,
            api_url,
            token,
            clear_cursor=args.clear_cursor_before_pull,
        )
        if pull_summary.get("errors"):
            fail(f"Pull sync completed with errors: {json.dumps(pull_summary.get('errors'))[:1200]}")

        after = get_local_book_snapshot(calibre_debug, library_path)
        identifiers_after = {str(k).lower(): str(v) for k, v in (after.get("identifiers") or {}).items()}
        tags_after = {str(t).lower() for t in (after.get("tags") or [])}

        pull_checks = {
            "title_pulled_from_server": after.get("title") == mutate_info["title_marker"],
            "identifier_pulled_from_server": identifiers_after.get(mutate_info["server_identifier_key"]) == mutate_info["server_identifier_val"],
            "tag_pulled_from_server": mutate_info["server_tag_name"].lower() in tags_after,
            "local_has_cover": bool(after.get("has_cover")),
            "local_has_files": bool(after.get("formats")),
        }
        if not has_real_file_payload:
            pull_checks["local_has_files"] = True
        failed_pull_checks = [k for k, v in pull_checks.items() if not v]
    else:
        failed_pull_checks = []

    result = {
        "status": "ok",
        "book_uuid": book_uuid,
        "library_uuid": library_uuid,
        "library_id": library_id,
        "user_id": user_id,
        "local_push_identifier": {"key": local_push_key, "value": local_push_val},
        "has_real_file_payload": has_real_file_payload,
        "push_checks": push_checks,
        "server_mutation": mutate_info,
        "pull_checks": pull_checks,
        "failed_checks": {
            "push": failed_push_checks,
            "pull": failed_pull_checks,
        },
    }

    if failed_push_checks or failed_pull_checks:
        result["status"] = "failed_checks"

    print("E2E_RESULT_START")
    print(json.dumps(result, indent=2))
    print("E2E_RESULT_END")
    if result["status"] == "ok":
        log("E2E bidirectional checks passed.")
        return 0
    log(f"E2E completed with failed checks: push={failed_push_checks}, pull={failed_pull_checks}")
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:
        print(f"[{_now()}] ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
