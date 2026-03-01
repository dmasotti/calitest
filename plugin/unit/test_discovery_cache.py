"""Unit tests for discovery cache invalidation helper."""

import importlib.util
from pathlib import Path


plugin_path = Path(__file__).parent.parent.parent.parent / 'sync_calimob'
module_path = plugin_path / 'discovery_cache.py'
spec = importlib.util.spec_from_file_location('discovery_cache', str(module_path))
discovery_cache = importlib.util.module_from_spec(spec)
spec.loader.exec_module(discovery_cache)


def test_invalidate_cache_when_endpoint_changes():
    store = {
        'restEndpoint': 'https://old.example.com',
        'discoveryCache': {'ts': 123, 'data': {'api_url': 'https://old.example.com/api'}},
    }
    changed = discovery_cache.set_endpoint_with_cache_invalidation(
        store, 'restEndpoint', 'discoveryCache', 'https://new.example.com'
    )
    assert changed is True
    assert store['restEndpoint'] == 'https://new.example.com'
    assert 'discoveryCache' not in store


def test_keep_cache_when_endpoint_unchanged():
    cache = {'ts': 123, 'data': {'api_url': 'https://same.example.com/api'}}
    store = {
        'restEndpoint': 'https://same.example.com',
        'discoveryCache': cache,
    }
    changed = discovery_cache.set_endpoint_with_cache_invalidation(
        store, 'restEndpoint', 'discoveryCache', 'https://same.example.com'
    )
    assert changed is False
    assert store['discoveryCache'] == cache

