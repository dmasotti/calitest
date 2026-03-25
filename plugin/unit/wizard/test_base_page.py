"""Tests for WizardBasePage."""

from unittest.mock import Mock


class TestWizardBasePage:
    """Unit tests for WizardBasePage layout structure."""

    def _make_page(self):
        from calibre_plugins.sync_calimob.wizard.pages.base_page import WizardBasePage
        return WizardBasePage(Mock(), Mock())

    def test_page_has_card(self):
        page = self._make_page()
        assert hasattr(page, '_card')

    def test_page_has_card_layout(self):
        page = self._make_page()
        assert hasattr(page, 'card_layout')

    def test_page_has_gui(self):
        gui = Mock()
        from calibre_plugins.sync_calimob.wizard.pages.base_page import WizardBasePage
        page = WizardBasePage(gui, Mock())
        assert page.gui is gui

    def test_page_has_plugin_action(self):
        action = Mock()
        from calibre_plugins.sync_calimob.wizard.pages.base_page import WizardBasePage
        page = WizardBasePage(Mock(), action)
        assert page.plugin_action is action

    def test_page_has_opacity_slider(self):
        page = self._make_page()
        assert hasattr(page, '_opacity_slider')
