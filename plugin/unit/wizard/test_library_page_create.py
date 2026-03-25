"""Tests for LibraryPage — create library + UUID filter."""

from unittest.mock import Mock, patch, MagicMock
import sys


class TestLibraryPageCreateLibrary:
    """Tests for the 'Create a new library on server' feature."""

    def _make_page(self, gui=None, plugin_action=None):
        from calibre_plugins.sync_calimob.wizard.pages.library_page import LibraryPage
        return LibraryPage(gui or Mock(), plugin_action or Mock())

    def test_has_on_create_library_method(self):
        page = self._make_page()
        assert hasattr(page, '_on_create_library')
        assert callable(page._on_create_library)

    def test_create_library_calls_api(self):
        """_on_create_library_confirm should call client.create_library."""
        page = self._make_page()
        page._libraries = []
        page.library_combo = Mock()
        page.library_name_label = Mock()
        page.book_count_label = Mock()
        page.error_label = Mock()
        page.create_name_input = Mock()
        page.create_name_input.text = Mock(return_value='My New Library')
        page.create_confirm_btn = Mock()

        mock_client = MagicMock()
        mock_client.create_library.return_value = {
            'id': 'new-lib-1', 'name': 'My New Library', 'book_count': 0,
        }

        with patch.object(page, '_make_client', return_value=mock_client):
            page._on_create_library_confirm()

        mock_client.create_library.assert_called_once()
        assert len(page._libraries) == 1
        assert page._libraries[0]['name'] == 'My New Library'

    def test_create_library_empty_name_does_nothing(self):
        """Empty name should not call API."""
        page = self._make_page()
        page._libraries = []
        page.create_name_input = Mock()
        page.create_name_input.text = Mock(return_value='')

        page._on_create_library_confirm()
        assert len(page._libraries) == 0

    def test_create_library_api_error_shows_message(self):
        """API error should show error, not crash."""
        page = self._make_page()
        page._libraries = []
        page.error_label = Mock()
        page.create_name_input = Mock()
        page.create_name_input.text = Mock(return_value='Test')
        page.create_confirm_btn = Mock()

        from calibre_plugins.sync_calimob.rest_client import RestApiError
        mock_client = MagicMock()
        mock_client.create_library.side_effect = RestApiError('Server error')

        with patch.object(page, '_make_client', return_value=mock_client):
            page._on_create_library_confirm()

        assert len(page._libraries) == 0

    def test_show_create_makes_input_visible(self):
        """Clicking 'Create a new library' should show the input row."""
        page = self._make_page()
        page.create_name_input = Mock()
        page.create_confirm_btn = Mock()
        page._on_show_create('#')
        page.create_name_input.setVisible.assert_called_with(True)
        page.create_confirm_btn.setVisible.assert_called_with(True)


class TestLibraryPageUUIDFilter:
    """Tests for UUID-filtered library loading."""

    def _make_page(self):
        from calibre_plugins.sync_calimob.wizard.pages.library_page import LibraryPage
        return LibraryPage(Mock(), Mock())

    def test_load_libraries_passes_uuid(self):
        """_load_libraries should pass calibre_library_uuid to get_libraries."""
        page = self._make_page()
        page.library_combo = Mock()
        page.library_name_label = Mock()
        page.book_count_label = Mock()

        mock_client = MagicMock()
        mock_client.get_libraries.return_value = [
            {'id': 'lib-1', 'name': 'Test', 'book_count': 10},
        ]

        # Patch get_calibre_library_id in the module where it's used
        lib_utils = sys.modules.get('calibre_plugins.sync_calimob.library_utils')
        orig_fn = getattr(lib_utils, 'get_calibre_library_id', None)
        setattr(lib_utils, 'get_calibre_library_id', lambda db: 'test-uuid-123')
        try:
            with patch.object(page, '_make_client', return_value=mock_client):
                page._load_libraries()
        finally:
            if orig_fn is not None:
                setattr(lib_utils, 'get_calibre_library_id', orig_fn)

        mock_client.get_libraries.assert_called_once_with(calibre_library_uuid='test-uuid-123')
