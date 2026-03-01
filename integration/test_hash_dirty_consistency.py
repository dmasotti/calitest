"""
Cross-check metadata hash consistency (Python vs PHP) using dirty payloads.
"""
import json
import re
import subprocess
import tempfile
from pathlib import Path

import sys

sync_calimob_path = Path(__file__).parent.parent.parent / "sync_calimob"
sys.path.insert(0, str(sync_calimob_path))
import sync_utils


ROOT = Path(__file__).resolve().parents[2]
PHP_HELPER = ROOT / "tests" / "compute_hash.php"


def php_hash(payload):
    with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
        json.dump(payload, f)
        json_path = f.name
    try:
        res = subprocess.run(
            ["php", str(PHP_HELPER), json_path],
            capture_output=True,
            text=True,
            timeout=20,
        )
        assert res.returncode == 0, res.stderr
        matches = re.findall(r"\b[a-fA-F0-9]{64}\b", res.stdout or "")
        assert matches, f"No hash in PHP output: {res.stdout!r}"
        return matches[-1].lower()
    finally:
        Path(json_path).unlink(missing_ok=True)


def py_hash(payload):
    return sync_utils.compute_metadata_hash(payload, format_cache={}, cover_hash=None)


def test_dirty_payload_hash_matches_php():
    payload = {
        "id": 123,
        "uuid": "u-dirty-1",
        "title": "Hash Dirty",
        "title_sort": "IGNORE",
        "author_sort": "IGNORE",
        "authors": [
            {"name": "Bob", "role": "author", "position": 9, "id": -2},
            {"name": "Alice", "role": "author", "position": 0, "link": ""},
        ],
        "series": {"name": "Saga", "index": "1"},
        "identifiers": [
            {"type": "ISBN", "value": "978111"},
            {"scheme": "GOOGLE", "val": "gid"},
        ],
        "publisher": "",
        "pubdate": None,
        "languages": ["ita", "eng", "eng"],
        "tags": [{"name": "science", "id": -10}, "fiction"],
        "rating": 0,
        "comments": "",
        "last_modified": 1772100000,
        "files": [{"format": "EPUB", "file_hash": "sha256:abc"}],
        "formats": [{"format": "EPUB"}],
        "cover": {"cover_hash": "sha256:def"},
        "extra": {"x": 1},
    }
    assert py_hash(payload) == php_hash(payload)

