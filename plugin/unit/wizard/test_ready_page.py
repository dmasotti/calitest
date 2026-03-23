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

    def test_page_has_sync_all_radio(self):
        page = self._make_page()
        assert hasattr(page, 'sync_all_radio')

    def test_page_has_sync_selected_radio(self):
        page = self._make_page()
        assert hasattr(page, 'sync_selected_radio')

    def test_page_has_start_sync_button(self):
        page = self._make_page()
        assert hasattr(page, 'start_sync_btn')

    def test_page_has_advanced_link(self):
        page = self._make_page()
        assert hasattr(page, 'advanced_link')

    def test_next_id_returns_progress_page(self):
        page = self._make_page()
        assert page.nextId() == 4  # PageProgress

    def test_sync_mode_defaults_to_all(self):
        page = self._make_page()
        assert page._sync_mode == 'all'

    def test_on_start_sync_sets_started(self):
        page = self._make_page()
        page._on_start_sync()
        assert page._sync_started is True
