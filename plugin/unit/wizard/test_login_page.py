"""Tests for LoginPage (Screen 2) — 3-tab: Sign in / Create account / Browser."""

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

    def test_page_has_register_fields(self):
        page = self._make_page()
        assert hasattr(page, 'reg_name_input')
        assert hasattr(page, 'reg_email_input')
        assert hasattr(page, 'reg_password_input')
        assert hasattr(page, 'register_btn')

    def test_page_has_browser_button(self):
        page = self._make_page()
        assert hasattr(page, 'browser_btn')

    def test_page_has_tab_buttons(self):
        page = self._make_page()
        assert hasattr(page, '_tab_signin_btn')
        assert hasattr(page, '_tab_register_btn')
        assert hasattr(page, '_tab_browser_btn')

    def test_page_has_error_label(self):
        page = self._make_page()
        assert hasattr(page, 'error_label')

    def test_page_has_custom_server_link(self):
        page = self._make_page()
        assert hasattr(page, 'custom_server_link')

    def test_page_has_site_link(self):
        page = self._make_page()
        assert hasattr(page, '_site_link')

    def test_default_endpoint(self):
        page = self._make_page()
        assert page._endpoint == 'https://coral-shark-984693.hostingersite.com'

    def test_next_id_blocked_when_not_logged_in(self):
        page = self._make_page()
        assert page.nextId() == -1  # Blocked — must login first

    def test_next_id_returns_library_after_login(self):
        page = self._make_page()
        page._login_success = True
        assert page.nextId() == 2  # PageLibrary

    def test_switch_tab_changes_stack(self):
        page = self._make_page()
        page._stack = Mock()
        page._tab_signin_btn = Mock()
        page._tab_register_btn = Mock()
        page._tab_browser_btn = Mock()
        page.error_label = Mock()
        page._switch_tab(1)
        page._stack.setCurrentIndex.assert_called_with(1)

    def test_do_login_success_stores_token(self):
        """Successful login should store token and advance."""
        page = self._make_page()
        page.email_input = Mock()
        page.email_input.text = Mock(return_value='user@test.com')
        page.password_input = Mock()
        page.password_input.text = Mock(return_value='secret')
        page.login_btn = Mock()

        mock_client = MagicMock()
        mock_client.login_and_get_token.return_value = {
            'access_token': '45|abc123',
            'user': {'id': 1, 'name': 'Test User'},
        }

        stored = {}
        with patch.object(page, '_make_client', return_value=mock_client):
            with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
                mp.__getitem__ = Mock(return_value=stored)
                mp.__setitem__ = Mock(side_effect=lambda k, v: stored.update({k: v}) if isinstance(v, dict) else None)
                page._do_login()

        mock_client.login_and_get_token.assert_called_once_with('user@test.com', 'secret')
        assert page._login_success is True

    def test_do_login_failure_shows_error(self):
        """Failed login should show error."""
        page = self._make_page()
        page.email_input = Mock()
        page.email_input.text = Mock(return_value='user@test.com')
        page.password_input = Mock()
        page.password_input.text = Mock(return_value='wrong')
        page.login_btn = Mock()
        page.error_label = Mock()

        from calibre_plugins.sync_calimob.rest_client import RestApiError
        mock_client = MagicMock()
        mock_client.login_and_get_token.side_effect = RestApiError('Invalid', status_code=401)

        with patch.object(page, '_make_client', return_value=mock_client):
            page._do_login()

        assert page._login_success is False

    def test_do_login_empty_fields_shows_error(self):
        page = self._make_page()
        page.email_input = Mock()
        page.email_input.text = Mock(return_value='')
        page.password_input = Mock()
        page.password_input.text = Mock(return_value='')
        page.error_label = Mock()
        page._do_login()
        assert page._login_success is False

    def test_do_register_success(self):
        """Successful registration should store token."""
        page = self._make_page()
        page.reg_name_input = Mock()
        page.reg_name_input.text = Mock(return_value='Marco')
        page.reg_email_input = Mock()
        page.reg_email_input.text = Mock(return_value='marco@test.com')
        page.reg_password_input = Mock()
        page.reg_password_input.text = Mock(return_value='password123')
        page.register_btn = Mock()

        mock_client = MagicMock()
        mock_client.register_and_get_token.return_value = {
            'access_token': '45|new123',
            'user': {'id': 2, 'name': 'Marco'},
        }

        stored = {}
        with patch.object(page, '_make_client', return_value=mock_client):
            with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
                mp.__getitem__ = Mock(return_value=stored)
                mp.__setitem__ = Mock(side_effect=lambda k, v: stored.update({k: v}) if isinstance(v, dict) else None)
                page._do_register()

        mock_client.register_and_get_token.assert_called_once_with('Marco', 'marco@test.com', 'password123')
        assert page._login_success is True

    def test_do_register_empty_fields(self):
        page = self._make_page()
        page.reg_name_input = Mock()
        page.reg_name_input.text = Mock(return_value='')
        page.reg_email_input = Mock()
        page.reg_email_input.text = Mock(return_value='')
        page.reg_password_input = Mock()
        page.reg_password_input.text = Mock(return_value='')
        page.error_label = Mock()
        page._do_register()
        assert page._login_success is False

    def test_do_register_short_password(self):
        page = self._make_page()
        page.reg_name_input = Mock()
        page.reg_name_input.text = Mock(return_value='Marco')
        page.reg_email_input = Mock()
        page.reg_email_input.text = Mock(return_value='marco@test.com')
        page.reg_password_input = Mock()
        page.reg_password_input.text = Mock(return_value='short')
        page.error_label = Mock()
        page._do_register()
        assert page._login_success is False

    def test_get_calibre_lang_fallback(self):
        page = self._make_page()
        lang = page._get_calibre_lang()
        assert isinstance(lang, str)
        assert len(lang) >= 2
