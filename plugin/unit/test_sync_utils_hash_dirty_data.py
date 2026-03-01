import copy
import importlib.util
from pathlib import Path

plugin_path = Path(__file__).parent.parent.parent.parent / "sync_calimob"
sync_utils_path = plugin_path / "sync_utils.py"
spec = importlib.util.spec_from_file_location("sync_utils", str(sync_utils_path))
sync_utils = importlib.util.module_from_spec(spec)
spec.loader.exec_module(sync_utils)


def _hash(item):
    return sync_utils.compute_metadata_hash(item, format_cache={}, cover_hash=None)


def test_hash_ignores_client_only_fields_and_transport_noise():
    base = {
        "uuid": "u-1",
        "title": "My Book",
        "authors": [{"name": "B Author"}, {"name": "A Author"}],
        "series": {"name": "S", "series_index": 2},
        "identifiers": {"ISBN": "978123", "amazon": "B00X"},
        "publisher": "Pub",
        "pubdate": 1700000000,
        "languages": ["ita", "eng"],
        "tags": [{"name": "zeta"}, {"name": "alpha"}],
        "description": "Desc",
        "rating": None,
    }
    noisy = copy.deepcopy(base)
    noisy.update(
        {
            "id": 99,
            "title_sort": "ignored",
            "author_sort": "ignored",
            "last_modified": 1772000000,
            "version": 1772000000,
            "files": [{"format": "EPUB", "file_hash": "sha256:aaa"}],
            "formats": [{"format": "EPUB"}],
            "cover": {"cover_hash": "sha256:bbb"},
            "extra": {"k": "v"},
            "status": "read",
            "favorite": True,
            "progress_percent": 55,
        }
    )
    assert _hash(base) == _hash(noisy)


def test_hash_normalizes_dirty_people_tags_identifiers_and_ordering():
    canonical = {
        "uuid": "u-2",
        "title": "Ordered",
        "authors": [{"name": "Alice"}, {"name": "Bob"}],
        "series": {"name": "Saga", "series_index": 1.0},
        "identifiers": {"isbn": "111", "google": "gid"},
        "publisher": None,
        "pubdate": None,
        "languages": ["eng", "ita"],
        "tags": [{"name": "fiction"}, {"name": "science"}],
        "description": None,
    }
    dirty = {
        "title": "Ordered",
        "uuid": "u-2",
        "authors": [
            {"name": "Bob", "role": "author", "position": 9, "id": -10},
            "Alice",
        ],
        "series": {"name": "Saga", "index": "1"},
        "identifiers": [
            {"scheme": "GOOGLE", "val": "gid"},
            {"type": "ISBN", "value": "111"},
        ],
        "languages": ["ita", "eng", "eng"],
        "tags": ["science", {"name": "fiction", "id": -2}],
        "comments": "",
        "rating": 0,
    }
    assert _hash(canonical) == _hash(dirty)
