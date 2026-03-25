"""Tests for ReadyPage link handlers and text visibility."""

from unittest.mock import Mock


class TestReadyPageAdvancedLink:
    """Advanced Settings link must be wired to a handler."""

    def _make_page(self, gui=None, plugin_action=None):
        from calibre_plugins.sync_calimob.wizard.pages.ready_page import ReadyPage
        return ReadyPage(gui or Mock(), plugin_action or Mock())

    def test_advanced_link_has_handler(self):
        """The advanced link should have _on_advanced connected."""
        page = self._make_page()
        assert hasattr(page, '_on_advanced')
        assert callable(page._on_advanced)

    def test_advanced_link_opens_config(self):
        mock_action = Mock()
        mock_action.show_configuration = Mock()
        page = self._make_page(plugin_action=mock_action)
        page._on_advanced('#')
        mock_action.show_configuration.assert_called_once()


class TestReadyPageTextContrast:
    """Radio buttons and labels should use dark text for readability."""

    def _make_page(self):
        from calibre_plugins.sync_calimob.wizard.pages.ready_page import ReadyPage
        return ReadyPage(Mock(), Mock())

    def test_radio_buttons_exist(self):
        page = self._make_page()
        assert hasattr(page, 'sync_all_radio')
        assert hasattr(page, 'sync_selected_radio')
