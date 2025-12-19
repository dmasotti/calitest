"""
Unit tests for sync_mapper.py - Pure functions without external dependencies.
"""

import pytest
from unittest.mock import Mock
from datetime import datetime

# Import sync_mapper functions
import sys
from pathlib import Path
plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'
sys.path.insert(0, str(plugin_path.parent))

try:
    from sync_calimob import sync_mapper
except ImportError:
    from calibre_plugins.sync_calimob import sync_mapper


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
        assert item['calibre_book_id'] == 123
        assert 'client_ids' in item
        assert 'calibre:test-library-id:123' in item['client_ids']
    
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
        assert item['series']['index'] == 2.5
    
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
        assert 'fiction' in item['tags']
        assert 'sci-fi' in item['tags']
        assert 'test' in item['tags']
    
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
        assert len(hash_value) == 64  # SHA256 hex string length
    
    def test_hash_from_path(self, tmp_path):
        """Test hash calculation from file path."""
        cover_file = tmp_path / 'cover.jpg'
        cover_file.write_bytes(b'fake_cover_image_data')
        
        hash_value = sync_mapper.calculate_cover_hash(str(cover_file))
        
        assert isinstance(hash_value, str)
        assert len(hash_value) == 64
    
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
