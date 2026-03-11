<?php

namespace Tests\Server;

use App\Models\Author;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class BookMetadataHandlerAuthorEdgeMatrixTest extends TestCase
{
    use RefreshDatabase;

    public function test_authors_noop_update_does_not_delete_existing_links(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $first = $this->createAuthor($user, $library, 1301, 'Marcus Sakey');
        $second = $this->createAuthor($user, $library, 1302, 'H. G. Wells');

        DB::table('books_authors_link')->insert([
            [
                'uuid' => 'author-pivot-1',
                'book' => $book->uuid,
                'author' => $first->id,
                'position' => 0,
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
            [
                'uuid' => 'author-pivot-2',
                'book' => $book->uuid,
                'author' => $second->id,
                'position' => 1,
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'authors' => [
                ['name' => 'Marcus Sakey', 'position' => 0],
                ['name' => 'H. G. Wells', 'position' => 1],
            ],
        ], $user, $library->id);

        $deleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete') && str_contains($sql, 'books_authors_link');
        }));

        $this->assertSame([], $deleteQueries, 'No-op author update must not delete and recreate pivot rows');
        $this->assertSame(['H. G. Wells', 'Marcus Sakey'], $this->authorNamesForBook($book, $user, $library));
    }

    public function test_authors_existing_resolution_is_prefetched_not_one_query_per_author(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        foreach ([
            'Marcus Sakey',
            'Québec Author',
            'AC/DC Writer',
            'H. G. Wells',
            'Robert A. Heinlein',
        ] as $index => $name) {
            $this->createAuthor($user, $library, 1401 + $index, $name);
        }

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'authors' => [
                ['name' => 'Marcus Sakey'],
                ['name' => 'Québec Author'],
                ['name' => 'AC/DC Writer'],
                ['name' => 'H. G. Wells'],
                ['name' => 'Robert A. Heinlein'],
            ],
        ], $user, $library->id);

        $authorSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'from `books_authors`') && str_contains($sql, 'select');
        }));

        $this->assertLessThanOrEqual(
            2,
            count($authorSelects),
            'Author resolution should be prefetched in bulk, not one SELECT per author name'
        );
    }

    public function test_authors_edge_matrix_deduplicates_payload_and_uses_bulk_link_write(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'authors' => [
                ['name' => 'Québec Author', 'position' => 0],
                ['name' => 'Marcus Sakey', 'position' => 1],
                ['name' => 'Québec Author', 'position' => 2],
                ['name' => '  AC/DC Writer  ', 'position' => 3],
                ['name' => 'AC/DC Writer', 'position' => 4],
                ['name' => ' ', 'position' => 5],
            ],
        ], $user, $library->id);

        $linkWrites = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'books_authors_link')
                && (str_contains($sql, 'insert') || str_contains($sql, 'update'));
        }));

        $this->assertLessThanOrEqual(
            2,
            count($linkWrites),
            'Author pivot persistence must use bulk write, not one insert/update per author row'
        );
        $this->assertSame(['AC/DC Writer', 'Marcus Sakey', 'Québec Author'], $this->authorNamesForBook($book, $user, $library));
    }

    public function test_authors_edge_matrix_explicit_empty_array_clears_links(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'authors' => [
                ['name' => 'Marcus Sakey'],
                ['name' => 'H. G. Wells'],
            ],
        ], $user, $library->id);

        $handler->applyBookMetadata($book, [
            'authors' => [],
        ], $user, $library->id);

        $this->assertSame([], $this->authorNamesForBook($book, $user, $library));
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Author Edge Matrix',
        ]);

        $book = UserBook::create([
            'id' => 9201,
            'uuid' => 'dd000000-0000-4000-8000-000000009201',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Author Test Book',
            'path' => 'author-test-book',
            'author_sort' => 'Tester, Author',
            'last_modified' => now(),
        ]);

        return [$user, $library, $book->fresh()];
    }

    private function createAuthor(User $user, Library $library, int $id, string $name): Author
    {
        return Author::create([
            'id' => $id,
            'idx' => $id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => $name,
            'sort' => $name,
            'uuid' => sprintf('00000000-0000-4000-8000-%012d', $id),
        ]);
    }

    private function authorNamesForBook(UserBook $book, User $user, Library $library): array
    {
        return DB::table('books_authors_link')
            ->join('books_authors', 'books_authors_link.author', '=', 'books_authors.id')
            ->where('books_authors_link.book', $book->uuid)
            ->where('books_authors_link.user_id', $user->id)
            ->where('books_authors_link.library_id', $library->id)
            ->orderBy('books_authors.name')
            ->pluck('books_authors.name')
            ->values()
            ->all();
    }
}
