"""
Unit tests for sync_mapper.py - Pure functions without external dependencies.
"""

import pytest
from unittest.mock import Mock
from datetime import datetime
import importlib.util
from pathlib import Path

# Import sync_mapper without importing sync_calimob __init__
plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'
sync_mapper_path = plugin_path / 'sync_mapper.py'
spec = importlib.util.spec_from_file_location('sync_mapper', str(sync_mapper_path))
sync_mapper = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_mapper)


class TestCalibreToJsonItem:
    """Test calibre_to_json_item() function."""
    
    def test_basic_conversion(self, mock_calibre_metadata):
        """Test basic conversion of Calibre metadata to JSON item."""
        item = sync_mapper.calibre_to_json_item(
            book_id=123,
            metadata=mock_calibre_metadata,
            library_id='test-library-id'
        )
        
        assert item['title'] == 'Test Book'
        assert len(item['authors']) == 1
        assert item['authors'][0]['name'] == 'Test Author'
        assert item['authors'][0]['role'] == 'author'
        assert item['id'] == 123
        assert item['uuid'] == mock_calibre_metadata.uuid
        assert 'client_ids' not in item
    
    def test_with_series(self, mock_calibre_metadata):
        """Test conversion with series information."""
        mock_calibre_metadata.series = 'Test Series'
        mock_calibre_metadata.series_index = 2.5
        
        item = sync_mapper.calibre_to_json_item(
            book_id=123,
            metadata=mock_calibre_metadata,
            library_id='test-library-id'
        )
        
        assert item['series']['name'] == 'Test Series'
        assert item['series']['series_index'] == 2.5
    
    def test_without_series(self, mock_calibre_metadata):
        """Test conversion without series."""
        mock_calibre_metadata.series = None
        
        item = sync_mapper.calibre_to_json_item(
            book_id=123,
            metadata=mock_calibre_metadata,
            library_id='test-library-id'
        )
        
        assert item['series'] is None
    
    def test_with_isbn(self, mock_calibre_metadata):
        """Test conversion with ISBN."""
        mock_calibre_metadata.isbn = '9781234567890'
        
        item = sync_mapper.calibre_to_json_item(
            book_id=123,
            metadata=mock_calibre_metadata,
            library_id='test-library-id'
        )
        
        assert item['identifiers']['isbn'] == '9781234567890'
    
    def test_multiple_authors(self, mock_calibre_metadata):
        """Test conversion with multiple authors."""
        mock_calibre_metadata.authors = ['Author One', 'Author Two', 'Author Three']
        
        item = sync_mapper.calibre_to_json_item(
            book_id=123,
            metadata=mock_calibre_metadata,
            library_id='test-library-id'
        )
        
        assert len(item['authors']) == 3
        assert item['authors'][0]['name'] == 'Author One'
        assert item['authors'][1]['name'] == 'Author Two'
        assert item['authors'][2]['name'] == 'Author Three'
    
    def test_with_tags(self, mock_calibre_metadata):
        """Test conversion with tags."""
        mock_calibre_metadata.tags = ['fiction', 'sci-fi', 'test']
        
        item = sync_mapper.calibre_to_json_item(
            book_id=123,
            metadata=mock_calibre_metadata,
            library_id='test-library-id'
        )
        
        assert len(item['tags']) == 3
        tag_names = [t.get('name') for t in item['tags']]
        assert 'fiction' in tag_names
        assert 'sci-fi' in tag_names
        assert 'test' in tag_names
        assert [t.get('position') for t in item['tags']] == [0, 1, 2]
    
    def test_status_tag_mapping(self, mock_calibre_metadata, mock_calibre_db):
        """Test status mapping from tags."""
        mock_calibre_metadata.tags = ['Currently Reading']
        status_mappings = {
            'reading': 'currently reading',
            'finished': 'read',
            'abandoned': 'abandoned',
            'tbr': 'to read'
        }
        
        item = sync_mapper.calibre_to_json_item(
            book_id=123,
            metadata=mock_calibre_metadata,
            library_id='test-library-id',
            status_tag_mappings=status_mappings,
            db=mock_calibre_db
        )
        
        assert item['status'] == 'reading'
    
    def test_custom_columns(self, mock_calibre_metadata, mock_calibre_db):
        """Test custom columns (progress_percent, favorite)."""
        # Mock custom column values
        mock_calibre_db.field_metadata.key_to_label = Mock(return_value='Progress')
        mock_calibre_db.get_custom = Mock(side_effect=lambda book_id, label, index_is_id: {
            'Progress': 75.5,
            'Favorite': True
        }.get(label))
        
        item = sync_mapper.calibre_to_json_item(
            book_id=123,
            metadata=mock_calibre_metadata,
            library_id='test-library-id',
            db=mock_calibre_db,
            progress_percent_column='#progress_percent',
            favorite_column='#favorite'
        )
        
        assert item['progress_percent'] == 75.5
        assert item['favorite'] is True


class TestJsonItemToCalibre:
    """Test json_item_to_calibre() function."""
    
    def test_basic_conversion(self, sample_json_item, mock_calibre_db):
        """Test basic conversion of JSON item to Calibre metadata."""
        metadata_dict = sync_mapper.json_item_to_calibre(
            item=sample_json_item,
            db=mock_calibre_db
        )
        
        assert metadata_dict['title'] == 'Test Book'
        assert len(metadata_dict['authors']) == 1
        assert metadata_dict['authors'][0] == 'Test Author'
        assert metadata_dict['series'] == 'Test Series'
        assert metadata_dict['series_index'] == 1.0
        assert metadata_dict['uuid'] == sample_json_item['uuid']
    
    def test_without_series(self, sample_json_item, mock_calibre_db):
        """Test conversion without series."""
        sample_json_item['series'] = None
        
        metadata_dict = sync_mapper.json_item_to_calibre(
            item=sample_json_item,
            db=mock_calibre_db
        )
        
        assert 'series' not in metadata_dict or metadata_dict.get('series') is None
    
    def test_multiple_authors(self, sample_json_item, mock_calibre_db):
        """Test conversion with multiple authors."""
        sample_json_item['authors'] = [
            {'name': 'Author One', 'role': 'author'},
            {'name': 'Author Two', 'role': 'author'},
            {'name': 'Author Three', 'role': 'author'}
        ]
        
        metadata_dict = sync_mapper.json_item_to_calibre(
            item=sample_json_item,
            db=mock_calibre_db
        )
        
        assert len(metadata_dict['authors']) == 3
        assert metadata_dict['authors'][0] == 'Author One'
        assert metadata_dict['authors'][1] == 'Author Two'
        assert metadata_dict['authors'][2] == 'Author Three'


class TestCalculateCoverHash:
    """Test calculate_cover_hash() function."""
    
    def test_hash_from_bytes(self):
        """Test hash calculation from bytes."""
        cover_data = b'fake_cover_image_data'
        hash_value = sync_mapper.calculate_cover_hash(cover_data)
        
        assert isinstance(hash_value, str)
        assert hash_value.startswith('sha256:')
        assert len(hash_value) == 71  # "sha256:" + 64 hex chars
    
    def test_hash_from_path(self, tmp_path):
        """Test hash calculation from file path."""
        cover_file = tmp_path / 'cover.jpg'
        cover_file.write_bytes(b'fake_cover_image_data')
        
        hash_value = sync_mapper.calculate_cover_hash(str(cover_file))
        
        assert isinstance(hash_value, str)
        assert hash_value.startswith('sha256:')
        assert len(hash_value) == 71
    
    def test_hash_consistency(self):
        """Test that same data produces same hash."""
        cover_data = b'fake_cover_image_data'
        hash1 = sync_mapper.calculate_cover_hash(cover_data)
        hash2 = sync_mapper.calculate_cover_hash(cover_data)
        
        assert hash1 == hash2
    
    def test_hash_different_data(self):
        """Test that different data produces different hash."""
        cover_data1 = b'fake_cover_image_data_1'
        cover_data2 = b'fake_cover_image_data_2'

        hash1 = sync_mapper.calculate_cover_hash(cover_data1)
        hash2 = sync_mapper.calculate_cover_hash(cover_data2)

        assert hash1 != hash2


class TestPubdateIsoContract:
    """Test pubdate ISO date string contract (2026-04-04).

    Wire format must be "YYYY-MM-DD" string, not unix timestamp.
    """

    def test_push_pubdate_as_iso_date_string(self, mock_calibre_metadata):
        """calibre_to_json_item must send pubdate as 'YYYY-MM-DD'."""
        from datetime import datetime, timezone
        mock_calibre_metadata.pubdate = datetime(1991, 4, 15, 4, 0, 0, tzinfo=timezone.utc)
        item = sync_mapper.calibre_to_json_item(1, mock_calibre_metadata, 'lib-1')
        assert item['pubdate'] == '1991-04-15', f"Expected ISO date string, got {item['pubdate']!r}"

    def test_push_null_pubdate(self, mock_calibre_metadata):
        """Null pubdate must stay null."""
        mock_calibre_metadata.pubdate = None
        item = sync_mapper.calibre_to_json_item(1, mock_calibre_metadata, 'lib-1')
        assert item['pubdate'] is None

    def test_push_sentinel_pubdate_becomes_null(self, mock_calibre_metadata):
        """Calibre sentinel 0101-01-01 must become null."""
        from datetime import datetime, timezone
        mock_calibre_metadata.pubdate = datetime(101, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        item = sync_mapper.calibre_to_json_item(1, mock_calibre_metadata, 'lib-1')
        assert item['pubdate'] is None

    def test_push_pre_1970_pubdate_preserved(self, mock_calibre_metadata):
        """Pre-1970 dates must be preserved as ISO date strings."""
        from datetime import datetime, timezone
        mock_calibre_metadata.pubdate = datetime(1850, 6, 15, 0, 0, 0, tzinfo=timezone.utc)
        item = sync_mapper.calibre_to_json_item(1, mock_calibre_metadata, 'lib-1')
        assert item['pubdate'] == '1850-06-15'

    def test_receive_iso_date_string(self):
        """json_item_to_calibre must parse 'YYYY-MM-DD' pubdate."""
        from datetime import datetime, timezone
        item = {'pubdate': '2021-10-16', 'title': 'Test'}
        result = sync_mapper.json_item_to_calibre(item, None)
        assert result['pubdate'] is not None
        assert result['pubdate'].year == 2021
        assert result['pubdate'].month == 10
        assert result['pubdate'].day == 16

    def test_receive_null_pubdate(self):
        """Null pubdate must produce UNDEFINED_DATE."""
        item = {'pubdate': None, 'title': 'Test'}
        result = sync_mapper.json_item_to_calibre(item, None)
        # UNDEFINED_DATE is the Calibre sentinel for "no date"
        assert result['pubdate'] == sync_mapper.UNDEFINED_DATE

    def test_receive_pre_1970_iso_date(self):
        """Pre-1970 ISO dates must be parsed correctly."""
        item = {'pubdate': '1850-06-15', 'title': 'Test'}
        result = sync_mapper.json_item_to_calibre(item, None)
        assert result['pubdate'] is not None
        assert result['pubdate'].year == 1850
        assert result['pubdate'].month == 6
        assert result['pubdate'].day == 15
