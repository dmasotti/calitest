"""Tests for LoginPage (Screen 2) of the Sync Wizard."""

from unittest.mock import Mock, patch, MagicMock


class TestLoginPage:
    """Unit tests for LoginPage."""

    def _make_page(self, gui=None, plugin_action=None):
        from calibre_plugins.sync_calimob.wizard.pages.login_page import LoginPage
        return LoginPage(gui or Mock(), plugin_action or Mock())

    def test_page_has_email_field(self):
        page = self._make_page()
        assert hasattr(page, 'email_input')

    def test_page_has_password_field(self):
        page = self._make_page()
        assert hasattr(page, 'password_input')

    def test_page_has_login_button(self):
        page = self._make_page()
        assert hasattr(page, 'login_btn')

    def test_page_has_error_label(self):
        page = self._make_page()
        assert hasattr(page, 'error_label')

    def test_page_has_custom_server_link(self):
        page = self._make_page()
        assert hasattr(page, 'custom_server_link')

    def test_default_endpoint(self):
        page = self._make_page()
        assert page._endpoint == 'https://coral-shark-984693.hostingersite.com'

    def test_do_login_success_stores_token(self):
        """Successful login should store token and endpoint in plugin_prefs."""
        page = self._make_page()
        page.email_input = Mock()
        page.email_input.text = Mock(return_value='user@test.com')
        page.password_input = Mock()
        page.password_input.text = Mock(return_value='secret')

        mock_client = MagicMock()
        mock_client.login_and_get_token.return_value = {
            'access_token': '45|abc123',
            'user': {'id': 1, 'name': 'Test User', 'email': 'user@test.com'},
        }

        stored = {}
        with patch.object(page, '_make_client', return_value=mock_client):
            with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
                mock_prefs.__getitem__ = Mock(return_value=stored)
                mock_prefs.__setitem__ = Mock(side_effect=lambda k, v: stored.update({k: v}))
                page._do_login()

        mock_client.login_and_get_token.assert_called_once_with('user@test.com', 'secret')
        assert page._login_success is True

    def test_do_login_failure_shows_error(self):
        """Failed login should set error message and not mark success."""
        page = self._make_page()
        page.email_input = Mock()
        page.email_input.text = Mock(return_value='user@test.com')
        page.password_input = Mock()
        page.password_input.text = Mock(return_value='wrong')
        page.error_label = Mock()

        from calibre_plugins.sync_calimob.rest_client import RestApiError
        mock_client = MagicMock()
        mock_client.login_and_get_token.side_effect = RestApiError('Invalid credentials', status_code=401)

        with patch.object(page, '_make_client', return_value=mock_client):
            page._do_login()

        assert page._login_success is False

    def test_do_login_empty_fields_shows_error(self):
        """Empty email or password should show validation error."""
        page = self._make_page()
        page.email_input = Mock()
        page.email_input.text = Mock(return_value='')
        page.password_input = Mock()
        page.password_input.text = Mock(return_value='')
        page.error_label = Mock()

        page._do_login()
        assert page._login_success is False

    def test_next_id_returns_library_page(self):
        page = self._make_page()
        assert page.nextId() == 2  # PageLibrary
