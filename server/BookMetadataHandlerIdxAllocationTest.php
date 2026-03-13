<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class BookMetadataHandlerIdxAllocationTest extends TestCase
{
    use RefreshDatabase;

    public function test_apply_book_metadata_does_not_query_max_idx_for_runtime_tables(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Idx Allocation Matrix',
        ]);

        $book = UserBook::create([
            'id' => 9301,
            'uuid' => 'dd000000-0000-4000-8000-000000009301',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Idx Allocation Test',
            'path' => 'idx-allocation-test',
            'author_sort' => 'Tester, Idx',
            'last_modified' => now(),
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        app(BookMetadataHandler::class)->applyBookMetadata($book, [
            'authors' => [
                ['name' => 'Marcus Sakey'],
                ['name' => 'H. G. Wells'],
            ],
            'tags' => [
                ['name' => 'Quebec'],
                ['name' => 'Québec'],
            ],
            'series' => [
                'name' => 'Series X',
                'series_index' => 2.0,
            ],
            'publisher' => ['name' => 'Publisher X'],
            'languages' => ['eng', 'ita'],
            'identifiers' => [
                'isbn' => '9781234567890',
                'goodreads' => '42',
            ],
            'rating' => 8,
        ], $user, $library->id);

        $maxIdxQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'max(') && str_contains($sql, 'idx');
        }));

        $this->assertSame([], $maxIdxQueries, 'Metadata apply must rely on DB-assigned idx, not MAX(idx) allocation queries');
    }

    public function test_apply_book_metadata_reuses_negative_id_allocator_per_table(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Negative Id Allocator Matrix',
        ]);

        $book = UserBook::create([
            'id' => 9302,
            'uuid' => 'dd000000-0000-4000-8000-000000009302',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Negative Id Allocation Test',
            'path' => 'negative-id-allocation-test',
            'author_sort' => 'Tester, Negative',
            'last_modified' => now(),
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        app(BookMetadataHandler::class)->applyBookMetadata($book, [
            'authors' => [
                ['name' => 'Marcus Sakey'],
                ['name' => 'H. G. Wells'],
            ],
            'tags' => [
                ['name' => 'Quebec'],
                ['name' => 'Québec'],
            ],
            'identifiers' => [
                'isbn' => '9781234567890',
                'goodreads' => '42',
                'asin' => 'B000123456',
            ],
        ], $user, $library->id);

        $countMinIdQueries = static function (array $allQueries, string $table): int {
            return count(array_filter($allQueries, static function (string $sql) use ($table): bool {
                $tablePattern = '/(?:from|into|update)\s+(?:[`"]?public[`"]?\.)?[`"]?' . preg_quote($table, '/') . '[`"]?(?:\s|$)/';
                return str_contains($sql, 'min(')
                    && str_contains($sql, 'id')
                    && preg_match($tablePattern, $sql) === 1;
            }));
        };

        $this->assertLessThanOrEqual(1, $countMinIdQueries($queries, 'books_authors'), 'authors must allocate negative ids with at most one MIN(id) query per batch');
        $this->assertLessThanOrEqual(1, $countMinIdQueries($queries, 'books_tags'), 'tags must allocate negative ids with at most one MIN(id) query per batch');
        $this->assertLessThanOrEqual(1, $countMinIdQueries($queries, 'books_identifiers'), 'identifiers must allocate negative ids with at most one MIN(id) query per batch');
    }
}
