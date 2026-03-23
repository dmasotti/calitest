"""Tests for ProgressPage (Screen 5) of the Sync Wizard."""

from unittest.mock import Mock


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

    def test_next_id_returns_complete_page(self):
        page = self._make_page()
        assert page.nextId() == 5  # PageComplete

    def test_on_progress_updates_bar(self):
        """Progress callback should update the progress bar value."""
        page = self._make_page()
        page.progress_bar = Mock()
        page.status_label = Mock()
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
        page.on_sync_complete({'synced': 100, 'updated': 5, 'skipped': 3, 'issues': 0})
        assert page._sync_done is True

    def test_toggle_details_visibility(self):
        """Toggling details should flip log area visibility."""
        page = self._make_page()
        page.log_area = Mock()
        page.log_area.isVisible = Mock(return_value=False)
        page._on_toggle_details()
        page.log_area.setVisible.assert_called_with(True)
