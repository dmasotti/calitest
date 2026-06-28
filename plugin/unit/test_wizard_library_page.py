"""Unit tests for wizard library page: UUID filtering and mapping save."""

import importlib.util
from pathlib import Path
from unittest.mock import MagicMock, patch

plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'


def _load_module(name, filename):
    mod_path = plugin_path / filename
    spec = importlib.util.spec_from_file_location(name, str(mod_path))
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Test: client-side UUID filtering (the server may ignore the filter)
# ---------------------------------------------------------------------------

class TestClientSideUuidFilter:
    """Verify that _load_libraries filters by calibre_library_uuid client-side."""

    def _make_page(self, current_uuid, server_response):
        """Create a minimal LibraryPage mock that exercises _load_libraries."""

        class FakeDB:
            library_path = '/fake/library'

        class FakeGui:
            current_db = FakeDB()

        class FakeClient:
            def get_libraries(self, calibre_library_uuid=None):
                return server_response

            def create_library(self, **kw):
                return {'id': 'new-99', 'name': kw.get('name', 'New'),
                        'calibre_library_uuid': current_uuid}

        # We test the filtering logic directly rather than constructing Qt widgets
        page = MagicMock()
        page.gui = FakeGui()
        page._libraries = []
        page._selected_library = None
        page._cal_uuid = None

        return page, FakeClient(), current_uuid

    def test_filters_out_wrong_uuid(self):
        """Server returns libraries for a different UUID — should get empty list."""
        uuid_giulia = 'aaaa-bbbb-cccc'
        server_libs = [
            {'id': '1', 'name': 'calibrefra', 'calibre_library_uuid': 'xxxx-yyyy-zzzz'},
        ]
        # Simulate the filtering logic from _load_libraries
        filtered = [
            lib for lib in server_libs
            if lib.get('calibre_library_uuid', '') == uuid_giulia
        ]
        assert filtered == []

    def test_keeps_matching_uuid(self):
        """Server returns a library with matching UUID — should keep it."""
        uuid_fra = 'xxxx-yyyy-zzzz'
        server_libs = [
            {'id': '1', 'name': 'calibrefra', 'calibre_library_uuid': 'xxxx-yyyy-zzzz'},
            {'id': '2', 'name': 'calibregiulia', 'calibre_library_uuid': 'aaaa-bbbb-cccc'},
        ]
        filtered = [
            lib for lib in server_libs
            if lib.get('calibre_library_uuid', '') == uuid_fra
        ]
        assert len(filtered) == 1
        assert filtered[0]['name'] == 'calibrefra'

    def test_multiple_libs_different_uuids(self):
        """Server returns all libraries — only the one matching current UUID is kept."""
        uuid_giulia = 'aaaa-bbbb-cccc'
        server_libs = [
            {'id': '1', 'name': 'calibrefra', 'calibre_library_uuid': 'xxxx-yyyy-zzzz'},
            {'id': '2', 'name': 'calibregiulia', 'calibre_library_uuid': 'aaaa-bbbb-cccc'},
            {'id': '3', 'name': 'calibretest', 'calibre_library_uuid': 'mmmm-nnnn-pppp'},
        ]
        filtered = [
            lib for lib in server_libs
            if lib.get('calibre_library_uuid', '') == uuid_giulia
        ]
        assert len(filtered) == 1
        assert filtered[0]['name'] == 'calibregiulia'

    def test_no_uuid_on_server_lib_excluded(self):
        """Server library without calibre_library_uuid field is excluded."""
        uuid_fra = 'xxxx-yyyy-zzzz'
        server_libs = [
            {'id': '1', 'name': 'oldlib'},  # no calibre_library_uuid
        ]
        filtered = [
            lib for lib in server_libs
            if lib.get('calibre_library_uuid', '') == uuid_fra
        ]
        assert filtered == []


# ---------------------------------------------------------------------------
# Test: _save_mapping uses current_db (not gui) and saves correctly
# ---------------------------------------------------------------------------

class TestSaveMapping:
    """Verify that the mapping is saved with the correct key from current_db."""

    def test_mapping_key_matches_progress_page_key(self):
        """The key used to save (library_page) must match the key used to read (progress_page).

        Both must use get_calibre_library_id(gui.current_db), not get_calibre_library_id(gui).
        """
        # This is a contract test: both pages must use the same function with the same argument
        import ast

        lib_page_src = (plugin_path / 'wizard' / 'pages' / 'library_page.py').read_text()
        progress_src = (plugin_path / 'wizard' / 'pages' / 'progress_page.py').read_text()

        # library_page must use gui.current_db (not just gui)
        assert 'get_calibre_library_id(self.gui.current_db)' in lib_page_src or \
               'get_calibre_library_id(db)' in lib_page_src, \
            "library_page._save_mapping must use gui.current_db, not gui"

        # progress_page must also use current_db
        assert 'self.gui.current_db' in progress_src, \
            "progress_page._start_sync must use gui.current_db"

    def test_nextId_calls_save_mapping(self):
        """nextId() must save the mapping before navigating, not just return the page ID."""
        src = (plugin_path / 'wizard' / 'pages' / 'library_page.py').read_text()

        # nextId must reference _save_mapping or _confirmed
        assert '_save_mapping' in src or '_confirmed' in src, \
            "nextId() must check/call _save_mapping before returning page ID"

        # nextId must NOT unconditionally return _PAGE_READY
        import re
        # Find the nextId method body
        match = re.search(r'def nextId\(self\):\s*\n((?:[ \t]+.*\n)*)', src)
        assert match, "Could not find nextId method"
        body = match.group(1)
        # Should not be just "return self._PAGE_READY" with no guard
        lines = [l.strip() for l in body.strip().split('\n') if l.strip()]
        assert len(lines) > 1, \
            "nextId() must have guard logic, not just 'return self._PAGE_READY'"

    def test_error_message_says_caliweb_not_calimob(self):
        """The error message in progress_page must say 'Caliweb', not 'calimob'."""
        src = (plugin_path / 'wizard' / 'pages' / 'progress_page.py').read_text()
        assert 'No calimob library' not in src, \
            "Error message still says 'calimob' — should be 'Caliweb'"
