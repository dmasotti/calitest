"""Tests for ProgressPage (Screen 5) of the Sync Wizard."""

from unittest.mock import Mock, patch, MagicMock


class TestProgressPage:
    """Unit tests for ProgressPage."""

    def _make_page(self, gui=None, plugin_action=None):
        from calibre_plugins.sync_calimob.wizard.pages.progress_page import ProgressPage
        return ProgressPage(gui or Mock(), plugin_action or Mock())

    def test_page_has_progress_bar(self):
        page = self._make_page()
        assert hasattr(page, 'progress_bar')

    def test_page_has_status_label(self):
        page = self._make_page()
        assert hasattr(page, 'status_label')

    def test_page_has_detail_toggle(self):
        page = self._make_page()
        assert hasattr(page, 'detail_toggle')

    def test_page_has_log_area(self):
        page = self._make_page()
        assert hasattr(page, 'log_area')

    def test_page_has_background_button(self):
        page = self._make_page()
        assert hasattr(page, 'background_btn')

    def test_page_has_cancel_button(self):
        page = self._make_page()
        assert hasattr(page, 'cancel_btn')

    def test_next_id_returns_complete_page(self):
        page = self._make_page()
        assert page.nextId() == 5  # PageComplete

    def test_on_progress_updates_bar(self):
        """Progress callback should update the progress bar value."""
        page = self._make_page()
        page.progress_bar = Mock()
        page.status_label = Mock()
        page.log_area = Mock()
        page.on_progress('Collecting local changes...', 50, 100)
        page.progress_bar.setValue.assert_called()

    def test_on_progress_appends_log(self):
        """Progress callback should append to log area."""
        page = self._make_page()
        page.log_area = Mock()
        page.progress_bar = Mock()
        page.status_label = Mock()
        page.on_progress('Hashing books...', 10, 100)
        page.log_area.append.assert_called()

    def test_on_sync_complete_transitions(self):
        """Sync completion should mark page as done."""
        page = self._make_page()
        page.progress_bar = Mock()
        page.status_label = Mock()
        page.background_btn = Mock()
        page.cancel_btn = Mock()
        page.on_sync_complete({'synced': 100, 'updated': 5, 'skipped': 3, 'issues': 0})
        assert page._sync_done is True

    def test_on_sync_error_transitions(self):
        """Sync error should mark page as done with error."""
        page = self._make_page()
        page.status_label = Mock()
        page.background_btn = Mock()
        page.cancel_btn = Mock()
        page.on_sync_error('Connection failed')
        assert page._sync_done is True
        assert page._sync_result.get('error') == 'Connection failed'

    def test_on_cancel_disables_button(self):
        """Cancel should disable the cancel button."""
        page = self._make_page()
        page.cancel_btn = Mock()
        page._runner = Mock()
        page._on_cancel()
        page.cancel_btn.setEnabled.assert_called_with(False)
        page._runner.cancel.assert_called_once()

    def test_toggle_details_expands(self):
        """Toggling details should change max height."""
        page = self._make_page()
        page.log_area = Mock()
        page.log_area.maximumHeight = Mock(return_value=0)
        page.detail_toggle = Mock()
        page._on_toggle_details()
        page.log_area.setMaximumHeight.assert_called_with(200)

    def test_toggle_details_collapses(self):
        """Toggling when expanded should collapse."""
        page = self._make_page()
        page.log_area = Mock()
        page.log_area.maximumHeight = Mock(return_value=200)
        page.detail_toggle = Mock()
        page._on_toggle_details()
        page.log_area.setMaximumHeight.assert_called_with(0)
