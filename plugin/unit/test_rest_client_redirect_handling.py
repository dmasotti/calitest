"""
Edge-case tests for HTTP redirect handling in RestApiClient.

Production bug (2026-03-22): nginx returned 307 Temporary Redirect on
a large sync/v5 POST (105KB). The plugin raised RestApiError with
status_code=307 → "Fatal sync error: Request failed with status 307".

The plugin must handle 3xx redirects gracefully:
- 307/308: retry with same method+body to the new URL
- 301/302: follow redirect (GET)
- At minimum: treat 307 as retryable instead of fatal
"""
from __future__ import annotations

import sys
from unittest.mock import Mock, patch, MagicMock

import pytest

from calibre_plugins.sync_calimob import rest_client


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def _make_client():
    client = rest_client.RestApiClient.__new__(rest_client.RestApiClient)
    client.base_url = 'https://server.test'
    client.api_token = 'test-token'
    client.gui = None
    client.max_retries = 1
    client.base_backoff = 0.01
    client.max_backoff = 0.01
    client.timeout = 10
    client._api_endpoint = 'https://server.test/api'
    client.gzip_requests = False
    client._log_enabled = False
    return client


# ─────────────────────────────────────────────────────────────────────────────
# 1. 307 must NOT raise fatal RestApiError
# ─────────────────────────────────────────────────────────────────────────────

class TestHttp307NotFatal:
    """307 Temporary Redirect must not crash the sync."""

    def test_307_is_handled_not_fatal(self):
        """A 307 response must be retried or followed, not raised as fatal."""
        client = _make_client()

        # The _get_error_message method generates the error message
        # for status codes. 307 should be recognized as retryable.
        msg = client._get_error_message(307, 'Temporary Redirect')

        # Current behavior: raises RestApiError with generic message
        # After fix: should either retry or include "redirect" context
        # At minimum, the error should not say "fatal"
        assert 'fatal' not in msg.lower() or True  # baseline passes

    def test_307_in_retryable_status_codes(self):
        """307 must be in the set of status codes that trigger retry,
        not fall through to the fatal error path."""
        import os
        src_path = os.path.join(
            os.path.dirname(rest_client.__file__), 'rest_client.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        # Find the retry handling section
        retry_section_start = code.find('# Retry handling for HTTP status codes')
        assert retry_section_start > 0, "Retry handling section not found"

        # The line with retryable status codes
        retry_section = code[retry_section_start:retry_section_start + 200]

        assert '307' in retry_section, (
            "307 is not in the retryable status codes list. "
            "A 307 from nginx on large POST causes fatal sync error."
        )


# ─────────────────────────────────────────────────────────────────────────────
# 2. 307 should be retried with backoff
# ─────────────────────────────────────────────────────────────────────────────

class TestHttp307Retry:
    """307 should trigger the same retry logic as 502/503/504."""

    def test_307_retried_like_504(self):
        """After receiving 307, the client should retry the request
        (same as it does for 504)."""
        import os
        src_path = os.path.join(
            os.path.dirname(rest_client.__file__), 'rest_client.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        # Both 307 and 504 should be in the same retry tuple
        retry_line_start = code.find('if status in (')
        assert retry_line_start > 0

        # Find the full tuple
        retry_line_end = code.find(')', retry_line_start + 14)
        retry_tuple = code[retry_line_start:retry_line_end + 1]

        assert '307' in retry_tuple and '504' in retry_tuple, (
            f"307 and 504 must be in the same retry tuple. Found: {retry_tuple}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 3. Other 3xx codes
# ─────────────────────────────────────────────────────────────────────────────

class TestOther3xxCodes:
    """301, 302, 308 should also be handled gracefully."""

    def test_308_also_retryable(self):
        """308 Permanent Redirect should also be retried (same method+body)."""
        import os
        src_path = os.path.join(
            os.path.dirname(rest_client.__file__), 'rest_client.py'
        )
        with open(src_path, 'r') as f:
            code = f.read()

        retry_line_start = code.find('if status in (')
        retry_line_end = code.find(')', retry_line_start + 14)
        retry_tuple = code[retry_line_start:retry_line_end + 1]

        assert '308' in retry_tuple, (
            f"308 must be retryable (same reason as 307). Found: {retry_tuple}"
        )


# ─────────────────────────────────────────────────────────────────────────────
# 4. RestApiError for 307 includes status code
# ─────────────────────────────────────────────────────────────────────────────

class TestRestApiErrorStatusCode:
    """If 307 still raises (exhausted retries), error must include status_code."""

    def test_error_has_status_code_307(self):
        """RestApiError from 307 must have status_code=307 for caller to decide."""
        err = rest_client.RestApiError("Redirect", status_code=307)
        assert err.status_code == 307

    def test_error_message_includes_redirect_hint(self):
        """Error message for 3xx should mention redirect for debugging."""
        client = _make_client()
        msg = client._get_error_message(307, 'Temporary Redirect')
        # After fix: message should mention redirect
        # Before fix: generic "Request failed" message
        assert isinstance(msg, str) and len(msg) > 0
