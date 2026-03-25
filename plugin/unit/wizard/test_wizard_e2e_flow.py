"""E2E flow tests for the Sync Wizard — test page navigation logic."""

from unittest.mock import Mock, patch, MagicMock


class TestWizardFlowUnauthenticated:
    """User has NO token — first time ever."""

    def _make_wizard_pages(self):
        """Create all wizard pages with mock gui/action."""
        from calibre_plugins.sync_calimob.wizard.pages.welcome_page import WelcomePage
        from calibre_plugins.sync_calimob.wizard.pages.login_page import LoginPage
        from calibre_plugins.sync_calimob.wizard.pages.library_page import LibraryPage

        gui = Mock()
        gui.current_db = Mock()
        gui.current_db.library_path = '/tmp/test'
        action = Mock()

        return {
            'welcome': WelcomePage(gui, action),
            'login': LoginPage(gui, action),
            'library': LibraryPage(gui, action),
            'gui': gui,
            'action': action,
        }

    def test_welcome_next_goes_to_login_when_no_token(self):
        """With no token, WelcomePage.nextId() should return PageLogin (1)."""
        pages = self._make_wizard_pages()
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value={
                'restEndpoint': '',
                'restToken': '',
                'deviceToken': '',
            })
            next_id = pages['welcome'].nextId()
        assert next_id == 1, f"Expected PageLogin (1), got {next_id}"

    def test_login_next_blocked_when_not_logged_in(self):
        """LoginPage.nextId() should return -1 when user hasn't logged in.

        This prevents advancing to LibraryPage without authentication,
        which would cause a 401 → restart → infinite loop.
        """
        pages = self._make_wizard_pages()
        login = pages['login']
        assert login._login_success is False
        next_id = login.nextId()
        # Should NOT allow advancing to Library page
        assert next_id == -1 or next_id == 1, \
            f"Login page should block navigation when not authenticated, got nextId={next_id}"

    def test_login_next_goes_to_library_after_success(self):
        """After successful login, LoginPage.nextId() should return PageLibrary (2)."""
        pages = self._make_wizard_pages()
        login = pages['login']
        login._login_success = True
        next_id = login.nextId()
        assert next_id == 2, f"Expected PageLibrary (2), got {next_id}"


class TestWizardFlowExpiredToken:
    """User has a token but it's expired/invalid."""

    def test_welcome_skips_to_library_with_existing_token(self):
        """If token exists, WelcomePage skips to Library."""
        from calibre_plugins.sync_calimob.wizard.pages.welcome_page import WelcomePage
        page = WelcomePage(Mock(), Mock())
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value={
                'restEndpoint': 'https://example.com',
                'restToken': 'old-token',
                'deviceToken': '',
            })
            next_id = page.nextId()
        assert next_id == 2, "Should skip to Library when token exists"

    def test_library_auth_failure_goes_to_login_not_loop(self):
        """When Library gets 401, it should go to Login, not create a loop.

        The flow should be:
        1. Library page gets 401
        2. Marks token invalid
        3. Navigates to Login page (not restart → Welcome → Library → 401 loop)
        """
        from calibre_plugins.sync_calimob.wizard.pages.library_page import LibraryPage
        from calibre_plugins.sync_calimob.rest_client import RestApiError

        gui = Mock()
        gui.current_db = Mock()
        action = Mock()
        page = LibraryPage(gui, action)

        mock_client = MagicMock()
        mock_client.get_libraries.side_effect = RestApiError(
            'Authentication failed', status_code=401)

        # Mock wizard
        mock_wizard = Mock()
        mock_login_page = Mock()
        mock_wizard.page.return_value = mock_login_page

        with patch.object(page, 'wizard', return_value=mock_wizard):
            with patch.object(page, '_make_client', return_value=mock_client):
                page.error_label = Mock()
                page.library_name_label = Mock()
                page.book_count_label = Mock()
                page._load_libraries()

        # Should navigate directly to login page (not restart which loops)
        mock_wizard._set_page.assert_called_with(1)


class TestWizardFlowComplete:
    """Happy path — authenticated user goes through all pages."""

    def test_welcome_to_library_skipping_login(self):
        """Configured user: Welcome → Library (skip Login)."""
        from calibre_plugins.sync_calimob.wizard.pages.welcome_page import WelcomePage
        page = WelcomePage(Mock(), Mock())
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mp:
            mp.__getitem__ = Mock(return_value={
                'restEndpoint': 'https://api.test',
                'restToken': 'valid-token',
                'deviceToken': '',
            })
            assert page.nextId() == 2  # PageLibrary

    def test_library_next_goes_to_ready(self):
        from calibre_plugins.sync_calimob.wizard.pages.library_page import LibraryPage
        page = LibraryPage(Mock(), Mock())
        assert page.nextId() == 3  # PageReady

    def test_ready_next_goes_to_progress(self):
        from calibre_plugins.sync_calimob.wizard.pages.ready_page import ReadyPage
        page = ReadyPage(Mock(), Mock())
        assert page.nextId() == 4  # PageProgress

    def test_progress_next_goes_to_complete(self):
        from calibre_plugins.sync_calimob.wizard.pages.progress_page import ProgressPage
        page = ProgressPage(Mock(), Mock())
        assert page.nextId() == 5  # PageComplete

    def test_complete_next_is_last(self):
        from calibre_plugins.sync_calimob.wizard.pages.complete_page import CompletePage
        page = CompletePage(Mock(), Mock())
        assert page.nextId() == -1  # Last page
