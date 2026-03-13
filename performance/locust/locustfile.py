"""Locust harness for Calimob sync and presigned upload workflows."""

from __future__ import annotations

import hashlib
import os
import random
import time
from typing import Any

from locust import HttpUser, between, task


def _env(name: str, default: str = "") -> str:
    return os.getenv(name, default).strip()


def _env_bool(name: str, default: bool = False) -> bool:
    value = _env(name)
    if not value:
        return default
    return value.lower() in {"1", "true", "yes", "on"}


def _csv(name: str) -> list[str]:
    raw = _env(name)
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


class CalimobSyncUser(HttpUser):
    wait_time = between(
        int(_env("CALIMOB_LOCUST_WAIT_MIN_MS", "250")) / 1000.0,
        int(_env("CALIMOB_LOCUST_WAIT_MAX_MS", "1250")) / 1000.0,
    )

    host = _env("CALIMOB_LOCUST_BASE_URL", "http://caliserver.test")

    def on_start(self) -> None:
        self.api_prefix = _env("CALIMOB_LOCUST_API_PREFIX", "/api").rstrip("/")
        self.token = _env("CALIMOB_LOCUST_API_TOKEN")
        self.sync_files = _env_bool("CALIMOB_LOCUST_SYNC_FILES", False)
        self.sync_covers = _env_bool("CALIMOB_LOCUST_SYNC_COVERS", False)
        self.enable_presigned = _env_bool("CALIMOB_LOCUST_ENABLE_PRESIGNED", False)
        self.batch_size = int(_env("CALIMOB_LOCUST_BATCH_SIZE", "100"))
        self.client_batch_size = int(_env("CALIMOB_LOCUST_CLIENT_BATCH_SIZE", "100"))
        self.library_id = _env("CALIMOB_LOCUST_LIBRARY_ID")
        self.library_uuid = _env("CALIMOB_LOCUST_LIBRARY_UUID")
        self.book_uuid = _env("CALIMOB_LOCUST_BOOK_UUID")
        self.client_uuids = _csv("CALIMOB_LOCUST_CLIENT_UUIDS")
        self.headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept": "application/json",
        }
        if not self.token:
            raise RuntimeError("CALIMOB_LOCUST_API_TOKEN is required")
        self._resolve_library()
        if self.enable_presigned:
            self._resolve_book()

    def _api_get(self, path: str, name: str):
        return self.client.get(
            f"{self.api_prefix}{path}",
            headers=self.headers,
            name=name,
        )

    def _api_post(self, path: str, payload: dict[str, Any], name: str):
        return self.client.post(
            f"{self.api_prefix}{path}",
            json=payload,
            headers={**self.headers, "Content-Type": "application/json"},
            name=name,
        )

    def _resolve_library(self) -> None:
        if self.library_id and self.library_uuid:
            return
        response = self._api_get("/libraries", "bootstrap:libraries")
        response.raise_for_status()
        payload = response.json()
        first = None
        if isinstance(payload, list) and payload:
            first = payload[0]
        elif isinstance(payload, dict):
            data = payload.get("data")
            if isinstance(data, list) and data:
                first = data[0]
        if not first:
            raise RuntimeError("No library found for Locust bootstrap")
        self.library_id = self.library_id or str(first.get("id") or "")
        self.library_uuid = self.library_uuid or str(
            first.get("calibre_library_id")
            or first.get("calibre_library_uuid")
            or first.get("uuid")
            or ""
        )
        if not self.library_id:
            raise RuntimeError("Could not resolve CALIMOB_LOCUST_LIBRARY_ID")

    def _resolve_book(self) -> None:
        if self.book_uuid:
            return
        response = self._api_get(
            f"/user-books?library_id={self.library_id}&limit=1",
            "bootstrap:user-books",
        )
        response.raise_for_status()
        payload = response.json()
        data = payload.get("data") if isinstance(payload, dict) else None
        if not data:
            raise RuntimeError("No user-books found for presigned bootstrap")
        self.book_uuid = str(data[0].get("uuid") or "")
        if not self.book_uuid:
            raise RuntimeError("Could not resolve CALIMOB_LOCUST_BOOK_UUID")

    def _client_books_payload(self) -> dict[str, Any]:
        books: dict[str, Any] = {}
        for index, uuid in enumerate(self.client_uuids):
            books[uuid] = {
                "m": f"locust-m-{index}",
                "c": None,
                "f": None,
                "lm": int(time.time()) - index,
            }
        return {"b": books, "d": []}

    @task(3)
    def library_hash_preflight(self) -> None:
        self._api_get(
            f"/sync/v5/library-hash?library_id={self.library_id}",
            "sync:v5:library-hash",
        )

    @task(5)
    def sync_v5(self) -> None:
        payload = {
            "library_id": str(self.library_id),
            "calibre_library_uuid": self.library_uuid,
            "cursor": None,
            "batch_size": self.batch_size,
            "client_cursor": 0,
            "client_batch_size": self.client_batch_size,
            "sync_files_enabled": self.sync_files,
            "sync_covers_enabled": self.sync_covers,
            "client_books": self._client_books_payload(),
        }
        self._api_post("/sync/v5", payload, "sync:v5")

    @task(1)
    def merkle_root(self) -> None:
        self._api_get(
            f"/sync/v5/merkle-root?library_id={self.library_id}",
            "sync:v5:merkle-root",
        )

    @task(1)
    def presigned_upload(self) -> None:
        if not self.enable_presigned or not self.book_uuid:
            return

        payload_bytes = (
            f"locust-presigned:{self.environment.runner.user_count}:{random.random()}".encode(
                "utf-8"
            )
        )
        expected_sha256 = hashlib.sha256(payload_bytes).hexdigest()
        expected_size = len(payload_bytes)
        start_payload = {
            "library_id": int(self.library_id),
            "book_uuid": self.book_uuid,
            "format": "EPUB",
            "expected_sha256": expected_sha256,
            "expected_size": expected_size,
            "content_type": "application/octet-stream",
        }

        with self.client.post(
            f"{self.api_prefix}/sync/uploads/start",
            json=start_payload,
            headers={**self.headers, "Content-Type": "application/json"},
            name="sync:uploads:start",
            catch_response=True,
        ) as start_response:
            if start_response.status_code != 200:
                start_response.failure(f"start status={start_response.status_code}")
                return
            body = start_response.json()
            session_id = body.get("session_id")
            status = body.get("status")
            if status == "verified":
                start_response.success()
                return
            upload_url = body.get("upload_url")
            object_key = body.get("temp_object_key")
            if not session_id or not upload_url or not object_key:
                start_response.failure("missing session/upload data")
                return
            put_response = self.client.put(
                upload_url,
                data=payload_bytes,
                headers={"Content-Type": "application/octet-stream"},
                name="sync:uploads:put",
            )
            if put_response.status_code not in {200, 201, 204}:
                start_response.failure(f"put status={put_response.status_code}")
                return
            complete_payload = {
                "session_id": session_id,
                "object_key": object_key,
                "size": expected_size,
            }
            complete_response = self._api_post(
                "/sync/uploads/complete",
                complete_payload,
                "sync:uploads:complete",
            )
            if complete_response.status_code != 200:
                start_response.failure(
                    f"complete status={complete_response.status_code}"
                )
                return
            verify_response = self._api_post(
                "/sync/uploads/verify",
                {"session_id": session_id},
                "sync:uploads:verify",
            )
            if verify_response.status_code != 200:
                start_response.failure(f"verify status={verify_response.status_code}")
                return
            start_response.success()
