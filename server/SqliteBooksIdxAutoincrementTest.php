<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class SqliteBooksIdxAutoincrementTest extends TestCase
{
    use RefreshDatabase;

    public function test_books_idx_is_autoincrement_in_sqlite_testing_schema(): void
    {
        if (DB::getDriverName() !== 'sqlite') {
            $this->markTestSkipped('This contract test is specific to sqlite testing schema.');
        }

        $row = DB::selectOne("SELECT sql FROM sqlite_master WHERE type='table' AND name='books'");
        $this->assertNotNull($row, 'books table must exist in sqlite test schema');

        $createSql = (string) ($row->sql ?? '');
        $this->assertMatchesRegularExpression(
            '/\bidx\b\s+INTEGER\s+PRIMARY\s+KEY\s+AUTOINCREMENT/i',
            $createSql,
            'books.idx must be declared as INTEGER PRIMARY KEY AUTOINCREMENT in sqlite'
        );

        DB::table('books')->insert([
            'uuid' => '11111111-1111-1111-1111-111111111111',
            'title' => 'Auto Idx Test Book',
            'path' => '',
        ]);

        $book = DB::table('books')
            ->where('uuid', '11111111-1111-1111-1111-111111111111')
            ->first();

        $this->assertNotNull($book);
        $this->assertNotNull($book->idx);
        $this->assertGreaterThan(0, (int) $book->idx);
    }
}

