"""Tests for ReadyPage (Screen 4) of the Sync Wizard."""

from unittest.mock import Mock, patch


class TestReadyPage:
    """Unit tests for ReadyPage."""

    def _make_page(self, gui=None, plugin_action=None):
        from calibre_plugins.sync_calimob.wizard.pages.ready_page import ReadyPage
        return ReadyPage(gui or Mock(), plugin_action or Mock())

    def test_page_has_status_label(self):
        page = self._make_page()
        assert hasattr(page, 'status_label')

    def test_page_has_library_label(self):
        page = self._make_page()
        assert hasattr(page, 'library_label')

    def test_page_has_start_sync_button(self):
        page = self._make_page()
        assert hasattr(page, 'start_sync_btn')

    def test_page_has_advanced_link(self):
        page = self._make_page()
        assert hasattr(page, 'advanced_link')

    def test_next_id_returns_progress_page(self):
        page = self._make_page()
        assert page.nextId() == 4  # PageProgress

    def test_on_start_sync_sets_started(self):
        page = self._make_page()
        page._save_mappings = Mock()
        page._on_start_sync()
        assert page._sync_started is True

    # --- Status tag mapping widgets ---

    def test_has_status_tag_combos(self):
        page = self._make_page()
        assert hasattr(page, 'status_tag_tbr')
        assert hasattr(page, 'status_tag_reading')
        assert hasattr(page, 'status_tag_finished')
        assert hasattr(page, 'status_tag_abandoned')

    def test_has_custom_column_combos(self):
        page = self._make_page()
        assert hasattr(page, 'progress_percent_combo')
        assert hasattr(page, 'favorite_combo')

    def test_tags_section_collapsed_by_default(self):
        page = self._make_page()
        assert not page._tags_frame.isVisible()

    def test_cols_section_collapsed_by_default(self):
        page = self._make_page()
        assert not page._cols_frame.isVisible()

    def test_toggle_tags_calls_setVisible(self):
        page = self._make_page()
        page._tags_frame = Mock()
        page._tags_frame.isVisible = Mock(return_value=False)
        page._tags_toggle = Mock()
        page._on_toggle_tags()
        page._tags_frame.setVisible.assert_called_with(True)

    def test_toggle_tags_collapses(self):
        page = self._make_page()
        page._tags_frame = Mock()
        page._tags_frame.isVisible = Mock(return_value=True)
        page._tags_toggle = Mock()
        page._on_toggle_tags()
        page._tags_frame.setVisible.assert_called_with(False)

    def test_toggle_cols_calls_setVisible(self):
        page = self._make_page()
        page._cols_frame = Mock()
        page._cols_frame.isVisible = Mock(return_value=False)
        page._cols_toggle = Mock()
        page._on_toggle_cols()
        page._cols_frame.setVisible.assert_called_with(True)

    def test_start_sync_saves_mappings(self):
        page = self._make_page()
        page._save_mappings = Mock()
        page._on_start_sync()
        page._save_mappings.assert_called_once()
