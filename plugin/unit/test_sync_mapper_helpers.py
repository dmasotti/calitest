from __future__ import annotations

from datetime import datetime, timezone

from calibre_plugins.sync_calimob import sync_mapper


class DummyMetadata:
    def __init__(self):
        self.title = 'Test Title'
        self.sort = None
        self.title_sort = 'Sorted Title'
        self.author_sort = 'Author, Test'
        self.authors = ['Author Test']
        self.series = 'Series Name'
        self.series_index = 2.0
        self.isbn = '9781234567890'
        self.identifiers = {'ASIN': 'B00TEST', 'isbn13': 'duplicate'}
        self.publisher = 'Test Publisher'
        self.pubdate = datetime(2025, 1, 1, tzinfo=timezone.utc)
        self.languages = ['eng', 'ita']
        self.tags = ['Currently Reading', 'Fiction']
        self.rating = 8
        self.comments = 'Great book'
        self.uuid = '11111111-2222-3333-4444-555555555555'
        self.timestamp = datetime(2024, 1, 1, tzinfo=timezone.utc)
        self.last_modified = datetime(2025, 2, 2, tzinfo=timezone.utc)


def test_to_unix_timestamp_handles_datetime():
    """_to_unix_timestamp now delegates to _to_iso_date, returning 'YYYY-MM-DD' strings."""
    dt = datetime(2023, 1, 1, 12, 0, tzinfo=timezone.utc)
    result = sync_mapper._to_unix_timestamp(dt)
    assert result == '2023-01-01'


def test_to_unix_timestamp_handles_number():
    """Numeric values are no longer timestamps — _to_iso_date returns None for them."""
    result = sync_mapper._to_unix_timestamp(1670000000)
    assert result is None


def test_to_unix_timestamp_none():
    assert sync_mapper._to_unix_timestamp(None) is None


def test_from_unix_timestamp_returns_datetime():
    ts = int(datetime(2024, 5, 1, tzinfo=timezone.utc).timestamp())
    result = sync_mapper._from_unix_timestamp(ts)
    assert isinstance(result, datetime)
    assert result.year == 2024


def test_from_unix_timestamp_digits_string():
    value = str(int(datetime(2024, 6, 1, tzinfo=timezone.utc).timestamp()))
    assert sync_mapper._from_unix_timestamp(value).month == 6


def test_calibre_to_json_item_includes_expected_fields():
    metadata = DummyMetadata()
    status_map = {'reading': 'currently reading', 'finished': 'Read'}
    item = sync_mapper.calibre_to_json_item(
        book_id=42,
        metadata=metadata,
        library_id='lib-uuid',
        status_tag_mappings=status_map,
        progress_percent_column=None,
        favorite_column=None,
    )
    assert item['id'] == 42
    assert 'client_ids' not in item
    assert item['uuid'] == metadata.uuid
    assert item['title_sort'] == 'Sorted Title'
    assert item['author_sort'] == 'Author, Test'
    assert item['series']['name'] == 'Series Name'
    assert item['series']['series_index'] == 2.0
    assert item['identifiers']['asin'] == 'B00TEST'
    assert 'isbn' in item['identifiers']
    assert item['publisher'] == 'Test Publisher'
    # pubdate is now ISO date string "YYYY-MM-DD" per the pubdate contract
    assert item['pubdate'] == '2025-01-01'
    assert item['languages'] == ['eng', 'ita']
    assert any(tag['name'] == 'Fiction' for tag in item['tags'])
    assert item['status'] == 'reading'
    assert item['rating'] == 8
    assert item['comments'] == metadata.comments


def test_json_item_to_calibre_populates_fields():
    item = {
        'title': 'Book',
        'title_sort': 'Book',
        'authors': [{'name': 'Author'}],
        'author_sort': 'Author',
        'series': {'name': 'Series', 'series_index': 2},
        'identifiers': {'isbn': '123', 'ASIN': 'B00X'},
        'publisher': 'Pub',
        'pubdate': int(datetime(2024, 1, 1, tzinfo=timezone.utc).timestamp()),
        'languages': ['eng'],
        'tags': [{'name': 'Fiction'}, 'Adventure'],
        'rating': 8,
        'comments': 'Nice',
        'timestamps': {'created_at': int(datetime(2023, 1, 1, tzinfo=timezone.utc).timestamp())},
        'uuid': 'uuid-value',
        'last_modified': int(datetime(2023, 1, 2, tzinfo=timezone.utc).timestamp())
    }
    class DummyDb:
        field_metadata = type('FM', (), {'key_to_label': lambda self, key: key})
        def get_custom(self, book_id, label=None, index_is_id=False):
            return None
    metadata_dict = sync_mapper.json_item_to_calibre(item, DummyDb())
    assert metadata_dict['title'] == 'Book'
    assert metadata_dict['authors'] == ['Author']
    assert metadata_dict['series'] == 'Series'
    assert metadata_dict['series_index'] == 2
    assert metadata_dict['identifiers']['ISBN'] == '123'
    assert metadata_dict['isbn'] == '123'
    assert metadata_dict['rating'] == 8
    assert metadata_dict['uuid'] == 'uuid-value'
    assert metadata_dict['timestamp'].year == 2023


def test_calibre_to_json_item_custom_columns(monkeypatch):
    metadata = DummyMetadata()
    class DummyDb:
        class FieldMeta:
            def key_to_label(self, key):
                return key

        field_metadata = FieldMeta()

        def get_custom(self, book_id, label=None, index_is_id=False):
            if 'progress' in label:
                return '75'
            if 'favorite' in label:
                return '1'
            return None

    item = sync_mapper.calibre_to_json_item(
        book_id=1,
        metadata=metadata,
        library_id='lib',
        db=DummyDb(),
        progress_percent_column='#progress',
        favorite_column='#favorite',
    )
    assert item['progress_percent'] == 75.0
    assert item['favorite'] is True


def test_calibre_to_json_item_handles_missing_languages():
    metadata = DummyMetadata()
    metadata.languages = None
    item = sync_mapper.calibre_to_json_item(1, metadata, 'lib')
    assert item['languages'] == []


def test_calculate_cover_hash_bytes_and_file(tmp_path):
    digest = sync_mapper.calculate_cover_hash(b'data')
    assert digest.startswith('sha256:')
    file_path = tmp_path / 'cover.jpg'
    file_path.write_bytes(b'content')
    file_digest = sync_mapper.calculate_cover_hash(str(file_path))
    assert file_digest.startswith('sha256:')
    missing = sync_mapper.calculate_cover_hash(str(file_path) + '.missing')
    assert missing is None


def test_uuid_is_required_on_items():
    metadata = DummyMetadata()
    metadata.uuid = None
    item = sync_mapper.calibre_to_json_item(1, metadata, 'lib')
    assert item['uuid'] is None
