<?php

namespace Tests\Server;

use Tests\TestCase;

class BooksHashViewSoftDeleteFilterTest extends TestCase
{
    public function test_optimize_hash_view_migration_excludes_soft_deleted_books(): void
    {
        $path = base_path('database/migrations/2026_03_02_123000_optimize_hash_views_with_uuid_joins.php');
        $sql = file_get_contents($path);

        $this->assertNotFalse($sql, 'Migration file not readable');
        $this->assertStringContainsString(
            'b.deleted_at IS NULL',
            $sql,
            'books_hash_v2 migration must exclude soft-deleted books from hash computation'
        );
    }

    public function test_mysql_schema_books_hash_v2_view_excludes_soft_deleted_books(): void
    {
        $path = base_path('database/schema/mysql-schema.sql');
        $schema = file_get_contents($path);

        $this->assertNotFalse($schema, 'mysql-schema.sql not readable');
        $this->assertStringContainsString(
            '(`b`.`deleted_at` is null)',
            strtolower($schema),
            'mysql schema books_hash_v2 view must include deleted_at filter'
        );
    }
}
