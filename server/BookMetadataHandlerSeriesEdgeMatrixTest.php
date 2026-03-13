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

    public function test_series_resolution_reuses_handler_cache_across_books(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $otherBook = UserBook::create([
            'id' => 9302,
            'uuid' => 'dd000000-0000-4000-8000-000000009302',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Series Test Book 2',
            'path' => 'series-test-book-2',
            'author_sort' => 'Tester, Series',
            'last_modified' => now(),
        ]);
        $handler = app(BookMetadataHandler::class);

        $this->createSeries($user, $library, 2202, 'Shared Series');

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $payload = [
            'series' => [
                'name' => 'Shared Series',
                'index' => 2.0,
            ],
        ];
        $handler->applyBookMetadata($book, $payload, $user, $library->id);
        $handler->applyBookMetadata($otherBook, $payload, $user, $library->id);

        $seriesSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'from `books_series`') && str_contains($sql, 'select');
        }));

        $this->assertLessThanOrEqual(
            2,
            count($seriesSelects),
            'Series resolution should be cached across multiple books in the same handler lifecycle'
        );
    }

    public function test_series_sync_mapping_resolution_reuses_handler_cache_across_books(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $otherBook = UserBook::create([
            'id' => 9303,
            'uuid' => 'dd000000-0000-4000-8000-000000009303',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Series Test Book 3',
            'path' => 'series-test-book-3',
            'author_sort' => 'Tester, Series',
            'last_modified' => now(),
        ]);
        $handler = app(BookMetadataHandler::class);

        $series = $this->createSeries($user, $library, 2203, 'Mapped Shared Series');
        DB::table('sync_mappings')->insert([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'entity_type' => 'series',
            'client_key' => 'calibre:series:2203',
            'server_id' => $series->id,
            'uuid' => sprintf('00000000-0000-4000-8000-%012d', $series->id),
            'meta' => json_encode(['client_val' => 2203]),
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $payload = [
            'series' => [
                'name' => 'Mapped Shared Series',
                'index' => 2.0,
                'client_ids' => ['calibre:series:2203' => 2203],
            ],
        ];

        $handler->applyBookMetadata($book, $payload, $user, $library->id);
        $handler->applyBookMetadata($otherBook, $payload, $user, $library->id);

        $mappingSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return (str_contains($sql, 'from "sync_mappings"') || str_contains($sql, 'from `sync_mappings`'))
                && str_contains($sql, 'select');
        }));

        $this->assertLessThanOrEqual(
            2,
            count($mappingSelects),
            'Series mapping resolution should be cached across multiple books in the same handler lifecycle'
        );
    }

    public function test_series_sync_mapping_persist_uses_bulk_upsert_not_update_or_create(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'series' => [
                'name' => 'Bulk Persist Saga',
                'index' => 1.0,
                'client_ids' => ['calibre:series:bulk' => 1],
            ],
        ], $user, $library->id);

        $mappingWrites = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'sync_mappings')
                && (str_contains($sql, 'insert') || str_contains($sql, 'update'));
        }));

        $this->assertLessThanOrEqual(
            2,
            count($mappingWrites),
            'Series mapping persistence must use bulk write, not per-item updateOrCreate'
        );
    }

    public function test_series_mapping_only_update_with_same_final_link_does_not_write_pivot(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $series = $this->createSeries($user, $library, 2251, 'Mapped Cycle');

        DB::table('books_series_link')->insert([
            'uuid' => 'series-pivot-map-noop',
            'book' => $book->uuid,
            'series' => $series->id,
            'series_index' => 2.0,
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'series' => [
                'name' => 'Mapped Cycle',
                'index' => 2.0,
                'client_ids' => ['calibre:series:2251' => 2251],
            ],
        ], $user, $library->id);

        $pivotWrites = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'books_series_link')
                && (str_contains($sql, 'insert') || str_contains($sql, 'update') || str_contains($sql, 'delete'));
        }));

        $this->assertSame([], $pivotWrites, 'Mapping-only series update with identical final link must not write pivot rows');
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

    public function test_series_index_only_change_updates_existing_link_without_delete(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $series = $this->createSeries($user, $library, 2301, 'Index Shift Saga');

        DB::table('books_series_link')->insert([
            'uuid' => 'series-pivot-2',
            'book' => $book->uuid,
            'series' => $series->id,
            'series_index' => 1.0,
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'series' => [
                'name' => 'Index Shift Saga',
                'index' => 2.5,
            ],
        ], $user, $library->id);

        $deleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete') && str_contains($sql, 'books_series_link');
        }));

        $this->assertSame([], $deleteQueries, 'Changing only series_index must update the existing pivot without delete+reinsert');
        $this->assertSame(['name' => 'Index Shift Saga', 'series_index' => 2.5], $this->seriesStateForBook($book, $user, $library));
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

    public function test_series_and_rating_combined_update_saves_book_row_once(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'series' => [
                'name' => 'Marcus Cycle',
                'index' => 4.0,
            ],
            'rating' => 8,
        ], $user, $library->id);

        $bookUpdates = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'update "books" set')
                || str_contains($sql, 'update `books` set');
        }));

        $this->assertLessThanOrEqual(
            1,
            count($bookUpdates),
            'Combined series+rating metadata apply should persist the books row once'
        );
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
