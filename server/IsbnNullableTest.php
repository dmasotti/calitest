<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class IsbnNullableTest extends TestCase
{
    use RefreshDatabase;

    public function test_books_isbn_column_allows_null_client_payloads(): void
    {
        $column = DB::selectOne("SHOW COLUMNS FROM `books` WHERE `Field` = 'isbn'");
        $this->assertNotNull($column, 'books.isbn column is missing');
        $this->assertSame('YES', $column->Null, 'books.isbn must be nullable to accept headless payloads without ISBN');
    }

    public function test_global_books_isbn_column_allows_null(): void
    {
        $column = DB::selectOne("SHOW COLUMNS FROM `global_books` WHERE `Field` = 'isbn'");
        $this->assertNotNull($column, 'global_books.isbn column is missing');
        $this->assertSame('YES', $column->Null, 'global_books.isbn must be nullable so normalization can skip it');
    }
}
