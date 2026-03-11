<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class BookMetadataHandlerIdentifiersEdgeMatrixTest extends TestCase
{
    use RefreshDatabase;

    public function test_identifiers_noop_update_does_not_delete_existing_rows(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $this->insertIdentifier($user, $library, $book, 4101, 'amazon', 'A1');
        $this->insertIdentifier($user, $library, $book, 4102, 'isbn', '9780000000001');

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'identifiers' => [
                'isbn' => '9780000000001',
                'amazon' => 'A1',
            ],
        ], $user, $library->id);

        $deleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete') && str_contains($sql, 'books_identifiers');
        }));

        $this->assertSame([], $deleteQueries, 'No-op identifiers update must not delete and recreate rows');
        $this->assertSame([
            'amazon' => 'A1',
            'isbn' => '9780000000001',
        ], $this->identifiersForBook($user, $library, $book));
    }

    public function test_identifiers_edge_matrix_deduplicates_payload_and_uses_bulk_insert(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'identifiers' => [
                ['type' => 'amazon', 'value' => 'A1'],
                ['type' => 'isbn', 'value' => '9780000000001'],
                ['type' => 'amazon', 'value' => 'A1'],
                ['type' => 'isbn', 'value' => '9780000000001'],
                ['type' => 'google', 'value' => 'G1'],
            ],
        ], $user, $library->id);

        $insertQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'insert into `books_identifiers`');
        }));

        $this->assertLessThanOrEqual(1, count($insertQueries), 'Identifier persistence must use one bulk insert, not row-by-row inserts');
        $this->assertSame([
            'amazon' => 'A1',
            'google' => 'G1',
            'isbn' => '9780000000001',
        ], $this->identifiersForBook($user, $library, $book));
    }

    public function test_identifiers_edge_matrix_explicit_empty_payload_clears_rows_and_isbn(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'identifiers' => [
                'isbn' => '9780000000001',
                'amazon' => 'A1',
            ],
        ], $user, $library->id);

        $handler->applyBookMetadata($book, [
            'identifiers' => [],
        ], $user, $library->id);

        $this->assertSame([], $this->identifiersForBook($user, $library, $book));
        $this->assertNull($book->fresh()->isbn);
    }

    public function test_identifiers_edge_matrix_normalizes_assoc_map_and_list_equally(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'identifiers' => [
                'isbn' => '9780000000001',
                'amazon' => 'A1',
            ],
        ], $user, $library->id);

        $first = $this->identifiersForBook($user, $library, $book);

        $handler->applyBookMetadata($book, [
            'identifiers' => [
                ['type' => 'amazon', 'value' => 'A1'],
                ['type' => 'isbn', 'value' => '9780000000001'],
            ],
        ], $user, $library->id);

        $this->assertSame($first, $this->identifiersForBook($user, $library, $book));
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Identifiers Edge Matrix',
        ]);

        $book = UserBook::create([
            'id' => 9601,
            'uuid' => 'dd000000-0000-4000-8000-000000009601',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Identifiers Test Book',
            'path' => 'identifiers-test-book',
            'author_sort' => 'Tester, Identifiers',
            'last_modified' => now(),
        ]);

        return [$user, $library, $book->fresh()];
    }

    private function insertIdentifier(User $user, Library $library, UserBook $book, int $id, string $type, string $value): void
    {
        DB::table('books_identifiers')->insert([
            'id' => $id,
            'idx' => $id,
            'book' => $book->uuid,
            'type' => $type,
            'val' => $value,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => sprintf('00000000-0000-4000-8000-%012d', $id),
            'created_at' => now(),
            'updated_at' => now(),
        ]);
    }

    private function identifiersForBook(User $user, Library $library, UserBook $book): array
    {
        return DB::table('books_identifiers')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('book', $book->uuid)
            ->orderBy('type')
            ->pluck('val', 'type')
            ->all();
    }
}
