"""Unit tests for sync_matrix_verify helpers (no docker harness required)."""

from sync_matrix_verify import client_cover_item_hash


def test_cover_item_hash_orphan_zeros_hash_when_no_storage_pointer():
    """Server orphan-cover rule: no cover_url + no cover_optimized_path → empty hash."""
    uuid = "11111111-0000-4000-8000-000000000001"
    with_hash = "aa11bb22cc33dd44ee55ff667788990011223344556677889900aabbccddeeff"
    orphan = client_cover_item_hash(uuid, True, with_hash)
    healthy = client_cover_item_hash(
        uuid, True, with_hash, cover_url="https://example.com/cover.jpg"
    )
    assert orphan != healthy
    assert orphan == client_cover_item_hash(uuid, True, None)


def test_cover_item_hash_strips_sha256_prefix_when_bytes_present():
    uuid = "1bed2112-83be-4979-8e26-0e901b0b1eb1"
    prefixed = "sha256:6abc2e3776c525dade37241281c3d02ddf635ed1cddacdb77e4eb20cadb4e4b8"
    raw = "6abc2e3776c525dade37241281c3d02ddf635ed1cddacdb77e4eb20cadb4e4b8"
    assert client_cover_item_hash(
        uuid, True, prefixed, cover_url="https://example.com/c.jpg"
    ) == client_cover_item_hash(uuid, True, raw, cover_url="https://example.com/c.jpg")
