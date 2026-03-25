"""Regression tests for the login-library loop bug.

Scenario: user has leftover token that's expired/invalid.
WelcomePage skips to Library → 401 → restart → WelcomePage skips again → LOOP.
"""

from unittest.mock import Mock, patch


class TestWelcomePageTokenValidation:
    """WelcomePage._is_configured must check token STATUS, not just presence."""

    def _make_welcome(self):
        from calibre_plugins.sync_calimob.wizard.pages.welcome_page import WelcomePage
        return WelcomePage(Mock(), Mock())

    def test_invalid_token_status_means_not_configured(self):
        """Token exists but status='invalid' → NOT configured → go to Login."""
        page = self._make_welcome()
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value={
                'restEndpoint': 'https://example.com',
                'restToken': 'expired-token-xyz',
                'deviceToken': '',
                'deviceTokenStatus': 'invalid',
            })
            assert page._is_configured() is False
            assert page.nextId() == 1  # PageLogin, NOT PageLibrary

    def test_authorized_token_means_configured(self):
        """Token exists and status='authorized' → configured → skip to Library."""
        page = self._make_welcome()
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value={
                'restEndpoint': 'https://example.com',
                'restToken': 'good-token',
                'deviceToken': '',
                'deviceTokenStatus': 'authorized',
            })
            assert page._is_configured() is True
            assert page.nextId() == 2  # PageLibrary

    def test_unknown_token_status_means_configured(self):
        """Token exists and status='unknown' → treat as configured (will verify later)."""
        page = self._make_welcome()
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value={
                'restEndpoint': 'https://example.com',
                'restToken': 'some-token',
                'deviceToken': '',
                'deviceTokenStatus': 'unknown',
            })
            assert page._is_configured() is True

    def test_no_token_means_not_configured(self):
        """No token at all → not configured."""
        page = self._make_welcome()
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value={
                'restEndpoint': 'https://example.com',
                'restToken': '',
                'deviceToken': '',
                'deviceTokenStatus': 'unknown',
            })
            assert page._is_configured() is False


class TestLibraryAuthFailureNavigation:
    """Library page 401 should go DIRECTLY to Login, not restart wizard."""

    def test_auth_failure_navigates_to_login_page_directly(self):
        """On 401, library page should call wizard._set_page(1), not restart."""
        from calibre_plugins.sync_calimob.wizard.pages.library_page import LibraryPage
        from calibre_plugins.sync_calimob.rest_client import RestApiError

        page = LibraryPage(Mock(), Mock())
        page.error_label = Mock()
        page.library_name_label = Mock()
        page.book_count_label = Mock()

        mock_client = Mock()
        mock_client.get_libraries.side_effect = RestApiError('Auth failed', status_code=401)

        mock_wizard = Mock()
        mock_login_page = Mock()
        mock_wizard.page.return_value = mock_login_page

        with patch.object(page, 'wizard', return_value=mock_wizard):
            with patch.object(page, '_make_client', return_value=mock_client):
                page._load_libraries()

        # Should navigate to login page (index 1), NOT restart
        mock_wizard._set_page.assert_called_with(1)
        # Should NOT call restart (which causes the loop)
        mock_wizard.restart.assert_not_called()
