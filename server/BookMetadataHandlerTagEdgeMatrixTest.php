<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\Tag;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class BookMetadataHandlerTagEdgeMatrixTest extends TestCase
{
    use RefreshDatabase;

    public function test_tags_noop_update_does_not_delete_existing_links(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $firstTag = $this->createTag($user, $library, 1001, 'Marcus Sakey');
        $secondTag = $this->createTag($user, $library, 1002, 'Quebec');

        DB::table('books_tags_link')->insert([
            [
                'uuid' => 'pivot-tag-1',
                'book' => $book->uuid,
                'tag' => $firstTag->id,
                'position' => 0,
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
            [
                'uuid' => 'pivot-tag-2',
                'book' => $book->uuid,
                'tag' => $secondTag->id,
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
            'tags' => [
                ['name' => 'Marcus Sakey', 'position' => 0],
                ['name' => 'Quebec', 'position' => 1],
            ],
        ], $user, $library->id);

        $deleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete') && str_contains($sql, 'books_tags_link');
        }));

        $this->assertSame([], $deleteQueries, 'No-op tag update must not delete and recreate pivot rows');
        $this->assertSame(
            ['Marcus Sakey', 'Quebec'],
            $this->tagNamesForBook($book, $user, $library)
        );
    }

    public function test_tags_existing_name_resolution_is_prefetched_not_one_query_per_tag(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        foreach ([
            'Marcus Sakey',
            'Québec',
            'AC/DC',
            'H. G. Wells',
            'Robert A. Heinlein',
        ] as $index => $name) {
            $this->createTag($user, $library, 2001 + $index, $name);
        }

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'tags' => [
                ['name' => 'Marcus Sakey'],
                ['name' => 'Québec'],
                ['name' => 'AC/DC'],
                ['name' => 'H. G. Wells'],
                ['name' => 'Robert A. Heinlein'],
            ],
        ], $user, $library->id);

        $booksTagsSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'from `books_tags`') && str_contains($sql, 'select');
        }));

        $this->assertLessThanOrEqual(
            2,
            count($booksTagsSelects),
            'Tag resolution should be prefetched in bulk, not one SELECT per tag name'
        );
        $this->assertSame(
            ['AC/DC', 'H. G. Wells', 'Marcus Sakey', 'Québec', 'Robert A. Heinlein'],
            $this->tagNamesForBook($book, $user, $library)
        );
    }

    public function test_tags_link_persistence_uses_bulk_write_not_row_by_row_upserts(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'tags' => [
                ['name' => 'Marcus Sakey'],
                ['name' => 'Québec'],
                ['name' => 'AC/DC'],
                ['name' => 'H. G. Wells'],
                ['name' => 'Robert A. Heinlein'],
            ],
        ], $user, $library->id);

        $linkWrites = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'books_tags_link')
                && (str_contains($sql, 'insert') || str_contains($sql, 'update'));
        }));

        $this->assertLessThanOrEqual(
            2,
            count($linkWrites),
            'Tag pivot persistence must use bulk write, not one insert/update per tag row'
        );
    }

    public function test_tags_edge_matrix_deduplicates_payload_and_preserves_distinct_accented_values(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'tags' => [
                ['name' => 'Québec', 'position' => 0],
                ['name' => 'Quebec', 'position' => 1],
                ['name' => 'Québec', 'position' => 2],
                ['name' => '  AC/DC  ', 'position' => 3],
                ['name' => 'AC/DC', 'position' => 4],
                ['name' => ' ', 'position' => 5],
            ],
        ], $user, $library->id);

        $this->assertSame(
            ['AC/DC', 'Quebec', 'Québec'],
            $this->tagNamesForBook($book, $user, $library)
        );

        $pivotCount = DB::table('books_tags_link')
            ->where('book', $book->uuid)
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->count();

        $this->assertSame(3, $pivotCount);
    }

    public function test_tags_edge_matrix_explicit_empty_array_clears_links(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'tags' => [
                ['name' => 'Marcus Sakey'],
                ['name' => 'Québec'],
            ],
        ], $user, $library->id);

        $handler->applyBookMetadata($book, [
            'tags' => [],
        ], $user, $library->id);

        $this->assertSame([], $this->tagNamesForBook($book, $user, $library));
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Tag Edge Matrix',
        ]);

        $book = UserBook::create([
            'id' => 9001,
            'uuid' => 'ff000000-0000-4000-8000-000000009001',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Tag Test Book',
            'path' => 'tag-test-book',
            'author_sort' => 'Tester, Tag',
            'last_modified' => now(),
        ]);

        return [$user, $library, $book->fresh()];
    }

    private function createTag(User $user, Library $library, int $id, string $name): Tag
    {
        return Tag::create([
            'id' => $id,
            'idx' => $id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => $name,
            'uuid' => sprintf('tag-%04d-0000-4000-8000-000000000000', $id),
        ]);
    }

    private function tagNamesForBook(UserBook $book, User $user, Library $library): array
    {
        return DB::table('books_tags_link')
            ->join('books_tags', 'books_tags_link.tag', '=', 'books_tags.id')
            ->where('books_tags_link.book', $book->uuid)
            ->where('books_tags_link.user_id', $user->id)
            ->where('books_tags_link.library_id', $library->id)
            ->orderBy('books_tags.name')
            ->pluck('books_tags.name')
            ->values()
            ->all();
    }
}
