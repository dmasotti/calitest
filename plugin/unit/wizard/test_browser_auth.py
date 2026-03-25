"""Tests for browser auth flow — device_token is the API token."""

from unittest.mock import Mock, patch, MagicMock


class TestBrowserAuthPolling:
    """Tests for _poll_browser_auth — device_token as auth token."""

    def _make_page(self):
        from calibre_plugins.sync_calimob.wizard.pages.login_page import LoginPage
        return LoginPage(Mock(), Mock())

    def test_poll_authorized_uses_device_token_as_access_token(self):
        """When poll returns 'authorized', use self._device_token as the token."""
        page = self._make_page()
        page._device_token = 'my-device-uuid-123'
        page.browser_btn = Mock()
        page.browser_status = Mock()

        mock_client = MagicMock()
        mock_client._request.return_value = (
            Mock(),
            {'status': 'authorized', 'device_name': 'Calibre Plugin'},
        )

        stored = {}
        with patch.object(page, '_make_client', return_value=mock_client):
            with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
                mp.__getitem__ = Mock(return_value=stored)
                mp.__setitem__ = Mock(side_effect=lambda k, v: stored.update({k: v}) if isinstance(v, dict) else None)
                page._poll_browser_auth()

        assert page._login_success is True
        assert page._token == 'my-device-uuid-123'

    def test_poll_authorized_saves_as_device_token_not_rest_token(self):
        """Browser flow should save to KEY_DEVICE_TOKEN, not KEY_REST_TOKEN."""
        page = self._make_page()
        page._device_token = 'device-tok-456'
        page.browser_btn = Mock()
        page.browser_status = Mock()

        mock_client = MagicMock()
        mock_client._request.return_value = (
            Mock(),
            {'status': 'authorized'},
        )

        stored = {}
        with patch.object(page, '_make_client', return_value=mock_client):
            with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
                mp.__getitem__ = Mock(return_value=stored)
                mp.__setitem__ = Mock(side_effect=lambda k, v: stored.update({k: v}) if isinstance(v, dict) else None)
                page._poll_browser_auth()

        # device_token should be stored in deviceToken key
        assert stored.get('deviceToken') == 'device-tok-456'
        # restToken should be empty (not the device token)
        assert stored.get('restToken', '') == ''

    def test_poll_pending_keeps_polling(self):
        """'pending' status should not stop polling or set success."""
        page = self._make_page()
        page._device_token = 'some-token'
        page._poll_timer = Mock()

        mock_client = MagicMock()
        mock_client._request.return_value = (
            Mock(),
            {'status': 'pending', 'message': 'Waiting for user'},
        )

        with patch.object(page, '_make_client', return_value=mock_client):
            page._poll_browser_auth()

        assert page._login_success is False
        page._poll_timer.stop.assert_not_called()

    def test_poll_expired_shows_error(self):
        """'expired' status should stop polling and show error."""
        page = self._make_page()
        page._device_token = 'expired-token'
        page._poll_timer = Mock()
        page.browser_btn = Mock()
        page.browser_status = Mock()
        page.error_label = Mock()

        mock_client = MagicMock()
        mock_client._request.return_value = (
            Mock(),
            {'status': 'expired'},
        )

        with patch.object(page, '_make_client', return_value=mock_client):
            page._poll_browser_auth()

        assert page._login_success is False
        page.browser_btn.setEnabled.assert_called_with(True)

    def test_poll_no_device_token_stops(self):
        """If device_token is None, stop immediately."""
        page = self._make_page()
        page._device_token = None
        timer_mock = Mock()
        page._poll_timer = timer_mock
        page._poll_browser_auth()
        timer_mock.stop.assert_called()
        assert page._poll_timer is None


class TestAuthSuccessTokenRouting:
    """_on_auth_success routes token to correct config key."""

    def _make_page(self):
        from calibre_plugins.sync_calimob.wizard.pages.login_page import LoginPage
        return LoginPage(Mock(), Mock())

    def test_login_saves_to_rest_token(self):
        """Login/register flow saves to KEY_REST_TOKEN."""
        page = self._make_page()
        stored = {}
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value=stored)
            mp.__setitem__ = Mock(side_effect=lambda k, v: stored.update({k: v}) if isinstance(v, dict) else None)
            page._on_auth_success({
                'access_token': 'sanctum-token-789',
                'user': {'id': 1},
            })

        assert stored.get('restToken') == 'sanctum-token-789'
        assert page._login_success is True

    def test_browser_saves_to_device_token(self):
        """Browser flow saves to KEY_DEVICE_TOKEN."""
        page = self._make_page()
        stored = {}
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value=stored)
            mp.__setitem__ = Mock(side_effect=lambda k, v: stored.update({k: v}) if isinstance(v, dict) else None)
            page._on_auth_success({
                'access_token': 'device-uuid-abc',
                'user': {'id': 2},
                'is_device_token': True,
            })

        assert stored.get('deviceToken') == 'device-uuid-abc'
        assert stored.get('restToken', '') == ''
        assert page._login_success is True
