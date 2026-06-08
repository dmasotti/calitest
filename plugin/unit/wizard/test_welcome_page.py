"""Tests for WelcomePage (Screen 1) of the Sync Wizard."""

import pytest
from unittest.mock import Mock, patch, MagicMock

from calibre_plugins.sync_calimob import config as cfg


def _fake_prefs(endpoint='https://example.com', rest_token='', device_token='',
                device_token_status='unknown'):
    """Build a minimal plugin_prefs dict usable by _is_configured()."""
    store = dict(cfg.DEFAULT_STORE_VALUES)
    store[cfg.KEY_REST_ENDPOINT] = endpoint
    store[cfg.KEY_REST_TOKEN] = rest_token
    store[cfg.KEY_DEVICE_TOKEN] = device_token
    store[cfg.KEY_DEVICE_TOKEN_STATUS] = device_token_status
    return {cfg.STORE_PLUGIN: store}


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
        fake = _fake_prefs(endpoint='https://example.com', rest_token='', device_token='')
        with patch.object(cfg, 'plugin_prefs', fake):
            assert page._is_configured() is False

    def test_is_configured_returns_false_when_no_endpoint(self):
        page = self._make_page()
        fake = _fake_prefs(endpoint='', rest_token='some-token', device_token='')
        with patch.object(cfg, 'plugin_prefs', fake):
            assert page._is_configured() is False

    def test_is_configured_returns_true_with_rest_token(self):
        page = self._make_page()
        fake = _fake_prefs(endpoint='https://example.com', rest_token='some-token', device_token='')
        with patch.object(cfg, 'plugin_prefs', fake):
            assert page._is_configured() is True

    def test_is_configured_returns_true_with_device_token(self):
        page = self._make_page()
        fake = _fake_prefs(endpoint='https://example.com', rest_token='', device_token='device-tok')
        with patch.object(cfg, 'plugin_prefs', fake):
            assert page._is_configured() is True
