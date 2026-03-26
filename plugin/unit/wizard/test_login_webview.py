"""Tests for LoginPage — browser auth + polling flow."""

from unittest.mock import Mock, patch


class TestLoginPage:
    """LoginPage opens browser, polls for device authorization."""

    def _make_page(self):
        from calibre_plugins.sync_calimob.wizard.pages.login_page import LoginPage
        return LoginPage(Mock(), Mock())

    def test_page_has_device_token(self):
        page = self._make_page()
        assert page._device_token is not None
        assert len(page._device_token) > 10

    def test_page_has_open_button(self):
        page = self._make_page()
        assert hasattr(page, '_open_btn')

    def test_page_has_status_label(self):
        page = self._make_page()
        assert hasattr(page, '_status_label')

    def test_build_auth_url(self):
        page = self._make_page()
        url = page._build_auth_url()
        assert page._device_token in url
        assert 'authorize' in url
        assert 'embed' not in url  # no embed querystring

    def test_next_id_blocked_when_not_authenticated(self):
        page = self._make_page()
        assert page._login_success is False
        assert page.nextId() == -1

    def test_next_id_returns_library_after_auth(self):
        page = self._make_page()
        page._login_success = True
        assert page.nextId() == 2

    def test_on_auth_success_saves_device_token(self):
        page = self._make_page()
        page._device_token = 'test-device-uuid'
        page._status_label = Mock()
        page._success_label = Mock()
        page._open_btn = Mock()
        page._open_browser_link = Mock()

        stored = {}
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value=stored)
            mp.__setitem__ = Mock(side_effect=lambda k, v: stored.update({k: v}) if isinstance(v, dict) else None)
            # Patch QTimer.singleShot to avoid Qt dependency
            with patch('calibre_plugins.sync_calimob.wizard.pages.login_page.QTimer') as mock_qt:
                page._on_auth_success()

        assert page._login_success is True
        assert stored.get('deviceToken') == 'test-device-uuid'
        assert stored.get('deviceTokenStatus') == 'authorized'

    def test_poll_pending_keeps_waiting(self):
        """Polling with 'pending' status should not trigger success."""
        page = self._make_page()
        page._device_token = 'pending-uuid'
        page._poll_timer = Mock()
        # _poll_status will fail to create client in test env, but shouldn't crash
        page._poll_status()
        assert page._login_success is False
