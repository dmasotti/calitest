"""Tests for CompletePage (Screen 6 + 6b) of the Sync Wizard.

Edge-case matrix:
  ┌───────────────────────┬───────────┬──────────┬────────────────────────────┐
  │ Scenario              │ Checkmark │ Warning  │ Notes                      │
  ├───────────────────────┼───────────┼──────────┼────────────────────────────┤
  │ Full success          │ ✅ green  │ hidden   │ stats populated            │
  │ Success with issues   │ ✅ green  │ visible  │ issues > 0                 │
  │ Batch failure         │ ⚠️ orange │ visible  │ batches_failed > 0         │
  │ Partial batch failure │ ⚠️ orange │ visible  │ some OK, some failed       │
  │ Fatal error           │ ⚠️ orange │ visible  │ error key set              │
  │ Interrupted/paused    │ ⚠️ orange │ visible  │ resume+restart shown       │
  │ Cache corruption      │ ⚠️ orange │ visible  │ rebuild button shown       │
  │ Empty result          │ (no-op)   │ —        │ no crash                   │
  │ None result           │ (no-op)   │ —        │ no crash                   │
  │ 0 candidates success  │ ✅ green  │ hidden   │ all stats = 0, no warning  │
  │ Key aliasing          │ —         │ —        │ books_synced → synced etc   │
  └───────────────────────┴───────────┴──────────┴────────────────────────────┘
"""

import pytest
from unittest.mock import Mock, patch, MagicMock, call


class TestCompletePage:
    """Unit tests for CompletePage."""

    def _make_page(self, gui=None, plugin_action=None):
        from calibre_plugins.sync_calimob.wizard.pages.complete_page import CompletePage
        return CompletePage(gui or Mock(), plugin_action or Mock())

    def _mock_labels(self, page):
        """Replace widget labels with Mocks to capture setText/setVisible calls."""
        page.synced_label = Mock()
        page.updated_label = Mock()
        page.skipped_label = Mock()
        page.issues_label = Mock()
        page.status_label = Mock()
        page.warning_frame = Mock()
        page.warning_label = Mock()
        page.resume_btn = Mock()
        page.restart_btn = Mock()
        page.rebuild_cache_btn = Mock()

    # ------------------------------------------------------------------
    # Structural tests
    # ------------------------------------------------------------------

    def test_page_has_status_label(self):
        page = self._make_page()
        assert hasattr(page, 'status_label')

    def test_page_has_stat_labels(self):
        page = self._make_page()
        for attr in ('synced_label', 'updated_label', 'skipped_label', 'issues_label'):
            assert hasattr(page, attr), f'missing {attr}'

    def test_stat_labels_are_qlabels_not_frames(self):
        page = self._make_page()
        assert hasattr(page.synced_label, 'setText')

    def test_page_has_done_button(self):
        page = self._make_page()
        assert hasattr(page, 'done_btn')

    def test_next_id_returns_minus_one(self):
        page = self._make_page()
        assert page.nextId() == -1

    def test_is_final_page(self):
        page = self._make_page()
        assert page.isFinalPage() is True

    def test_make_stat_card_returns_tuple(self):
        page = self._make_page()
        result = page._make_stat_card('Test', '42')
        assert isinstance(result, tuple) and len(result) == 2

    # ------------------------------------------------------------------
    # _show_result — success scenarios
    # ------------------------------------------------------------------

    def test_show_success_result(self):
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'synced': 1247, 'updated': 12, 'skipped': 5, 'issues': 0,
        })
        page.synced_label.setText.assert_called_with('1247')
        page.updated_label.setText.assert_called_with('12')
        page.skipped_label.setText.assert_called_with('5')
        page.issues_label.setText.assert_called_with('0')

    def test_show_success_with_books_prefix_keys(self):
        """sync_v5 summary uses books_synced/books_updated/books_skipped."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'books_synced': 84, 'books_updated': 3, 'books_skipped': 7,
        })
        page.synced_label.setText.assert_called_with('84')
        page.updated_label.setText.assert_called_with('3')
        page.skipped_label.setText.assert_called_with('7')

    def test_show_success_with_books_from_server_fallback(self):
        """books_from_server should be used for synced count if books_synced=0."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'books_from_server': 50, 'books_updated': 0, 'books_skipped_hash': 10,
        })
        page.synced_label.setText.assert_called_with('50')
        page.skipped_label.setText.assert_called_with('10')

    def test_show_success_zero_candidates(self):
        """0 synced/updated/skipped with no errors = clean success."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'books_synced': 0, 'books_updated': 0, 'books_skipped': 0,
        })
        page.synced_label.setText.assert_called_with('0')
        # Status should show success checkmark
        status_text = page.status_label.setText.call_args[0][0]
        assert '✅' in status_text

    def test_show_success_with_issues(self):
        """Issues > 0 should show warning but still green checkmark."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'synced': 10, 'updated': 2, 'skipped': 0, 'issues': 3,
        })
        status_text = page.status_label.setText.call_args[0][0]
        assert '✅' in status_text
        page.warning_frame.setVisible.assert_called_with(True)

    # ------------------------------------------------------------------
    # _show_result — batch failure scenarios (THE BUG)
    # ------------------------------------------------------------------

    def test_batch_failure_shows_warning_not_success(self):
        """Regression: batch failure must NOT show green checkmark."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'books_synced': 0, 'books_updated': 0, 'books_skipped': 0,
            'batches_failed': 1,
            'batch_errors': [{'batch': 1, 'error': 'HTTP 500 Internal Server Error'}],
        })
        status_text = page.status_label.setText.call_args[0][0]
        assert '⚠' in status_text
        assert '✅' not in status_text
        page.warning_frame.setVisible.assert_called_with(True)
        warning_text = page.warning_label.setText.call_args[0][0]
        assert '500' in warning_text

    def test_batch_failure_counts_in_issues(self):
        """Failed batches should be reflected in the Issues stat card."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'books_synced': 0, 'books_updated': 0, 'books_skipped': 0,
            'batches_failed': 2,
            'batch_errors': [
                {'batch': 1, 'error': 'timeout'},
                {'batch': 2, 'error': 'timeout'},
            ],
        })
        issues_val = int(page.issues_label.setText.call_args[0][0])
        assert issues_val >= 2

    def test_partial_batch_failure(self):
        """Some batches OK, some failed = warning + partial stats."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'books_synced': 50, 'books_updated': 5, 'books_skipped': 0,
            'batches_failed': 1, 'batches_ok': 2,
            'batch_errors': [{'batch': 3, 'error': 'connection reset'}],
        })
        status_text = page.status_label.setText.call_args[0][0]
        assert '⚠' in status_text
        page.synced_label.setText.assert_called_with('50')
        page.warning_frame.setVisible.assert_called_with(True)

    def test_batch_failure_with_empty_errors_list(self):
        """batches_failed > 0 but batch_errors empty should still warn."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'books_synced': 0, 'books_updated': 0, 'books_skipped': 0,
            'batches_failed': 1, 'batch_errors': [],
        })
        status_text = page.status_label.setText.call_args[0][0]
        assert '⚠' in status_text
        page.warning_frame.setVisible.assert_called_with(True)

    def test_batch_errors_without_batches_failed_key(self):
        """batch_errors present but no batches_failed key."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'books_synced': 0, 'books_updated': 0, 'books_skipped': 0,
            'batch_errors': [{'batch': 1, 'error': 'some error'}],
        })
        status_text = page.status_label.setText.call_args[0][0]
        assert '⚠' in status_text

    def test_errors_list_counts_in_issues(self):
        """summary['errors'] list items should count in Issues."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'books_synced': 10, 'books_updated': 0, 'books_skipped': 0,
            'errors': [{'phase': 'download', 'error': 'timeout'}],
        })
        issues_val = int(page.issues_label.setText.call_args[0][0])
        assert issues_val >= 1

    # ------------------------------------------------------------------
    # _show_result — error / interrupted scenarios
    # ------------------------------------------------------------------

    def test_show_error_result(self):
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({'error': 'Connection timed out'})
        page.warning_frame.setVisible.assert_called_with(True)
        page.warning_label.setText.assert_called_with('Connection timed out')

    def test_show_interrupted_result(self):
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({'interrupted': True, 'error': 'User cancelled'})
        page.resume_btn.setVisible.assert_called_with(True)
        page.restart_btn.setVisible.assert_called_with(True)

    def test_cache_corruption_shows_rebuild_button(self):
        """Error mentioning 'rebuild' or 'malformed' shows rebuild button."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({'error': 'database disk image is malformed, rebuild cache'})
        page.rebuild_cache_btn.setVisible.assert_called_with(True)

    def test_network_error_hides_rebuild_button(self):
        """Network errors should NOT show rebuild button."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({'error': 'Connection refused'})
        page.rebuild_cache_btn.setVisible.assert_called_with(False)

    # ------------------------------------------------------------------
    # _show_result — edge cases
    # ------------------------------------------------------------------

    def test_show_result_empty_does_nothing(self):
        page = self._make_page()
        page._show_result({})
        page._show_result(None)

    def test_show_result_only_batches_ok(self):
        """Only batches_ok, no failures = success."""
        page = self._make_page()
        self._mock_labels(page)
        page._show_result({
            'books_synced': 84, 'books_updated': 0, 'books_skipped': 0,
            'batches_ok': 1, 'batches_failed': 0,
        })
        status_text = page.status_label.setText.call_args[0][0]
        assert '✅' in status_text

    # ------------------------------------------------------------------
    # initializePage stores _sync_result
    # ------------------------------------------------------------------

    def test_initialize_page_stores_sync_result(self):
        """initializePage must store _sync_result for _on_toggle_details."""
        page = self._make_page()
        self._mock_labels(page)
        mock_wizard = Mock()
        mock_progress = Mock()
        mock_progress._sync_result = {'books_synced': 10, 'batches_failed': 1, 'batch_errors': [{'batch': 1, 'error': 'x'}]}
        mock_wizard.page.return_value = mock_progress

        with patch.object(type(page), 'wizard', return_value=mock_wizard):
            page.initializePage()

        assert page._sync_result is not None
        assert page._sync_result.get('batches_failed') == 1

    def test_initialize_page_none_result_safe(self):
        """initializePage with None sync result should not crash."""
        page = self._make_page()
        self._mock_labels(page)
        mock_wizard = Mock()
        mock_progress = Mock()
        mock_progress._sync_result = None
        mock_wizard.page.return_value = mock_progress

        with patch.object(type(page), 'wizard', return_value=mock_wizard):
            page.initializePage()

        assert page._sync_result == {}

    # ------------------------------------------------------------------
    # _on_toggle_details (inline collapsible log)
    # ------------------------------------------------------------------

    def test_on_toggle_details_expands_log_area(self):
        """Toggle details should expand the log area inline."""
        page = self._make_page()
        page.log_area = Mock()
        page.log_area.maximumHeight = Mock(return_value=0)
        page.log_area.toPlainText = Mock(return_value='')
        page.detail_toggle = Mock()
        page._sync_result = {'error': 'test error'}
        with patch.object(type(page), 'wizard', return_value=None):
            page._on_toggle_details()
        page.log_area.setMaximumHeight.assert_called_with(200)

    def test_on_toggle_details_collapses_log_area(self):
        """Toggle details again should collapse."""
        page = self._make_page()
        page.log_area = Mock()
        page.log_area.maximumHeight = Mock(return_value=200)
        page.detail_toggle = Mock()
        page._on_toggle_details()
        page.log_area.setMaximumHeight.assert_called_with(0)
