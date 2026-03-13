<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class RuntimeMetadataIdxServerAssignedSchemaTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Runtime idx schema defaults are validated on MySQL/PostgreSQL.');
        }
    }

    public function test_runtime_metadata_tables_have_server_assigned_idx(): void
    {
        $tables = [
            'books',
            'books_authors',
            'books_authors_link',
            'books_tags',
            'books_tags_link',
            'books_series',
            'books_series_link',
            'books_publishers',
            'books_publishers_link',
            'books_languages',
            'books_languages_link',
            'books_identifiers',
            'books_ratings',
            'books_ratings_links',
        ];

        $driver = DB::getDriverName();
        foreach ($tables as $table) {
            if ($driver === 'mysql') {
                $row = DB::table('information_schema.columns')
                    ->selectRaw('`EXTRA` as extra_value')
                    ->whereRaw('table_schema = database()')
                    ->where('table_name', $table)
                    ->where('column_name', 'idx')
                    ->first();
                $this->assertNotNull($row, "Missing idx column for {$table}");
                $this->assertStringContainsString('auto_increment', strtolower((string) $row->extra_value), "idx for {$table} must be AUTO_INCREMENT on MySQL");
            } elseif ($driver === 'pgsql') {
                $row = DB::table('information_schema.columns')
                    ->select('column_default')
                    ->where('table_schema', 'public')
                    ->where('table_name', $table)
                    ->where('column_name', 'idx')
                    ->first();
                $this->assertNotNull($row, "Missing idx column for {$table}");
                $this->assertStringContainsString('nextval(', strtolower((string) $row->column_default), "idx for {$table} must use sequence default on PostgreSQL");
            }
        }
    }
}
