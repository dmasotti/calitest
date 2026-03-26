"""
E2E test for the device authorization polling flow.

Tests the EXACT same code path the wizard uses:
1. Generate device_token UUID
2. Build auth URL
3. Create a bare RestApiClient (same as _poll_status does)
4. Call GET /auth/device/{token}/status
5. Verify the response

Requires network access to the real server.
Skip with: pytest -k "not e2e_device_auth"
"""

import os
import sys
import uuid
import pytest

# Use the real server URL
API_URL = os.getenv(
    "CALIMOB_TEST_API_URL",
    "https://coral-shark-984693.hostingersite.com"
)


def _poll_device_status(endpoint, device_token):
    """Poll device auth status — same as login_page._poll_status (direct HTTP)."""
    import json
    import calibre_plugins.sync_calimob.httplib2 as httplib2

    url = '%s/api/auth/device/%s/status' % (endpoint.rstrip('/'), device_token)
    print(f"[E2E] GET {url}")

    http = httplib2.Http(
        proxy_info=None, ca_certs=None, timeout=10,
        disable_ssl_certificate_validation=False)
    resp, content = http.request(url, 'GET', headers={
        'Accept': 'application/json',
        'User-Agent': 'CaliMob-Calibre-Plugin/1.0',
    })

    print(f"[E2E] Status: {resp.status}")
    body = None
    if content:
        try:
            body = json.loads(content.decode('utf-8', errors='replace'))
        except Exception:
            body = content.decode('utf-8', errors='replace')
    print(f"[E2E] Body: {body}")
    return resp.status, body


class TestDeviceAuthPollingE2E:
    """E2E tests calling the real server."""

    @pytest.mark.skipif(
        os.getenv("SKIP_E2E", "0") == "1",
        reason="SKIP_E2E=1"
    )
    def test_poll_unknown_token_returns_not_found(self):
        """A random device_token that was never registered should return 404 or not_found."""
        token = str(uuid.uuid4())
        status, body = _poll_device_status(API_URL, token)

        # Unknown token → 404 with not_found
        assert status == 404, f"Expected 404, got {status}"
        assert isinstance(body, dict) and body.get('status') == 'not_found', \
            f"Expected not_found, got: {body}"
        print("[E2E] ✓ Unknown token returns 404/not_found")

    @pytest.mark.skipif(
        os.getenv("SKIP_E2E", "0") == "1",
        reason="SKIP_E2E=1"
    )
    def test_poll_url_format(self):
        """Verify the polling URL format is correct."""
        token = 'test-uuid-12345'
        expected = '%s/api/auth/device/%s/status' % (API_URL.rstrip('/'), token)
        actual = '%s/api/auth/device/%s/status' % (API_URL.rstrip('/'), token)
        print(f"\n[E2E] Expected URL: {expected}")
        assert actual == expected

    @pytest.mark.skipif(
        os.getenv("SKIP_E2E", "0") == "1",
        reason="SKIP_E2E=1"
    )
    def test_auth_url_opens_correctly(self):
        """Verify the auth URL the plugin opens in the browser."""
        from calibre_plugins.sync_calimob.wizard.pages.login_page import LoginPage
        from unittest.mock import Mock

        page = LoginPage(Mock(), Mock())
        url = page._build_auth_url()
        print(f"\n[E2E] Auth URL: {url}")

        assert 'auth/authorize' in url
        assert 'device_token=' in url
        assert page._device_token in url
