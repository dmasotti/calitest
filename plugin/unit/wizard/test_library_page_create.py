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
        """_on_create_library should call client.create_library."""
        page = self._make_page()
        page._libraries = []
        page.library_combo = Mock()
        page.library_name_label = Mock()
        page.book_count_label = Mock()
        page.error_label = Mock()

        mock_client = MagicMock()
        mock_client.create_library.return_value = {
            'id': 'new-lib-1', 'name': 'My New Library', 'book_count': 0,
        }

        # Mock QInputDialog at the module level where it's imported
        mock_dlg = MagicMock()
        mock_dlg.getText.return_value = ('My New Library', True)
        qt_core = sys.modules.get('qt.core')
        orig = getattr(qt_core, 'QInputDialog', None)
        setattr(qt_core, 'QInputDialog', mock_dlg)
        try:
            with patch.object(page, '_make_client', return_value=mock_client):
                page._on_create_library('#')
        finally:
            if orig is not None:
                setattr(qt_core, 'QInputDialog', orig)

        mock_client.create_library.assert_called_once()
        assert len(page._libraries) == 1
        assert page._libraries[0]['name'] == 'My New Library'

    def test_create_library_cancelled_does_nothing(self):
        """If user cancels, no API call."""
        page = self._make_page()
        page._libraries = []

        mock_dlg = MagicMock()
        mock_dlg.getText.return_value = ('', False)
        qt_core = sys.modules.get('qt.core')
        orig = getattr(qt_core, 'QInputDialog', None)
        setattr(qt_core, 'QInputDialog', mock_dlg)
        try:
            page._on_create_library('#')
        finally:
            if orig is not None:
                setattr(qt_core, 'QInputDialog', orig)

        assert len(page._libraries) == 0

    def test_create_library_api_error_shows_message(self):
        """API error should show error, not crash."""
        page = self._make_page()
        page._libraries = []
        page.error_label = Mock()

        from calibre_plugins.sync_calimob.rest_client import RestApiError
        mock_client = MagicMock()
        mock_client.create_library.side_effect = RestApiError('Server error')

        mock_dlg = MagicMock()
        mock_dlg.getText.return_value = ('Test', True)
        qt_core = sys.modules.get('qt.core')
        orig = getattr(qt_core, 'QInputDialog', None)
        setattr(qt_core, 'QInputDialog', mock_dlg)
        try:
            with patch.object(page, '_make_client', return_value=mock_client):
                page._on_create_library('#')
        finally:
            if orig is not None:
                setattr(qt_core, 'QInputDialog', orig)

        assert len(page._libraries) == 0


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
