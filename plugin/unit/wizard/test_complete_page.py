"""Tests for CompletePage (Screen 6 + 6b) of the Sync Wizard."""

from unittest.mock import Mock


class TestCompletePage:
    """Unit tests for CompletePage."""

    def _make_page(self, gui=None, plugin_action=None):
        from calibre_plugins.sync_calimob.wizard.pages.complete_page import CompletePage
        return CompletePage(gui or Mock(), plugin_action or Mock())

    def test_page_has_status_label(self):
        page = self._make_page()
        assert hasattr(page, 'status_label')

    def test_page_has_stat_labels(self):
        """Should have 4 stat card labels: synced, updated, skipped, issues."""
        page = self._make_page()
        assert hasattr(page, 'synced_label')
        assert hasattr(page, 'updated_label')
        assert hasattr(page, 'skipped_label')
        assert hasattr(page, 'issues_label')

    def test_page_has_done_button(self):
        page = self._make_page()
        assert hasattr(page, 'done_btn')

    def test_next_id_returns_minus_one(self):
        """CompletePage is the last page — nextId should return -1."""
        page = self._make_page()
        assert page.nextId() == -1

    def test_show_success_result(self):
        """_show_result with success data should populate stat labels."""
        page = self._make_page()
        page.synced_label = Mock()
        page.updated_label = Mock()
        page.skipped_label = Mock()
        page.issues_label = Mock()
        page.status_label = Mock()

        page._show_result({
            'synced': 1247,
            'updated': 12,
            'skipped': 5,
            'issues': 0,
        })

        page.synced_label.setText.assert_called()
        page.updated_label.setText.assert_called()

    def test_show_error_result(self):
        """_show_result with error should show warning state."""
        page = self._make_page()
        page.status_label = Mock()
        page.warning_frame = Mock()

        page._show_result({'error': 'Connection timed out'})

        page.warning_frame.setVisible.assert_called_with(True)

    def test_show_interrupted_result(self):
        """_show_result with interrupted flag should show resume options."""
        page = self._make_page()
        page.status_label = Mock()
        page.warning_frame = Mock()
        page.resume_btn = Mock()

        page._show_result({'interrupted': True, 'error': 'User cancelled'})

        page.resume_btn.setVisible.assert_called_with(True)

    def test_is_final_page(self):
        page = self._make_page()
        assert page.isFinalPage() is True
