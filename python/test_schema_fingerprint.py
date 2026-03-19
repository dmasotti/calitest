"""Tests for schema fingerprint guardrails."""

from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "scripts" / "schema_fingerprint.py"

spec = spec_from_file_location("schema_fingerprint", str(MODULE_PATH))
schema_fingerprint = module_from_spec(spec)
assert spec.loader is not None
spec.loader.exec_module(schema_fingerprint)


def test_domain_sync_profile_excludes_non_sync_and_test_only_tables() -> None:
    excluded = schema_fingerprint.excluded_tables("domain-sync", "")

    assert "test_books_hash_v2" in excluded
    assert "test_library_hash" in excluded
    assert "test_merkle_root" in excluded
    assert "test_merkle_branches" in excluded
    assert "test_merkle_leaves" in excluded
    assert "template_config" in excluded
    assert "template_configs" in excluded
    assert "template_configurations" in excluded
    assert "template_settings" in excluded
    assert "template_usage_logs" in excluded
    assert "template_variants" in excluded
    assert "user_template_assignments" in excluded
    assert "user_template_file_versions" in excluded


def test_domain_sync_profile_keeps_sync_runtime_tables() -> None:
    excluded = schema_fingerprint.excluded_tables("domain-sync", "")

    assert "books" not in excluded
    assert "books_files" not in excluded
    assert "books_hash_v2" not in excluded
    assert "sync_mappings" not in excluded
    assert "sync_merkle_roots" not in excluded
    assert "sync_merkle_branches" not in excluded
    assert "sync_merkle_leaves" not in excluded


def test_mysql_view_columns_ignore_derived_default_and_collation_noise() -> None:
    columns = [
        {
            "name": "last_modified",
            "ordinal": "10",
            "type": "timestamp",
            "nullable": "NO",
            "default": "2000-01-01 01:00:00",
            "extra": "",
            "collation": "",
        },
        {
            "name": "hash_payload",
            "ordinal": "11",
            "type": "longtext",
            "nullable": "YES",
            "default": "<NULL>",
            "extra": "",
            "collation": "utf8mb4_unicode_ci",
        },
    ]

    normalized = schema_fingerprint.normalize_columns_for_table_kind(
        driver="mysql",
        table_kind="VIEW",
        columns=columns,
    )

    assert normalized[0]["default"] == "<DERIVED>"
    assert normalized[0]["collation"] == ""
    assert normalized[1]["default"] == "<DERIVED>"
    assert normalized[1]["collation"] == "<DERIVED>"


def test_mysql_table_columns_keep_real_default_and_collation() -> None:
    columns = [
        {
            "name": "title",
            "ordinal": "1",
            "type": "varchar(255)",
            "nullable": "NO",
            "default": "Unknown",
            "extra": "",
            "collation": "utf8mb4_unicode_ci",
        }
    ]

    normalized = schema_fingerprint.normalize_columns_for_table_kind(
        driver="mysql",
        table_kind="BASE TABLE",
        columns=columns,
    )

    assert normalized == columns
