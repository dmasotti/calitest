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
        "expected_hash": "cec7af6f0911d31373efec64f09d84107623dbd2690758a969bc147a68caf5fa",
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
        "expected_hash": "419f3f644f19e86b6e5fa66f95ec3edda22df16801e5969576279f64dd8905fb",
    },
    {
        "uuid": "aaaaaaaa-0004-4000-a000-000000000004",
        "title": "Unicode\u2019s \"Test\"",
        "authors": [{"name": "M\u00fcller, Hans"}],
        "rating": 10,
        "languages": ["deu"],
        "description": "A <b>bold</b> description.",
        "expected_hash": "442acce493774b74a8a082574ba0dc257970b730b4d968865e5d6c3cdf2b1c3c",
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


def test_rating_is_integer_in_hash_payload():
    """Rating must be emitted as INTEGER (8 not 8.0) in the hash payload.

    CANONICAL DECISION (do NOT revert): rating is a whole 0-10 scale and is
    encoded as an integer across the server VIEW books_hash_v2, all PHP hashers,
    this plugin, and the Dart app. The earlier float form ("8.0") was WRONG and
    caused permanent Merkle mismatch. series_index STAYS float ("1.0").
    """
    from sync_calimob.sync_utils import build_metadata_hash_payload
    import json

    item = {"uuid": "test", "title": "Test", "rating": 8}
    payload = build_metadata_hash_payload(item)
    normalized = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    assert '"rating":8' in normalized and '"rating":8.0' not in normalized, (
        f"Rating should be integer 8 in payload, got: {normalized}"
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
