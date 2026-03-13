<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class BooksScopeIndexTest extends TestCase
{
    use RefreshDatabase;

    public function test_books_has_scope_index_for_sync_lookup(): void
    {
        $driver = DB::getDriverName();

        if ($driver === 'pgsql') {
            $rows = DB::select(
                "SELECT indexname FROM pg_indexes WHERE schemaname = 'public' AND tablename = 'books' AND indexname = ?",
                ['books_user_library_uuid_index']
            );

            $this->assertNotEmpty(
                $rows,
                'books must expose books_user_library_uuid_index on PostgreSQL for sync scoped lookups'
            );

            return;
        }

        if (in_array($driver, ['mysql', 'mariadb'], true)) {
            $rows = DB::table('information_schema.statistics')
                ->select('index_name')
                ->whereRaw('table_schema = DATABASE()')
                ->where('table_name', 'books')
                ->where('index_name', 'books_user_library_uuid_index')
                ->get();

            $this->assertTrue(
                $rows->isNotEmpty(),
                'books must expose books_user_library_uuid_index on MySQL for sync scoped lookups'
            );

            return;
        }

        $this->markTestSkipped('Unsupported driver for books scope index introspection.');
    }
}
