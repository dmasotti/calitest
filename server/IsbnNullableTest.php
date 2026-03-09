<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Tests\TestCase;

class IsbnNullableTest extends TestCase
{
    use RefreshDatabase;

    public function test_books_isbn_column_allows_null_client_payloads(): void
    {
        $this->assertTrue(Schema::hasTable('books'), 'books table is missing');
        $this->assertTrue(Schema::hasColumn('books', 'isbn'), 'books.isbn column is missing');
        $this->assertTrue($this->isColumnNullable('books', 'isbn'), 'books.isbn must be nullable to accept headless payloads without ISBN');
    }

    public function test_global_books_isbn_column_allows_null(): void
    {
        $this->assertTrue(Schema::hasTable('global_books'), 'global_books table is missing');
        $this->assertTrue(Schema::hasColumn('global_books', 'isbn'), 'global_books.isbn column is missing');
        $this->assertTrue($this->isColumnNullable('global_books', 'isbn'), 'global_books.isbn must be nullable so normalization can skip it');
    }

    private function isColumnNullable(string $table, string $column): bool
    {
        $driver = DB::getDriverName();
        if ($driver === 'sqlite') {
            $info = collect(DB::select("PRAGMA table_info('{$table}')"))
                ->first(fn ($row) => ($row->name ?? null) === $column);

            if (!$info) {
                return false;
            }

            return ((int) ($info->notnull ?? 1)) === 0;
        }

        $info = DB::selectOne("SHOW COLUMNS FROM `{$table}` WHERE `Field` = ?", [$column]);
        return $info !== null && ($info->Null ?? 'NO') === 'YES';
    }
}
