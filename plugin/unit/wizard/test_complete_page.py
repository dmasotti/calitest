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
        """Should have 4 stat card number labels."""
        page = self._make_page()
        assert hasattr(page, 'synced_label')
        assert hasattr(page, 'updated_label')
        assert hasattr(page, 'skipped_label')
        assert hasattr(page, 'issues_label')

    def test_stat_labels_are_qlabels_not_frames(self):
        """Stat labels must be the inner QLabel, not the QFrame card."""
        page = self._make_page()
        # The labels should have setText (QLabel), not be QFrames
        assert hasattr(page.synced_label, 'setText')

    def test_page_has_done_button(self):
        page = self._make_page()
        assert hasattr(page, 'done_btn')

    def test_next_id_returns_minus_one(self):
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
        page.warning_frame = Mock()

        page._show_result({
            'synced': 1247,
            'updated': 12,
            'skipped': 5,
            'issues': 0,
        })

        page.synced_label.setText.assert_called_with('1247')
        page.updated_label.setText.assert_called_with('12')
        page.skipped_label.setText.assert_called_with('5')
        page.issues_label.setText.assert_called_with('0')

    def test_show_error_result(self):
        """_show_result with error should show warning, not update stats."""
        page = self._make_page()
        page.status_label = Mock()
        page.warning_frame = Mock()
        page.warning_label = Mock()
        page.resume_btn = Mock()
        page.restart_btn = Mock()

        page._show_result({'error': 'Connection timed out'})

        page.warning_frame.setVisible.assert_called_with(True)
        page.warning_label.setText.assert_called_with('Connection timed out')

    def test_show_interrupted_result(self):
        """_show_result with interrupted flag should show resume options."""
        page = self._make_page()
        page.status_label = Mock()
        page.warning_frame = Mock()
        page.warning_label = Mock()
        page.resume_btn = Mock()
        page.restart_btn = Mock()

        page._show_result({'interrupted': True, 'error': 'User cancelled'})

        page.resume_btn.setVisible.assert_called_with(True)
        page.restart_btn.setVisible.assert_called_with(True)

    def test_show_result_empty_does_nothing(self):
        """Empty result should not crash."""
        page = self._make_page()
        page._show_result({})
        page._show_result(None)

    def test_is_final_page(self):
        page = self._make_page()
        assert page.isFinalPage() is True

    def test_make_stat_card_returns_tuple(self):
        """_make_stat_card should return (frame, label) tuple."""
        page = self._make_page()
        result = page._make_stat_card('Test', '42')
        assert isinstance(result, tuple)
        assert len(result) == 2
