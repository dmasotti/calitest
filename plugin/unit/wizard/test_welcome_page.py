"""Tests for WelcomePage (Screen 1) of the Sync Wizard."""

import pytest
from unittest.mock import Mock, patch, MagicMock

import calibre_plugins.sync_calimob.config as cfg


class TestWelcomePage:
    """Unit tests for the WelcomePage wizard page."""

    def _make_page(self, gui=None, plugin_action=None):
        from calibre_plugins.sync_calimob.wizard.pages.welcome_page import WelcomePage
        gui = gui or Mock()
        plugin_action = plugin_action or Mock()
        return WelcomePage(gui, plugin_action)

    def test_page_has_headline_label(self):
        page = self._make_page()
        assert hasattr(page, 'headline_label')

    def test_page_has_subtitle_label(self):
        page = self._make_page()
        assert hasattr(page, 'subtitle_label')

    def test_page_has_connect_button(self):
        page = self._make_page()
        assert hasattr(page, 'connect_btn')

    def test_page_has_advanced_link(self):
        page = self._make_page()
        assert hasattr(page, 'advanced_link')

    def test_next_id_goes_to_login_when_not_configured(self):
        """When no endpoint/token, next page should be Login."""
        page = self._make_page()
        with patch.object(page, '_is_configured', return_value=False):
            assert page.nextId() == 1  # PageLogin

    def test_next_id_skips_to_library_when_already_configured(self):
        """When endpoint + token already present, skip to Library page."""
        page = self._make_page()
        with patch.object(page, '_is_configured', return_value=True):
            assert page.nextId() == 2  # PageLibrary

    def test_is_configured_returns_false_when_no_token(self):
        page = self._make_page()
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
            mock_prefs.__getitem__ = Mock(return_value={
                'restEndpoint': 'https://example.com',
                'restToken': '',
                'deviceToken': '',
            })
            assert page._is_configured() is False

    def test_is_configured_returns_false_when_no_endpoint(self):
        page = self._make_page()
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
            mock_prefs.__getitem__ = Mock(return_value={
                'restEndpoint': '',
                'restToken': 'some-token',
                'deviceToken': '',
            })
            assert page._is_configured() is False

    def test_is_configured_returns_true_with_rest_token(self):
        page = self._make_page()
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
            mock_prefs.__getitem__ = Mock(return_value={
                'restEndpoint': 'https://example.com',
                'restToken': 'some-token',
                'deviceToken': '',
            })
            assert page._is_configured() is True

    def test_is_configured_returns_true_with_device_token(self):
        page = self._make_page()
        with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
            mock_prefs.__getitem__ = Mock(return_value={
                'restEndpoint': 'https://example.com',
                'restToken': '',
                'deviceToken': 'device-tok',
            })
            assert page._is_configured() is True
