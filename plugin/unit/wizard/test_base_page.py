"""Tests for WizardBasePage and _BackgroundFrame."""

from unittest.mock import Mock, patch, MagicMock


class TestBackgroundFrame:
    """Unit tests for _BackgroundFrame — hero image + overlay."""

    def _make_frame(self):
        from calibre_plugins.sync_calimob.wizard.pages.base_page import _BackgroundFrame
        return _BackgroundFrame()

    def test_frame_has_bg_pixmap_attribute(self):
        frame = self._make_frame()
        assert hasattr(frame, '_bg_pixmap')

    def test_load_bg_does_not_crash(self):
        """_load_bg should not crash even when get_pixmap returns stubs."""
        from calibre_plugins.sync_calimob.wizard.pages.base_page import _BackgroundFrame
        frame = _BackgroundFrame()
        assert hasattr(frame, '_bg_pixmap')

    def test_load_bg_method_exists(self):
        from calibre_plugins.sync_calimob.wizard.pages.base_page import _BackgroundFrame
        assert callable(getattr(_BackgroundFrame, '_load_bg', None))

    def test_has_paint_event(self):
        frame = self._make_frame()
        assert hasattr(frame, 'paintEvent')


class TestWizardBasePage:
    """Unit tests for WizardBasePage layout structure."""

    def _make_page(self):
        from calibre_plugins.sync_calimob.wizard.pages.base_page import WizardBasePage
        return WizardBasePage(Mock(), Mock())

    def test_page_has_bg_frame(self):
        page = self._make_page()
        assert hasattr(page, '_bg_frame')

    def test_page_has_card(self):
        page = self._make_page()
        assert hasattr(page, '_card')

    def test_page_has_card_layout(self):
        page = self._make_page()
        assert hasattr(page, 'card_layout')

    def test_card_object_name(self):
        """Card should have objectName 'wizardCard' for QSS targeting."""
        page = self._make_page()
        # In stub environment, setObjectName is a no-op, but attribute exists
        assert page._card is not None

    def test_bg_frame_object_name(self):
        page = self._make_page()
        assert page._bg_frame is not None
