<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class BookMetadataHandlerPublisherEdgeMatrixTest extends TestCase
{
    use RefreshDatabase;

    public function test_publisher_noop_update_does_not_delete_existing_link(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $this->createPublisher($user, $library, 3101, 'Snoogyscoob');

        DB::table('books_publishers_link')->insert([
            'uuid' => 'publisher-pivot-1',
            'book' => $book->uuid,
            'publisher' => 3101,
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'publisher' => 'Snoogyscoob',
        ], $user, $library->id);

        $deleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete') && str_contains($sql, 'books_publishers_link');
        }));

        $this->assertSame([], $deleteQueries, 'No-op publisher update must not delete and recreate pivot rows');
        $this->assertSame('Snoogyscoob', $this->publisherNameForBook($book, $user, $library));
    }

    public function test_publisher_existing_resolution_is_prefetched_not_repeated_lookup(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $this->createPublisher($user, $library, 3201, 'Macmillan');

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'publisher' => 'Macmillan',
        ], $user, $library->id);

        $publisherSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'from `books_publishers`') && str_contains($sql, 'select');
        }));

        $this->assertLessThanOrEqual(2, count($publisherSelects));
    }

    public function test_publisher_resolution_reuses_handler_cache_across_books(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $otherBook = UserBook::create([
            'id' => 9402,
            'uuid' => 'dd000000-0000-4000-8000-000000009402',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Publisher Test Book 2',
            'path' => 'publisher-test-book-2',
            'author_sort' => 'Tester, Publisher',
            'last_modified' => now(),
        ]);
        $handler = app(BookMetadataHandler::class);

        $this->createPublisher($user, $library, 3202, 'Shared Publisher');

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $payload = ['publisher' => 'Shared Publisher'];
        $handler->applyBookMetadata($book, $payload, $user, $library->id);
        $handler->applyBookMetadata($otherBook, $payload, $user, $library->id);

        $publisherSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'from `books_publishers`') && str_contains($sql, 'select');
        }));

        $this->assertLessThanOrEqual(
            2,
            count($publisherSelects),
            'Publisher resolution should be cached across multiple books in the same handler lifecycle'
        );
    }

    public function test_publisher_edge_matrix_trims_name_and_preserves_accented_text(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'publisher' => '  Québec Éditeur  ',
        ], $user, $library->id);

        $this->assertSame('Québec Éditeur', $this->publisherNameForBook($book, $user, $library));
    }

    public function test_publisher_edge_matrix_explicit_empty_value_clears_link(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'publisher' => 'Macmillan',
        ], $user, $library->id);

        $handler->applyBookMetadata($book, [
            'publisher' => null,
        ], $user, $library->id);

        $this->assertNull($this->publisherNameForBook($book, $user, $library));
    }

    public function test_publisher_change_to_existing_value_updates_link_without_delete(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $this->createPublisher($user, $library, 3301, 'Old House');
        $this->createPublisher($user, $library, 3302, 'New House');

        DB::table('books_publishers_link')->insert([
            'uuid' => 'publisher-pivot-2',
            'book' => $book->uuid,
            'publisher' => 3301,
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'publisher' => 'New House',
        ], $user, $library->id);

        $deleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete') && str_contains($sql, 'books_publishers_link');
        }));

        $this->assertSame([], $deleteQueries, 'Changing publisher to another existing entity must update the link without delete+reinsert');
        $this->assertSame('New House', $this->publisherNameForBook($book, $user, $library));
    }

    public function test_publisher_noop_update_does_not_issue_link_update(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $this->createPublisher($user, $library, 3401, 'Noop House');

        DB::table('books_publishers_link')->insert([
            'uuid' => 'publisher-pivot-3',
            'book' => $book->uuid,
            'publisher' => 3401,
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'publisher' => 'Noop House',
        ], $user, $library->id);

        $linkUpdates = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'update')
                && str_contains($sql, 'books_publishers_link');
        }));

        $this->assertSame([], $linkUpdates, 'No-op publisher update must not issue pivot update');
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Publisher Edge Matrix',
        ]);

        $book = UserBook::create([
            'id' => 9401,
            'uuid' => 'dd000000-0000-4000-8000-000000009401',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Publisher Test Book',
            'path' => 'publisher-test-book',
            'author_sort' => 'Tester, Publisher',
            'last_modified' => now(),
        ]);

        return [$user, $library, $book->fresh()];
    }

    private function createPublisher(User $user, Library $library, int $id, string $name): void
    {
        DB::table('books_publishers')->insert([
            'id' => $id,
            'idx' => $id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => $name,
            'sort' => $name,
            'uuid' => sprintf('00000000-0000-4000-8000-%012d', $id),
            'created_at' => now(),
            'updated_at' => now(),
        ]);
    }

    private function publisherNameForBook(UserBook $book, User $user, Library $library): ?string
    {
        $row = DB::table('books_publishers_link')
            ->join('books_publishers', 'books_publishers_link.publisher', '=', 'books_publishers.id')
            ->where('books_publishers_link.book', $book->uuid)
            ->where('books_publishers_link.user_id', $user->id)
            ->where('books_publishers_link.library_id', $library->id)
            ->value('books_publishers.name');

        return $row !== null ? (string) $row : null;
    }
}
