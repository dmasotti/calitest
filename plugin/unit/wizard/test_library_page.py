"""Tests for LibraryPage (Screen 3) of the Sync Wizard."""

from unittest.mock import Mock, patch, MagicMock


class TestLibraryPage:
    """Unit tests for LibraryPage."""

    def _make_page(self, gui=None, plugin_action=None):
        from calibre_plugins.sync_calimob.wizard.pages.library_page import LibraryPage
        return LibraryPage(gui or Mock(), plugin_action or Mock())

    def test_page_has_library_name_label(self):
        page = self._make_page()
        assert hasattr(page, 'library_name_label')

    def test_page_has_book_count_label(self):
        page = self._make_page()
        assert hasattr(page, 'book_count_label')

    def test_page_has_continue_button(self):
        page = self._make_page()
        assert hasattr(page, 'continue_btn')

    def test_page_has_library_combo(self):
        page = self._make_page()
        assert hasattr(page, 'library_combo')

    def test_next_id_returns_ready_page(self):
        page = self._make_page()
        assert page.nextId() == 3  # PageReady

    def test_load_libraries_populates_combo(self):
        """_load_libraries should populate combo with server libraries."""
        page = self._make_page()
        page.library_combo = Mock()

        mock_client = MagicMock()
        mock_client.get_libraries.return_value = [
            {'id': 'lib-1', 'name': 'My Library', 'book_count': 1247},
            {'id': 'lib-2', 'name': 'Work Library', 'book_count': 42},
        ]

        with patch.object(page, '_make_client', return_value=mock_client):
            page._load_libraries()

        assert page._libraries is not None
        assert len(page._libraries) == 2
        assert page._libraries[0]['name'] == 'My Library'

    def test_load_libraries_handles_empty_response(self):
        """Empty library list should be handled gracefully."""
        page = self._make_page()
        page.library_combo = Mock()

        mock_client = MagicMock()
        mock_client.get_libraries.return_value = []

        with patch.object(page, '_make_client', return_value=mock_client):
            page._load_libraries()

        assert page._libraries == []

    def test_load_libraries_handles_api_error(self):
        """API error during library fetch should show error."""
        page = self._make_page()
        page.library_combo = Mock()
        page.error_label = Mock()

        from calibre_plugins.sync_calimob.rest_client import RestApiError
        mock_client = MagicMock()
        mock_client.get_libraries.side_effect = RestApiError('Network error')

        with patch.object(page, '_make_client', return_value=mock_client):
            page._load_libraries()

        assert page._libraries == []

    def test_confirm_saves_library_mapping(self):
        """Confirming a library should save calimob_library_id to config."""
        page = self._make_page()
        page._libraries = [
            {'id': 'lib-1', 'name': 'My Library', 'book_count': 1247},
        ]
        page._selected_library = page._libraries[0]
        page.library_combo = Mock()
        page.library_combo.currentIndex = Mock(return_value=0)

        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
            mappings = {}
            mock_prefs.__getitem__ = Mock(return_value=mappings)
            mock_prefs.__setitem__ = Mock(side_effect=lambda k, v: mappings.update({k: v}) if isinstance(v, dict) else None)
            page._on_confirm()

        assert page._confirmed is True
