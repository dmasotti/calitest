<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class BookMetadataHandlerSchemaIntrospectionCacheTest extends TestCase
{
    use RefreshDatabase;

    public function test_schema_introspection_is_cached_across_books_in_same_handler_lifecycle(): void
    {
        [$user, $library, $firstBook, $secondBook] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $payload = [
            'series' => [
                'name' => 'Schema Cache Saga',
                'index' => 2.0,
            ],
            'publisher' => 'Schema Cache House',
            'rating' => 8,
            'languages' => ['eng', 'ita'],
        ];

        $handler->applyBookMetadata($firstBook, $payload, $user, $library->id);
        $handler->applyBookMetadata($secondBook, $payload, $user, $library->id);

        $schemaQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'information_schema')
                || str_contains($sql, 'pg_catalog')
                || str_contains($sql, 'show columns')
                || str_contains($sql, 'show full columns');
        }));

        $this->assertLessThanOrEqual(
            6,
            count($schemaQueries),
            'Schema introspection should be cached across repeated metadata apply calls in the same handler lifecycle'
        );
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Schema Introspection Cache',
        ]);

        $firstBook = UserBook::create([
            'id' => 9961,
            'uuid' => 'de000000-0000-4000-8000-000000009961',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Schema Cache Book 1',
            'path' => 'schema-cache-book-1',
            'author_sort' => 'Tester, Schema',
            'last_modified' => now(),
        ]);

        $secondBook = UserBook::create([
            'id' => 9962,
            'uuid' => 'de000000-0000-4000-8000-000000009962',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Schema Cache Book 2',
            'path' => 'schema-cache-book-2',
            'author_sort' => 'Tester, Schema',
            'last_modified' => now(),
        ]);

        return [$user, $library, $firstBook->fresh(), $secondBook->fresh()];
    }
}
