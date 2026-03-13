<?php

namespace Tests\Server;

use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Tests\TestCase;

class CalibreTablesUuidTest extends TestCase
{
    private array $calibreTables = [
        'book_authors',
        'book_series',
        'book_sources',
        'book_tags',
        'bookmarks',
        'books',
        'books_authors',
        'books_authors_link',
        'books_files',
        'books_identifiers',
        'books_languages',
        'books_languages_link',
        'books_publishers',
        'books_publishers_link',
        'books_ratings',
        'books_ratings_links',
        'books_series',
        'books_series_link',
        'books_tags',
        'books_tags_link',
    ];

    public function test_calibre_tables_expose_not_null_uuid_columns(): void
    {
        foreach ($this->calibreTables as $table) {
            if (!Schema::hasTable($table)) {
                $this->markTestSkipped("Table {$table} does not exist in this testing environment.");
            }
            $column = $this->getColumnInfo($table, 'uuid');
            $this->assertNotNull($column, "{$table}.uuid column is missing");
            $this->assertFalse($column->nullable, "{$table}.uuid must be NOT NULL");
        }
    }

    public function test_calibre_tables_have_uuid_user_library_unique_indexes(): void
    {
        if (Schema::getConnection()->getDriverName() === 'pgsql') {
            $this->markTestSkipped('Canonical PostgreSQL schema does not currently expose the same uuid/user/library unique index set as MySQL.');
        }

        foreach ($this->calibreTables as $table) {
            if (!Schema::hasTable($table)) {
                continue;
            }
            if (!$this->tableHasUserLibraryColumns($table)) {
                continue;
            }
            $this->assertTrue(
                $this->hasUuidUserLibraryUniqueIndex($table),
                "{$table} must expose a unique index on (uuid, user_id, library_id)"
            );
        }
    }

    private function getColumnInfo(string $table, string $column): ?\stdClass
    {
        $driver = Schema::getConnection()->getDriverName();
        if ($driver === 'sqlite') {
            $info = collect(DB::select("PRAGMA table_info('{$table}')"))
                ->first(fn ($row) => $row->name === $column);
            if (!$info) {
                return null;
            }
            return (object)[
                'nullable' => $info->notnull === 0,
            ];
        }

        if ($driver === 'pgsql') {
            $row = DB::selectOne(
                <<<'SQL'
                SELECT is_nullable
                FROM information_schema.columns
                WHERE table_schema = current_schema()
                  AND table_name = ?
                  AND column_name = ?
                SQL,
                [$table, $column]
            );
            if (!$row) {
                return null;
            }
            return (object)[
                'nullable' => (($row->is_nullable ?? null) === 'YES'),
            ];
        }

        $row = DB::selectOne("SHOW COLUMNS FROM `{$table}` WHERE `Field` = ?", [$column]);
        if (!$row) {
            return null;
        }

        return (object)[
            'nullable' => $row->Null === 'YES',
        ];
    }

    private function tableHasUserLibraryColumns(string $table): bool
    {
        return Schema::hasColumn($table, 'user_id') && Schema::hasColumn($table, 'library_id');
    }

    private function hasUuidUserLibraryUniqueIndex(string $table): bool
    {
        $indexName = "{$table}_uuid_user_library_unique";
        $driver = Schema::getConnection()->getDriverName();
        if ($driver === 'sqlite') {
            $indexes = DB::select("PRAGMA index_list('{$table}')");
            foreach ($indexes as $index) {
                if (($index->name ?? $index['name'] ?? null) === $indexName && ($index->unique ?? $index['unique'] ?? 0) == 1) {
                    return true;
                }
            }
            return false;
        }

        if ($driver === 'pgsql') {
            $row = DB::selectOne(
                <<<'SQL'
                SELECT 1
                FROM pg_indexes
                WHERE schemaname = current_schema()
                  AND tablename = ?
                  AND indexname = ?
                SQL,
                [$table, $indexName]
            );

            return $row !== null;
        }

        return count(DB::select("SHOW INDEX FROM `{$table}` WHERE Key_name = ?", [$indexName])) > 0;
    }
}
