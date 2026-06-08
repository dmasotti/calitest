"""Cross-platform golden hash vectors: Python == PHP == Dart == SQL VIEW.

These hashes are pinned against MetadataHasher::computeHash() (PHP),
computeCanonicalMetadataHashFromMap() (Dart), and the books_hash_v2 SQL VIEW.

If this test fails, one of the implementations has diverged. Do NOT update
the expected hashes without verifying all 4 implementations agree.

Companion tests:
- html/tests/Feature/Sync/HashViewVsHasherConvergenceTest.php
- flutter/calimob/test/sync/sync_convergence_edge_cases_test.dart (EC-06)
"""

import os
import sys

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
_ROOT = os.path.abspath(os.path.join(_THIS_DIR, "..", "..", ".."))
if _ROOT not in sys.path:
    sys.path.insert(0, _ROOT)

from sync_calimob.sync_utils import compute_metadata_hash  # noqa: E402


# Golden vectors: must match PHP MetadataHasher, Dart canonical hash, SQL VIEW
GOLDEN = [
    {
        "uuid": "aaaaaaaa-0001-4000-a000-000000000001",
        "title": "Rating Book",
        "authors": [{"name": "Test Author"}],
        "rating": 8,
        "pubdate": "2023-01-15",
        "languages": ["eng"],
        "expected_hash": "a4487ab0368efc3b53ebed3569e1b5536c814d10768dd052f922276c3c7be99c",
    },
    {
        "uuid": "aaaaaaaa-0002-4000-a000-000000000002",
        "title": "No Rating",
        "authors": [{"name": "Author Two"}],
        "pubdate": "2020-06-01",
        "languages": ["fra"],
        "expected_hash": "95553a9b19adee0059e6206ed7e44b591c200e9669d3dcd92b7b03ec1bfb9736",
    },
    {
        "uuid": "aaaaaaaa-0003-4000-a000-000000000003",
        "title": "Series Book",
        "authors": [{"name": "Jane Doe"}],
        "series": {"name": "Epic Saga", "series_index": 3.0},
        "rating": 6,
        "tags": [{"name": "fantasy"}, {"name": "adventure"}],
        "pubdate": "2019-03-20",
        "languages": ["eng"],
        "publisher": "Big Press",
        "expected_hash": "0359ec1549caa3358b560a22ca020688bf89ae530c6e363165e7f60028fad812",
    },
    {
        "uuid": "aaaaaaaa-0004-4000-a000-000000000004",
        "title": "Unicode\u2019s \"Test\"",
        "authors": [{"name": "M\u00fcller, Hans"}],
        "rating": 10,
        "languages": ["deu"],
        "description": "A <b>bold</b> description.",
        "expected_hash": "7c6e24eea6e46b115ea6e6995adcf30e951044681a0ad642a7fcbf90ab68deb6",
    },
]


def test_golden_hashes_match_cross_platform():
    """Each golden vector must produce the exact expected hash."""
    for vector in GOLDEN:
        item = {k: v for k, v in vector.items() if k != "expected_hash"}
        actual = compute_metadata_hash(item, {}, None)
        assert actual == vector["expected_hash"], (
            f"Hash mismatch for {vector['uuid']} ({vector['title']}): "
            f"got {actual}, expected {vector['expected_hash']}"
        )


def test_rating_is_float_in_hash_payload():
    """Rating must be emitted as float (8.0 not 8) in the hash payload."""
    from sync_calimob.sync_utils import build_metadata_hash_payload
    import json

    item = {"uuid": "test", "title": "Test", "rating": 8}
    payload = build_metadata_hash_payload(item)
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert '"rating":8.0' in normalized, (
        f"Rating should be float 8.0 in payload, got: {normalized}"
    )


def test_zero_rating_omitted():
    """Rating 0 / null must be omitted from the hash payload."""
    from sync_calimob.sync_utils import build_metadata_hash_payload

    for rating_val in [0, 0.0, None, "0"]:
        item = {"uuid": "test", "title": "Test", "rating": rating_val}
        payload = build_metadata_hash_payload(item)
        metadata = payload.get("metadata", {})
        assert "rating" not in metadata, (
            f"Rating {rating_val!r} should be omitted, but found in payload"
        )
