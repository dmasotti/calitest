<?php

namespace Tests\Server;

use Tests\TestCase;

class BooksHashViewCanonicalizationSqlTest extends TestCase
{
    private function migrationSql(): string
    {
        $path = base_path('database/migrations/2026_03_03_214500_fix_books_hash_v2_pubdate_and_rating_calibre_parity.php');
        $sql = file_get_contents($path);
        $this->assertNotFalse($sql, 'Migration file not readable');
        return (string) $sql;
    }

    public function test_books_hash_v2_migration_normalizes_pubdate_from_epoch(): void
    {
        $sql = $this->migrationSql();
        $this->assertStringContainsString(
            "TIMESTAMP('1970-01-01 00:00:00') + INTERVAL CAST(b.pubdate AS UNSIGNED) SECOND",
            $sql,
            'books_hash_v2 must normalize numeric pubdate to calibre-compatible UTC timestamp string'
        );
        $this->assertStringContainsString(
            "%Y-%m-%d %H:%i:%s+00:00",
            $sql,
            'books_hash_v2 pubdate normalization must include +00:00 suffix'
        );
    }

    public function test_books_hash_v2_migration_maps_null_pubdate_to_calibre_sentinel(): void
    {
        $sql = $this->migrationSql();

        $this->assertStringContainsString(
            "WHEN b.pubdate IS NULL THEN '0101-01-01 00:00:00+00:00'",
            $sql,
            'books_hash_v2 must map NULL pubdate to calibre sentinel'
        );
    }

    public function test_books_hash_v2_migration_uses_rating_link_tables(): void
    {
        $sql = $this->migrationSql();
        $this->assertStringContainsString(
            'FROM books_ratings_links brl',
            $sql,
            'books_hash_v2 must read rating from books_ratings_links'
        );
        $this->assertStringContainsString(
            'JOIN books_ratings br',
            $sql,
            'books_hash_v2 must join books_ratings for canonical rating value'
        );
    }

    public function test_books_hash_v2_migration_preserves_native_calibre_rating_scale(): void
    {
        $sql = $this->migrationSql();

        $this->assertStringNotContainsString(
            'rating_value * 2',
            $sql,
            'books_hash_v2 must not scale rating away from native Calibre 0..10 values'
        );
        $this->assertStringContainsString(
            'ELSE rating_agg.rating_value',
            $sql,
            'books_hash_v2 must preserve native rating values instead of remapping them to a star scale'
        );
        $this->assertStringContainsString(
            'AS CHAR',
            $sql,
            'books_hash_v2 must preserve native rating values in the canonical hash payload'
        );
    }

    public function test_library_hash_uses_concatenated_metadata_hashes_not_raw_payload(): void
    {
        $sql = $this->migrationSql();
        $this->assertStringContainsString(
            'SHA2(GROUP_CONCAT(SHA2(hash_payload, 256) ORDER BY uuid SEPARATOR \'\'), 256) as library_metadata_hash',
            $sql,
            'library_hash view must compute root from per-book metadata hashes'
        );
    }
}
