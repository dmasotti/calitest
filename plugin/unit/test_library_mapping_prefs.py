"""Unit tests for library_mapping_prefs helper module."""

import importlib.util
from pathlib import Path


plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'
module_path = plugin_path / 'library_mapping_prefs.py'
spec = importlib.util.spec_from_file_location('library_mapping_prefs', str(module_path))
library_mapping_prefs = importlib.util.module_from_spec(spec)
spec.loader.exec_module(library_mapping_prefs)


def test_status_mapping_does_not_create_missing_association():
    mappings = {}
    updated, changed = library_mapping_prefs.save_status_tag_mappings_if_associated(
        mappings,
        'lib-1',
        'statusTagMappings',
        {'reading': 'Reading'},
    )
    assert changed is False
    assert updated == {}


def test_status_mapping_updates_existing_association():
    mappings = {'lib-1': {'calimobLibraryId': 10}}
    updated, changed = library_mapping_prefs.save_status_tag_mappings_if_associated(
        mappings,
        'lib-1',
        'statusTagMappings',
        {'reading': 'Reading', 'finished': ''},
    )
    assert changed is True
    assert updated['lib-1']['statusTagMappings'] == {'reading': 'Reading'}


def test_custom_columns_do_not_create_missing_association():
    mappings = {}
    updated, changed = library_mapping_prefs.save_custom_columns_if_associated(
        mappings,
        'lib-1',
        'progressPercentColumn',
        '#progress',
        'favoriteColumn',
        '#fav',
    )
    assert changed is False
    assert updated == {}


def test_custom_columns_remove_when_empty_for_existing_association():
    mappings = {
        'lib-1': {
            'calimobLibraryId': 10,
            'progressPercentColumn': '#old_progress',
            'favoriteColumn': '#old_fav',
        }
    }
    updated, changed = library_mapping_prefs.save_custom_columns_if_associated(
        mappings,
        'lib-1',
        'progressPercentColumn',
        '',
        'favoriteColumn',
        '',
    )
    assert changed is True
    assert 'progressPercentColumn' not in updated['lib-1']
    assert 'favoriteColumn' not in updated['lib-1']

