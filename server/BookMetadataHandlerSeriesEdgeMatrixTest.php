<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\Series;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class BookMetadataHandlerSeriesEdgeMatrixTest extends TestCase
{
    use RefreshDatabase;

    public function test_series_noop_update_does_not_delete_existing_link(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $series = $this->createSeries($user, $library, 2101, 'Marcus Cycle');

        DB::table('books_series_link')->insert([
            'uuid' => 'series-pivot-1',
            'book' => $book->uuid,
            'series' => $series->id,
            'series_index' => 7.0,
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'series' => [
                'name' => 'Marcus Cycle',
                'index' => 7.0,
            ],
        ], $user, $library->id);

        $deleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete') && str_contains($sql, 'books_series_link');
        }));

        $this->assertSame([], $deleteQueries, 'No-op series update must not delete and recreate pivot rows');
        $this->assertSame(['name' => 'Marcus Cycle', 'series_index' => 7.0], $this->seriesStateForBook($book, $user, $library));
    }

    public function test_series_existing_resolution_is_prefetched_not_extra_lookups(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $this->createSeries($user, $library, 2201, 'Québec Saga');

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'series' => [
                'name' => 'Québec Saga',
                'index' => 3.5,
            ],
        ], $user, $library->id);

        $seriesSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'from `books_series`') && str_contains($sql, 'select');
        }));

        $this->assertLessThanOrEqual(
            2,
            count($seriesSelects),
            'Series resolution should be a bounded lookup, not repeated row-by-row queries'
        );
    }

    public function test_series_edge_matrix_trims_name_and_updates_index(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'series' => [
                'name' => '  AC/DC Chronicle  ',
                'index' => 4.5,
            ],
        ], $user, $library->id);

        $this->assertSame(['name' => 'AC/DC Chronicle', 'series_index' => 4.5], $this->seriesStateForBook($book, $user, $library));
    }

    public function test_series_edge_matrix_explicit_empty_value_clears_link(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'series' => [
                'name' => 'Marcus Cycle',
                'index' => 1.0,
            ],
        ], $user, $library->id);

        $handler->applyBookMetadata($book, [
            'series' => null,
        ], $user, $library->id);

        $this->assertNull($this->seriesStateForBook($book, $user, $library));
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Series Edge Matrix',
        ]);

        $book = UserBook::create([
            'id' => 9301,
            'uuid' => 'dd000000-0000-4000-8000-000000009301',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Series Test Book',
            'path' => 'series-test-book',
            'author_sort' => 'Tester, Series',
            'last_modified' => now(),
        ]);

        return [$user, $library, $book->fresh()];
    }

    private function createSeries(User $user, Library $library, int $id, string $name): Series
    {
        return Series::create([
            'id' => $id,
            'idx' => $id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => $name,
            'sort' => $name,
            'uuid' => sprintf('00000000-0000-4000-8000-%012d', $id),
        ]);
    }

    private function seriesStateForBook(UserBook $book, User $user, Library $library): ?array
    {
        $row = DB::table('books_series_link')
            ->join('books_series', 'books_series_link.series', '=', 'books_series.id')
            ->where('books_series_link.book', $book->uuid)
            ->where('books_series_link.user_id', $user->id)
            ->where('books_series_link.library_id', $library->id)
            ->select([
                'books_series.name as name',
                'books_series_link.series_index as series_index',
            ])
            ->first();

        if (!$row) {
            return null;
        }

        return [
            'name' => (string) $row->name,
            'series_index' => (float) $row->series_index,
        ];
    }
}
