#!/usr/bin/env python3
"""
Headless protocol compliance suite for sync_calimob plugin.
Runs outside Calibre using stubs and validates UUID-only sync protocol end-to-end.
"""

from __future__ import annotations

import json
import os
import sys
import time
import uuid
import importlib.util
from pathlib import Path

# Ensure tests stubs are loaded (calibre + calibre_plugins)
TESTS_ROOT = Path(__file__).resolve().parents[2]
CONFTEXT_PATH = TESTS_ROOT / "plugin" / "conftest.py"
if CONFTEXT_PATH.exists():
    spec = importlib.util.spec_from_file_location("plugin_conftest", str(CONFTEXT_PATH))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

from calibre_plugins.sync_calimob import config as cfg
from calibre_plugins.sync_calimob.rest_client import RestApiClient, RestApiError


def load_env():
    env_path = Path(__file__).resolve().parents[2] / "server" / ".env"
    if env_path.exists():
        with env_path.open() as fh:
            for line in fh:
                if not line.strip() or line.strip().startswith("#"):
                    continue
                if "=" not in line:
                    continue
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k, v.strip().strip('"').strip("'"))


def ensure_env():
    discovery = os.environ.get("DISCOVERY_URL")
    email = os.environ.get("TEST_USER_EMAIL")
    password = os.environ.get("TEST_USER_PASSWORD")
    if not discovery or not email or not password:
        raise SystemExit("Missing env: DISCOVERY_URL, TEST_USER_EMAIL, TEST_USER_PASSWORD")
    return discovery, email, password


def assert_true(cond, msg):
    if not cond:
        raise AssertionError(msg)


def main():
    load_env()
    discovery_url, email, password = ensure_env()

    # Configure plugin prefs for headless client
    cfg.plugin_prefs.setdefault(cfg.STORE_PLUGIN, cfg.DEFAULT_STORE_VALUES.copy())
    cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_DISCOVERY_URL] = discovery_url
    cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_REST_ENDPOINT] = ""
    cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_REST_TOKEN] = ""
    cfg.plugin_prefs[cfg.STORE_PLUGIN][cfg.KEY_DEVICE_TOKEN] = ""

    client = RestApiClient()
    try:
        token = client.login_and_get_token(email, password).get("access_token")
    except RestApiError as exc:
        if os.environ.get("TEST_AUTO_REGISTER", "").lower() in ("1", "true", "yes"):
            # Try to register and retry login
            try:
                client._request("POST", "/auth/register", body={
                    "name": "Test User",
                    "email": email,
                    "password": password
                })
            except RestApiError:
                pass
            token = client.login_and_get_token(email, password).get("access_token")
        else:
            raise
    assert_true(token, "Login failed: missing token")
    client.token = token

    # Create or reuse library
    cal_lib_uuid = str(uuid.uuid4())
    lib_name = f"protocol_suite_{int(time.time())}"
    lib = client.create_library(lib_name, calibre_library_uuid=cal_lib_uuid)
    lib_id = lib.get("id")
    assert_true(lib_id, "Library creation failed")

    # 1) Initial pull with inventory
    pull = client.get_sync(library_id=lib_id, calibre_library_uuid=cal_lib_uuid, include_inventory=True)
    assert_true("changes" in pull, "Pull response missing changes")
    assert_true("new_cursor" in pull, "Pull response missing new_cursor")
    assert_true("inventory" in pull, "Pull response missing inventory")

    # 2) Create book (UUID-only)
    now = int(time.time())
    book_uuid = str(uuid.uuid4())
    book_id = int(now % 100000)
    item = {
        "id": book_id,
        "uuid": book_uuid,
        "title": "Protocol Suite Book",
        "authors": [{"name": "Protocol Author", "role": "author", "position": 0}],
        "last_modified": now,
    }
    change = {"op": "create", "item": item, "idempotency_key": f"proto-create-{now}"}
    assert_true("client_ids" not in change["item"], "client_ids must not be sent")
    resp = client.post_sync([change], library_id=lib_id, calibre_library_uuid=cal_lib_uuid)
    result = resp.get("results", [{}])[0]
    assert_true(result.get("status") in ("applied", "merged"), f"Create failed: {json.dumps(resp)}")
    assert_true(result.get("server_item", {}).get("uuid") == book_uuid, "Server UUID mismatch")

    # 3) Idempotency: same payload OK
    resp2 = client.post_sync([change], library_id=lib_id, calibre_library_uuid=cal_lib_uuid)
    assert_true(resp2.get("results", [{}])[0].get("status") in ("applied", "merged", "noop"),
                "Idempotency reuse failed")

    # 4) Idempotency mismatch (same key, different payload) should error
    bad_item = dict(item)
    bad_item["title"] = "Protocol Suite Book (changed)"
    bad_change = {"op": "create", "item": bad_item, "idempotency_key": change["idempotency_key"]}
    bad = client.post_sync([bad_change], library_id=lib_id, calibre_library_uuid=cal_lib_uuid)
    bad_status = bad.get("results", [{}])[0].get("status")
    assert_true(bad_status in ("error", "conflict"), "Expected idempotency mismatch to fail")

    # 5) Pull delta with inventory hint
    cursor = resp.get("new_cursor")
    delta = client.get_sync(library_id=lib_id, calibre_library_uuid=cal_lib_uuid,
                            cursor=cursor, include_inventory_hint=True)
    assert_true("inventory_hint" in delta, "Delta missing inventory_hint")

    # 6) Delete and ensure no resurrection
    delete_change = {
        "op": "delete",
        "item": {"id": book_id, "uuid": book_uuid, "last_modified": now + 10},
        "idempotency_key": f"proto-delete-{now}"
    }
    deleted = client.post_sync([delete_change], library_id=lib_id, calibre_library_uuid=cal_lib_uuid)
    del_status = deleted.get("results", [{}])[0].get("status")
    assert_true(del_status in ("applied", "merged", "noop"), "Delete failed")

    update_after_delete = {
        "op": "update",
        "item": {"id": book_id, "uuid": book_uuid, "title": "Should not resurrect", "last_modified": now + 20},
        "idempotency_key": f"proto-update-after-delete-{now}"
    }
    upd = client.post_sync([update_after_delete], library_id=lib_id, calibre_library_uuid=cal_lib_uuid)
    upd_status = upd.get("results", [{}])[0].get("status")
    assert_true(upd_status in ("conflict", "noop", "error"), "Deleted book should not resurrect")

    # 7) Delete missing book -> noop/not_found
    missing_change = {
        "op": "delete",
        "item": {"id": book_id + 9999, "uuid": str(uuid.uuid4()), "last_modified": now + 30},
        "idempotency_key": f"proto-delete-missing-{now}"
    }
    missing = client.post_sync([missing_change], library_id=lib_id, calibre_library_uuid=cal_lib_uuid)
    miss_status = missing.get("results", [{}])[0].get("status")
    assert_true(miss_status in ("noop", "conflict", "error"), "Delete missing should not be applied")

    # Cleanup + coverage: soft-delete library and ensure sync is blocked
    client._request("DELETE", f"/libraries/{lib_id}")

    # After delete, library should not be accessible or syncable
    blocked = False
    try:
        client.get_sync(library_id=lib_id, calibre_library_uuid=cal_lib_uuid)
    except RestApiError as exc:
        blocked = True
        assert_true(exc.status_code in (403, 404, 410), "Expected sync blocked for deleted library")
    assert_true(blocked, "Sync should be blocked after library delete")

    blocked_push = False
    try:
        client.post_sync([change], library_id=lib_id, calibre_library_uuid=cal_lib_uuid)
    except RestApiError as exc:
        blocked_push = True
        assert_true(exc.status_code in (403, 404, 410), "Expected push blocked for deleted library")
    assert_true(blocked_push, "Push should be blocked after library delete")

    # Restore library and ensure sync works again
    client._request("POST", f"/libraries/{lib_id}/restore")
    restored_pull = client.get_sync(library_id=lib_id, calibre_library_uuid=cal_lib_uuid)
    assert_true("changes" in restored_pull, "Sync should work after restore")

    print("Protocol compliance suite: PASS")


if __name__ == "__main__":
    main()
