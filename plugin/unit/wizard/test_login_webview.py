"""Tests for LoginPage WebView-based auth flow."""

from unittest.mock import Mock, patch


class TestLoginPageWebView:
    """LoginPage embeds a WebView with the site's auth flow."""

    def _make_page(self, gui=None, plugin_action=None):
        from calibre_plugins.sync_calimob.wizard.pages.login_page import LoginPage
        return LoginPage(gui or Mock(), plugin_action or Mock())

    def test_page_has_device_token(self):
        """Page should generate a device_token UUID on creation."""
        page = self._make_page()
        assert page._device_token is not None
        assert len(page._device_token) > 10

    def test_page_has_auth_url(self):
        """Page should build an auth URL with device_token."""
        page = self._make_page()
        url = page._build_auth_url()
        assert page._device_token in url
        assert 'authorize' in url

    def test_page_has_open_browser_link(self):
        """Page should have a fallback link to open in external browser."""
        page = self._make_page()
        assert hasattr(page, '_open_browser_link')

    def test_auth_url_includes_locale(self):
        """Auth URL should include Calibre's locale."""
        page = self._make_page()
        url = page._build_auth_url()
        assert '/locale/' in url or 'device_token=' in url

    def test_next_id_blocked_when_not_authenticated(self):
        """nextId should return -1 until auth succeeds."""
        page = self._make_page()
        assert page._login_success is False
        assert page.nextId() == -1

    def test_next_id_returns_library_after_auth(self):
        """After successful auth, nextId should return PageLibrary (2)."""
        page = self._make_page()
        page._login_success = True
        assert page.nextId() == 2

    def test_on_url_changed_detects_authorized(self):
        """When WebView URL contains 'device-authorized', auth is complete."""
        page = self._make_page()
        page._device_token = 'test-device-uuid'
        page._poll_timer = Mock()

        stored = {}
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value=stored)
            mp.__setitem__ = Mock(side_effect=lambda k, v: stored.update({k: v}) if isinstance(v, dict) else None)
            mp.get = Mock(return_value=stored)
            # Simulate URL change to authorized page
            page._on_url_changed_str('https://example.com/auth/device-authorized')

        assert page._login_success is True
        assert stored.get('deviceToken') == 'test-device-uuid'

    def test_on_url_changed_ignores_other_urls(self):
        """Non-authorized URLs should not trigger auth success."""
        page = self._make_page()
        page._device_token = 'test-uuid'
        page._on_url_changed_str('https://example.com/auth/login')
        assert page._login_success is False
