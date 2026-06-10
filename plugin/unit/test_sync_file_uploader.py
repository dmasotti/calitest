"""
Unit tests for sync_file_uploader.py — retry logic and retriability checks.

Covers:
  fu01: _is_retriable → True for 5xx
  fu02: _is_retriable → True for 429
  fu03: _is_retriable → False for 4xx (except 429)
  fu04: _is_retriable → True for OSError/IOError
  fu05: _is_retriable → True for RestApiError with no status_code
  fu06: _retry_with_backoff → retries on 5xx, succeeds on 3rd attempt
  fu07: _retry_with_backoff → immediate fail on 4xx (no retry)
  fu08: _retry_with_backoff → raises after max_retries exhausted
  fu09: _retry_with_backoff → respects cancel_check
  fu10: FileUploader._is_cancelled → reflects cancel callback
  fu11: FileUploader.upload_batch with empty list → no-op
"""
from __future__ import annotations

import importlib.util
import sys
import time
from pathlib import Path
from unittest.mock import Mock, patch, MagicMock

import pytest

_plugin_root = Path(__file__).resolve().parents[3] / 'sync_calimob'

# Ensure sync_calimob dir is on sys.path so bare `from rest_client import ...`
# inside sync_file_uploader resolves to the same module as conftest loaded.
if str(_plugin_root) not in sys.path:
    sys.path.insert(0, str(_plugin_root))

# Make sure bare 'rest_client' in sys.modules points to the same module
# that conftest loaded as 'calibre_plugins.sync_calimob.rest_client'.
# This ensures isinstance(exc, RestApiError) works inside _is_retriable.
_rest_mod = sys.modules.get('calibre_plugins.sync_calimob.rest_client')
if _rest_mod is not None and 'rest_client' not in sys.modules:
    sys.modules['rest_client'] = _rest_mod
import rest_client

# Load sync_file_uploader module
_sfu_path = _plugin_root / 'sync_file_uploader.py'
_sfu_spec = importlib.util.spec_from_file_location(
    'sync_file_uploader', str(_sfu_path)
)
sync_file_uploader = importlib.util.module_from_spec(_sfu_spec)
sys.modules['sync_file_uploader'] = sync_file_uploader
_sfu_spec.loader.exec_module(sync_file_uploader)


# ── Helpers ──────────────────────────────────────────────────────────────────

def _raise_cancelled():
    raise Exception('cancelled')


def _make_rest_error(status_code=None):
    """Create a RestApiError with a given status code."""
    return rest_client.RestApiError(
        'test error', status_code=status_code, response_body='error body'
    )


# ── _is_retriable tests ─────────────────────────────────────────────────────

class TestIsRetriable:

    def test_fu01_5xx_is_retriable(self):
        for code in [500, 502, 503, 504]:
            exc = _make_rest_error(code)
            assert sync_file_uploader._is_retriable(exc) is True

    def test_fu02_429_is_retriable(self):
        exc = _make_rest_error(429)
        assert sync_file_uploader._is_retriable(exc) is True

    def test_fu03_4xx_not_retriable(self):
        for code in [400, 401, 403, 404, 409, 422]:
            exc = _make_rest_error(code)
            assert sync_file_uploader._is_retriable(exc) is False

    def test_fu04_oserror_is_retriable(self):
        assert sync_file_uploader._is_retriable(OSError('conn reset')) is True

    def test_fu04b_ioerror_is_retriable(self):
        assert sync_file_uploader._is_retriable(IOError('broken pipe')) is True

    def test_fu05_rest_error_no_status_code_is_retriable(self):
        exc = _make_rest_error(status_code=None)
        assert sync_file_uploader._is_retriable(exc) is True

    def test_non_rest_non_os_error_not_retriable(self):
        assert sync_file_uploader._is_retriable(ValueError('bad')) is False


# ── _retry_with_backoff tests ────────────────────────────────────────────────

class TestRetryWithBackoff:

    def test_fu06_retries_on_5xx_succeeds_3rd_attempt(self):
        """Retry on 5xx, succeed on 3rd attempt."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            if call_count[0] < 3:
                raise _make_rest_error(500)
            return 'ok'

        result = sync_file_uploader._retry_with_backoff(
            fn, max_retries=3, base_delay=0.01, max_delay=0.05
        )
        assert result == 'ok'
        assert call_count[0] == 3

    def test_fu07_no_retry_on_4xx(self):
        """4xx errors should raise immediately without retry."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            raise _make_rest_error(403)

        with pytest.raises(rest_client.RestApiError) as exc_info:
            sync_file_uploader._retry_with_backoff(
                fn, max_retries=3, base_delay=0.01
            )
        assert exc_info.value.status_code == 403
        assert call_count[0] == 1  # no retry

    def test_fu08_raises_after_max_retries_exhausted(self):
        """After max_retries attempts, the last error is re-raised."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            raise _make_rest_error(500)

        with pytest.raises(rest_client.RestApiError) as exc_info:
            sync_file_uploader._retry_with_backoff(
                fn, max_retries=3, base_delay=0.01, max_delay=0.05
            )
        assert exc_info.value.status_code == 500
        assert call_count[0] == 3

    def test_fu09_cancel_check_aborts_retry(self):
        """If cancel_check raises, retry loop aborts."""
        call_count = [0]

        def fn():
            call_count[0] += 1
            raise _make_rest_error(500)

        def cancel():
            if call_count[0] >= 1:
                raise Exception('cancelled')

        with pytest.raises(rest_client.RestApiError):
            sync_file_uploader._retry_with_backoff(
                fn, max_retries=5, base_delay=0.01, cancel_check=cancel
            )
        # Should have been cancelled after 1st attempt (cancel fires before 2nd sleep)
        assert call_count[0] <= 2

    def test_success_on_first_attempt(self):
        """No retry needed when first call succeeds."""
        result = sync_file_uploader._retry_with_backoff(
            lambda: 'immediate', max_retries=3
        )
        assert result == 'immediate'


# ── FileUploader tests ───────────────────────────────────────────────────────

class TestFileUploaderCancellation:

    def test_fu10_is_cancelled_reflects_callback(self):
        """_is_cancelled returns True when cancel callback raises."""
        uploader = sync_file_uploader.FileUploader(
            client=Mock(), db=Mock(),
            cancel_check_fn=_raise_cancelled,
        )
        assert uploader._is_cancelled() is True

    def test_fu10b_not_cancelled(self):
        uploader = sync_file_uploader.FileUploader(
            client=Mock(), db=Mock(),
            cancel_check_fn=lambda: None,
        )
        assert uploader._is_cancelled() is False


class TestFileUploaderEmptyBatch:

    def test_fu11_empty_list_no_op(self):
        """upload_batch with empty list returns immediately."""
        client = Mock()
        uploader = sync_file_uploader.FileUploader(client=client, db=Mock())
        summary = {'files_uploaded': 0, 'files_failed': 0, 'file_results': []}

        uploader.upload_batch([], summary, {})

        # No background thread should have been started — client never called
        assert summary['files_uploaded'] == 0
        assert summary['files_failed'] == 0
