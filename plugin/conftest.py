"""
Pytest configuration and fixtures for plugin tests.
"""

import pytest
import sys
import os
from unittest.mock import Mock, MagicMock, patch
from pathlib import Path
from datetime import datetime, timezone
import types

# Provide minimal calibre stubs if Calibre is not installed (unit tests only).
if 'calibre' not in sys.modules:
    calibre = types.ModuleType('calibre')
    calibre.utils = types.ModuleType('calibre.utils')
    calibre.utils.date = types.ModuleType('calibre.utils.date')
    calibre.utils.iso8601 = types.ModuleType('calibre.utils.iso8601')
    calibre.ebooks = types.ModuleType('calibre.ebooks')
    calibre.ebooks.metadata = types.ModuleType('calibre.ebooks.metadata')
    calibre.ebooks.metadata.book = types.ModuleType('calibre.ebooks.metadata.book')
    calibre.ebooks.metadata.book.base = types.ModuleType('calibre.ebooks.metadata.book.base')
    calibre.constants = types.ModuleType('calibre.constants')
    calibre.devices = types.ModuleType('calibre.devices')
    calibre.devices.usbms = types.ModuleType('calibre.devices.usbms')
    calibre.devices.usbms.driver = types.ModuleType('calibre.devices.usbms.driver')

    calibre.utils.date.UNDEFINED_DATE = object()
    calibre.utils.date.utcnow = lambda: datetime.now(timezone.utc)

    def _parse_iso8601(val):
        if not val:
            return None
        if isinstance(val, datetime):
            return val
        try:
            return datetime.fromisoformat(str(val).replace('Z', '+00:00'))
        except Exception:
            return None

    calibre.utils.iso8601.parse_iso8601 = _parse_iso8601
    calibre.utils.iso8601.format_iso8601 = lambda dt: dt.isoformat() if dt else None

    calibre.ebooks.metadata.authors_to_string = lambda authors: ', '.join(authors or [])
    calibre.ebooks.metadata.fmt_sidx = lambda x: x

    class _Metadata(object):
        def __init__(self, title='', authors=None):
            self.title = title
            self.authors = authors or []

    calibre.ebooks.metadata.book.base.Metadata = _Metadata
    calibre.constants.DEBUG = False
    calibre.devices.usbms.driver.debug_print = lambda *args, **kwargs: None

    sys.modules['calibre'] = calibre
    sys.modules['calibre.utils'] = calibre.utils
    sys.modules['calibre.utils.date'] = calibre.utils.date
    sys.modules['calibre.utils.iso8601'] = calibre.utils.iso8601
    sys.modules['calibre.ebooks'] = calibre.ebooks
    sys.modules['calibre.ebooks.metadata'] = calibre.ebooks.metadata
    sys.modules['calibre.ebooks.metadata.book'] = calibre.ebooks.metadata.book
    sys.modules['calibre.ebooks.metadata.book.base'] = calibre.ebooks.metadata.book.base
    sys.modules['calibre.constants'] = calibre.constants
    sys.modules['calibre.devices'] = calibre.devices
    sys.modules['calibre.devices.usbms'] = calibre.devices.usbms
    sys.modules['calibre.devices.usbms.driver'] = calibre.devices.usbms.driver

# Provide minimal calibre_plugins stubs for patching config
if 'calibre_plugins' not in sys.modules:
    calibre_plugins = types.ModuleType('calibre_plugins')
    sys.modules['calibre_plugins'] = calibre_plugins
if 'calibre_plugins.sync_calimob' not in sys.modules:
    sync_pkg = types.ModuleType('calibre_plugins.sync_calimob')
    sys.modules['calibre_plugins.sync_calimob'] = sync_pkg
if 'calibre_plugins.sync_calimob.config' not in sys.modules:
    cfg_mod = types.ModuleType('calibre_plugins.sync_calimob.config')
    cfg_mod.plugin_prefs = {}
    sys.modules['calibre_plugins.sync_calimob.config'] = cfg_mod

# Add sync_calimob to path
plugin_path = Path(__file__).parent.parent.parent / 'sync_calimob'
sys.path.insert(0, str(plugin_path.parent))


@pytest.fixture
def mock_calibre_metadata():
    """Mock Calibre Metadata object."""
    from unittest.mock import Mock
    from datetime import datetime, timezone
    
    metadata = Mock()
    metadata.title = 'Test Book'
    metadata.authors = ['Test Author']
    metadata.series = None
    metadata.series_index = None
    metadata.isbn = '9781234567890'
    metadata.publisher = 'Test Publisher'
    metadata.pubdate = None
    metadata.languages = ['eng']
    metadata.tags = []
    metadata.identifiers = {}
    metadata.comments = ''
    metadata.rating = 0.0
    metadata.uuid = '11111111-2222-3333-4444-555555555555'
    metadata.timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
    metadata.last_modified = datetime(2024, 1, 2, tzinfo=timezone.utc)
    
    # Mock methods
    metadata.get = Mock(return_value=None)
    
    return metadata


@pytest.fixture
def mock_calibre_db(mock_calibre_metadata):
    """Mock Calibre database object."""
    db = Mock()
    
    # Mock library path
    db.library_path = '/tmp/test_library'
    
    # Mock book data
    db.data = Mock()
    db.data.has_id = Mock(return_value=True)
    db.data.search_getting_ids = Mock(return_value=[1, 2, 3])
    db.data.iterallids = Mock(return_value=iter([1, 2, 3]))
    
    # Mock metadata methods
    db.get_metadata = Mock(return_value=mock_calibre_metadata)
    db.title = Mock(return_value='Test Book')
    db.authors = Mock(return_value='Test Author')
    db.rating = Mock(return_value=0.0)
    db.comments = Mock(return_value='')
    db.get_identifiers = Mock(return_value={})
    db.cover = Mock(return_value=b'fake_cover_data')
    
    # Mock custom columns
    db.field_metadata = Mock()
    db.field_metadata.custom_field_metadata = Mock(return_value={})
    db.field_metadata.key_to_label = Mock(return_value='Test Column')
    db.get_custom = Mock(return_value=None)
    db.set_custom = Mock()
    db.set_metadata = Mock()
    db.commit = Mock()
    
    # Mock identifiers
    db.set_identifiers = Mock()
    
    return db


@pytest.fixture
def mock_calibre_gui(mock_calibre_db):
    """Mock Calibre GUI object."""
    gui = Mock()
    gui.current_db = mock_calibre_db
    gui.library_view = Mock()
    gui.library_view.model = Mock(return_value=Mock(db=mock_calibre_db))
    gui.status_bar = Mock()
    gui.status_bar.showMessage = Mock()
    gui.status_bar.clearMessage = Mock()
    return gui


@pytest.fixture
def mock_plugin_config():
    """Mock plugin configuration."""
    config = {
        'restEndpoint': 'https://api.example.com',
        'restToken': 'test-token-123',
        'deviceToken': '',
        'restUsername': '',
        'restPassword': '',
        'syncBatchSize': 200,
        'pullLimit': 200,
        'coverBatchMaxBytes': 3 * 1024 * 1024,
        'coverSingleMaxBytes': 600 * 1024,
        'httpTimeout': 30,
        'uploadTimeout': 120,
        'debugApiLogs': False,
    }
    
    library_mappings = {
        'test-library-id': {
            'calibreLibraryId': 'test-library-id',
            'calibreLibraryName': 'Test Library',
            'calimobLibraryId': 'calimob-lib-123',
            'calimobLibraryName': 'Test Library',
            'syncEnabled': True,
            'lastSyncCursor': None,
            'lastSyncTime': None,
            'lastPullCursor': None,
            'lastPullTime': None,
            'syncedBookIds': [],
            'statusTagMappings': {},
            'progressPercentColumn': None,
            'favoriteColumn': None,
        }
    }
    
    return {
        'plugin': config,
        'library_mappings': library_mappings,
    }


@pytest.fixture
def sample_json_item():
    """Sample JSON item from REST API."""
    return {
        'id': 1,
        'uuid': 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
        'client_ids': {
            'calibre:test-library-id:1': '1'
        },
        'title': 'Test Book',
        'title_sort': 'Test Book',
        'author_sort': 'Author, Test',
        'authors': [
            {'name': 'Test Author', 'role': 'author'}
        ],
        'series': {
            'name': 'Test Series',
            'series_index': 1.0
        },
        'identifiers': {
            'isbn': '9781234567890'
        },
        'publisher': 'Test Publisher',
        'pubdate': '2020-01-01T00:00:00Z',
        'languages': ['eng'],
        'tags': [{'name': 'fiction'}, {'name': 'test'}],
        'status': None,
        'rating': 4,
        'comments': 'Test description',
        'progress_percent': None,
        'favorite': False,
        'source': {
            'client': 'calibre',
            'client_library': 'test-library-id'
        },
        'extra': {},
        'version': 1,
        'last_modified': 1704067200,
        'timestamps': {
            'created_at': 1704067200
        },
    }


@pytest.fixture
def sample_calibre_book():
    """Sample Calibre book data."""
    return {
        'id': 1,
        'title': 'Test Book',
        'authors': ['Test Author'],
        'series': 'Test Series',
        'series_index': 1.0,
        'isbn': '9781234567890',
        'publisher': 'Test Publisher',
        'pubdate': None,
        'languages': ['eng'],
        'tags': ['fiction', 'test'],
        'rating': 4.0,
        'comments': 'Test description',
    }


@pytest.fixture
def mock_http_response():
    """Mock HTTP response."""
    response = Mock()
    response.status = 200
    response.reason = 'OK'
    response.__getitem__ = Mock(return_value='application/json')
    return response


@pytest.fixture(autouse=True)
def patch_plugin_prefs(mock_plugin_config):
    """Auto-patch plugin preferences for all tests."""
    with patch('calibre_plugins.sync_calimob.config.plugin_prefs') as mock_prefs:
        mock_prefs.__getitem__ = Mock(side_effect=lambda key: {
            'Goodreads': mock_plugin_config['plugin'],
            'LibraryMappings': mock_plugin_config['library_mappings'],
        }.get(key, {}))
        mock_prefs.get = Mock(side_effect=lambda key, default=None: {
            'Goodreads': mock_plugin_config['plugin'],
            'LibraryMappings': mock_plugin_config['library_mappings'],
        }.get(key, default))
        yield mock_prefs
