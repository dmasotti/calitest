import sys
from pathlib import Path
from unittest.mock import AsyncMock

from fastapi.testclient import TestClient


APP_DIR = Path(__file__).resolve().parent.parent.parent.parent / "calicloud" / "rag-comics-hf-bench" / "app"
if str(APP_DIR) not in sys.path:
    sys.path.insert(0, str(APP_DIR))

import main as hf_main  # noqa: E402


def _reset_jobs():
    hf_main._JOB_STORE.clear()


def test_health_reports_version_and_hf_token_check(monkeypatch):
    _reset_jobs()
    monkeypatch.setenv("APP_VERSION", "test-version")
    monkeypatch.setenv("HF_TOKEN", "present")

    async def fake_auth_health():
        return {"status": "ok", "url": "http://auth"}

    monkeypatch.setattr(hf_main, "check_auth_service", fake_auth_health)

    client = TestClient(hf_main.app)
    response = client.get("/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["service"] == "rag-comics-hf-bench"
    assert payload["version"] == "test-version"
    assert payload["checks"]["hf_token"]["status"] == "ok"


def test_upload_async_accepts_file_url_and_sends_callback(monkeypatch):
    _reset_jobs()

    async def fake_validate(token, session_id):
        assert token == "test-token"
        assert session_id == "bookuuid_CBZ"
        return {"user_id": "user-1"}

    async def fake_run(**kwargs):
        assert kwargs["session_id"] == "bookuuid_CBZ"
        assert kwargs["book_id"] == "42"
        assert kwargs["source_kind"] == "file_url"
        assert kwargs["vision_provider"] == "gemini"
        assert kwargs["vision_model"] is None
        return {
            "summary": {
                "runs": [
                    {
                        "pipeline": "hf-rtdetr-bubble-ocr",
                        "pages": 2,
                        "panels": 3,
                        "balloons": 4,
                        "balloons_with_text": 3,
                        "cost_usd": 0.0,
                    }
                ]
            },
            "primary_result": {
                "pipeline": "hf-rtdetr-bubble-ocr",
                "pages": [
                    {
                        "page": 0,
                        "text": "Hello there",
                        "balloons": [{"x1": 1, "y1": 2, "x2": 30, "y2": 40, "text": "Hello there"}],
                        "panels": [
                            {
                                "reading_order": 1,
                                "corners": {"x1": 0, "y1": 0, "x2": 100, "y2": 0, "x3": 100, "y3": 120, "x4": 0, "y4": 120},
                                "balloons": [{"x1": 1, "y1": 2, "x2": 30, "y2": 40, "text": "Hello there"}],
                            }
                        ],
                    }
                ],
                "pipeline_meta": {"type": "hf-rtdetr-bubble-ocr"},
                "cost_usd": 0.0,
                "tokens_used": {"vision_total_tokens": 0},
            },
            "selected_pipeline": "hf-rtdetr-bubble-ocr",
            "output_dir": "/tmp/out",
            "elapsed_seconds": 1.23,
        }

    send_callback = AsyncMock()

    async def fake_download(file_url, dest_path):
        dest_path.write_bytes(b"fake-cbz")
        return dest_path

    monkeypatch.setattr(hf_main, "validate_token_and_book_access", fake_validate)
    monkeypatch.setattr(hf_main, "download_remote_file", fake_download)
    monkeypatch.setattr(hf_main, "run_hf_benchmark_job", fake_run)
    monkeypatch.setattr(hf_main, "send_callback", send_callback)

    client = TestClient(hf_main.app)
    response = client.post(
        "/upload-async?session_id=bookuuid_CBZ&book_id=42&callback_url=https://example.com/webhook",
        headers={"Authorization": "Bearer test-token"},
        json={"file_url": "https://example.com/comic.cbz"},
    )

    assert response.status_code == 200
    assert response.json()["status"] == "processing"

    status = client.get("/upload-status/bookuuid_CBZ")
    assert status.status_code == 200
    status_payload = status.json()
    assert status_payload["status"] == "completed"
    assert status_payload["selected_pipeline"] == "hf-rtdetr-bubble-ocr"

    send_callback.assert_awaited_once()
    callback_payload = send_callback.await_args.args[1]
    assert callback_payload["kind"] == "indexing"
    assert callback_payload["status"] == "completed"
    assert callback_payload["book_id"] == "42"
    assert callback_payload["session_id"] == "bookuuid_CBZ"
    assert callback_payload["pages_metadata"][0]["page_number"] == 1
    assert callback_payload["pages_metadata"][0]["vision_provider"] == "gemini"


def test_upload_async_requires_file_or_file_url(monkeypatch):
    _reset_jobs()

    async def fake_validate(token, session_id):
        return {"user_id": "user-1"}

    monkeypatch.setattr(hf_main, "validate_token_and_book_access", fake_validate)

    client = TestClient(hf_main.app)
    response = client.post(
        "/upload-async?session_id=bookuuid_CBZ&book_id=42&callback_url=https://example.com/webhook",
        headers={"Authorization": "Bearer test-token"},
        json={},
    )

    assert response.status_code == 400
    assert "Either 'file' or 'file_url' must be provided" in response.text


def test_upload_async_denies_book_access(monkeypatch):
    _reset_jobs()

    async def fake_validate(token, session_id):
        raise hf_main.HTTPException(status_code=403, detail="book_access_denied")

    monkeypatch.setattr(hf_main, "validate_token_and_book_access", fake_validate)

    client = TestClient(hf_main.app)
    response = client.post(
        "/upload-async?session_id=bookuuid_CBZ&book_id=42&callback_url=https://example.com/webhook",
        headers={"Authorization": "Bearer test-token"},
        json={"file_url": "https://example.com/comic.cbz"},
    )

    assert response.status_code == 403
    assert response.json()["detail"] == "book_access_denied"
