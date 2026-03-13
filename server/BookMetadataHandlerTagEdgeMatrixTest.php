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

    public function test_tags_resolution_reuses_handler_cache_across_books(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $otherBook = UserBook::create([
            'id' => 9002,
            'uuid' => 'dd000000-0000-4000-8000-000000009002',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Tag Test Book 2',
            'path' => 'tag-test-book-2',
            'author_sort' => 'Tester, Tag',
            'last_modified' => now(),
        ]);
        $handler = app(BookMetadataHandler::class);

        foreach ([
            'Marcus Sakey',
            'Québec',
            'AC/DC',
            'H. G. Wells',
            'Robert A. Heinlein',
        ] as $index => $name) {
            $this->createTag($user, $library, 4001 + $index, $name);
        }

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $payload = [
            'tags' => [
                ['name' => 'Marcus Sakey'],
                ['name' => 'Québec'],
                ['name' => 'AC/DC'],
                ['name' => 'H. G. Wells'],
                ['name' => 'Robert A. Heinlein'],
            ],
        ];

        $handler->applyBookMetadata($book, $payload, $user, $library->id);
        $handler->applyBookMetadata($otherBook, $payload, $user, $library->id);

        $booksTagsSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'from `books_tags`') && str_contains($sql, 'select');
        }));

        $this->assertLessThanOrEqual(
            1,
            count($booksTagsSelects),
            'Tag resolution should hit books_tags at most once across multiple books in the same handler lifecycle'
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

    public function test_tags_existing_entity_with_unchanged_link_does_not_issue_update(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $this->createTag($user, $library, 3201, 'Marcus Sakey', 'https://example.test/marcus');

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'tags' => [
                ['name' => 'Marcus Sakey', 'link' => 'https://example.test/marcus'],
            ],
        ], $user, $library->id);

        $tagUpdates = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'update')
                && str_contains($sql, 'books_tags')
                && !str_contains($sql, 'books_tags_link');
        }));

        $this->assertSame([], $tagUpdates, 'Existing tag with unchanged link must not issue row update');
    }

    public function test_tags_delta_update_reuses_existing_links_snapshot_without_second_pivot_select(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $firstTag = $this->createTag($user, $library, 3301, 'Marcus Sakey');
        $secondTag = $this->createTag($user, $library, 3302, 'Quebec');
        $thirdTag = $this->createTag($user, $library, 3303, 'AC/DC');

        DB::table('books_tags_link')->insert([
            [
                'uuid' => 'pivot-tag-snapshot-1',
                'book' => $book->uuid,
                'tag' => $firstTag->id,
                'position' => 0,
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
            [
                'uuid' => 'pivot-tag-snapshot-2',
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
                ['name' => 'AC/DC', 'position' => 1],
            ],
        ], $user, $library->id);

        $pivotSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'select')
                && str_contains($sql, 'books_tags_link')
                && str_contains($sql, 'join')
                && str_contains($sql, 'books_tags');
        }));

        $this->assertLessThanOrEqual(
            1,
            count($pivotSelects),
            'Tag delta update should reuse existing links snapshot instead of issuing a second pivot select'
        );
    }

    public function test_tags_mapping_only_update_with_same_final_links_does_not_write_pivots(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $firstTag = $this->createTag($user, $library, 6101, 'Marcus Sakey');
        $secondTag = $this->createTag($user, $library, 6102, 'Quebec');

        DB::table('books_tags_link')->insert([
            [
                'uuid' => 'pivot-tag-map-noop-1',
                'book' => $book->uuid,
                'tag' => $firstTag->id,
                'position' => 0,
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
            [
                'uuid' => 'pivot-tag-map-noop-2',
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
                ['name' => 'Marcus Sakey', 'position' => 0, 'client_ids' => ['calibre:tag:6101' => 6101]],
                ['name' => 'Quebec', 'position' => 1, 'client_ids' => ['calibre:tag:6102' => 6102]],
            ],
        ], $user, $library->id);

        $linkWrites = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'books_tags_link')
                && (str_contains($sql, 'insert') || str_contains($sql, 'update') || str_contains($sql, 'delete'));
        }));

        $this->assertSame([], $linkWrites, 'Mapping-only tag update with identical final links must not write pivot rows');
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

    public function test_tags_partial_delta_update_does_not_delete_all_existing_links(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $firstTag = $this->createTag($user, $library, 3001, 'Marcus Sakey');
        $secondTag = $this->createTag($user, $library, 3002, 'Quebec');
        $thirdTag = $this->createTag($user, $library, 3003, 'AC/DC');

        DB::table('books_tags_link')->insert([
            [
                'uuid' => 'pivot-tag-delta-1',
                'book' => $book->uuid,
                'tag' => $firstTag->id,
                'position' => 0,
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
            [
                'uuid' => 'pivot-tag-delta-2',
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
                ['name' => 'AC/DC', 'position' => 1],
            ],
        ], $user, $library->id);

        $fullDeleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete')
                && str_contains($sql, 'books_tags_link')
                && !str_contains($sql, ' and "tag" in ')
                && !str_contains($sql, ' and `tag` in ');
        }));

        $this->assertSame([], $fullDeleteQueries, 'Partial tag delta must not issue a full delete of all tag pivots');
        $this->assertSame(
            ['AC/DC', 'Marcus Sakey'],
            $this->tagNamesForBook($book, $user, $library)
        );

        $pivotNames = DB::table('books_tags_link')
            ->join('books_tags', 'books_tags_link.tag', '=', 'books_tags.id')
            ->where('books_tags_link.book', $book->uuid)
            ->where('books_tags_link.user_id', $user->id)
            ->where('books_tags_link.library_id', $library->id)
            ->orderBy('books_tags_link.position')
            ->get(['books_tags.name', 'books_tags_link.uuid'])
            ->all();

        $this->assertSame('pivot-tag-delta-1', trim((string) $pivotNames[0]->uuid), 'Unchanged tag pivot should be preserved');
        $this->assertNotSame('pivot-tag-delta-2', trim((string) $pivotNames[1]->uuid), 'Changed tag pivot may be replaced');
    }

    public function test_tags_position_reorder_uses_bulk_upsert_not_row_by_row_updates(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $firstTag = $this->createTag($user, $library, 3101, 'Marcus Sakey');
        $secondTag = $this->createTag($user, $library, 3102, 'Quebec');
        $thirdTag = $this->createTag($user, $library, 3103, 'AC/DC');

        DB::table('books_tags_link')->insert([
            [
                'uuid' => 'pivot-tag-reorder-1',
                'book' => $book->uuid,
                'tag' => $firstTag->id,
                'position' => 0,
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
            [
                'uuid' => 'pivot-tag-reorder-2',
                'book' => $book->uuid,
                'tag' => $secondTag->id,
                'position' => 1,
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
            [
                'uuid' => 'pivot-tag-reorder-3',
                'book' => $book->uuid,
                'tag' => $thirdTag->id,
                'position' => 2,
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
                ['name' => 'AC/DC', 'position' => 0],
                ['name' => 'Marcus Sakey', 'position' => 1],
                ['name' => 'Quebec', 'position' => 2],
            ],
        ], $user, $library->id);

        $linkWrites = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'books_tags_link')
                && (str_contains($sql, 'insert') || str_contains($sql, 'update'));
        }));

        $this->assertLessThanOrEqual(
            2,
            count($linkWrites),
            'Tag reorder should use bulk pivot persistence, not one write per reordered row'
        );
        $this->assertSame(
            ['AC/DC', 'Marcus Sakey', 'Quebec'],
            $this->tagNamesForBook($book, $user, $library)
        );
    }

    public function test_tags_sync_mappings_persist_uses_bulk_upsert_not_row_by_row_updates(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'tags' => [
                ['name' => 'Marcus Sakey', 'client_ids' => ['calibre:tag:1' => 1]],
                ['name' => 'Québec', 'client_ids' => ['calibre:tag:2' => 2]],
                ['name' => 'AC/DC', 'client_ids' => ['calibre:tag:3' => 3]],
                ['name' => 'H. G. Wells', 'client_ids' => ['calibre:tag:4' => 4]],
                ['name' => 'Robert A. Heinlein', 'client_ids' => ['calibre:tag:5' => 5]],
            ],
        ], $user, $library->id);

        $mappingWrites = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'sync_mappings')
                && (str_contains($sql, 'insert') || str_contains($sql, 'update'));
        }));

        $this->assertLessThanOrEqual(
            2,
            count($mappingWrites),
            'Tag mapping persistence must use bulk write, not one updateOrCreate per tag mapping'
        );
    }

    public function test_tags_sync_mappings_resolution_is_prefetched_not_one_query_per_tag(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        foreach ([
            [5001, 'Marcus Sakey', 'calibre:tag:1', 1],
            [5002, 'Québec', 'calibre:tag:2', 2],
            [5003, 'AC/DC', 'calibre:tag:3', 3],
            [5004, 'H. G. Wells', 'calibre:tag:4', 4],
            [5005, 'Robert A. Heinlein', 'calibre:tag:5', 5],
        ] as [$id, $name, $clientKey, $clientVal]) {
            $tag = $this->createTag($user, $library, $id, $name);
            DB::table('sync_mappings')->insert([
                'user_id' => $user->id,
                'library_id' => $library->id,
                'entity_type' => 'tags',
                'client_key' => $clientKey,
                'server_id' => $tag->id,
                'uuid' => sprintf('00000000-0000-4000-8000-%012d', $id),
                'meta' => json_encode(['client_val' => $clientVal]),
                'created_at' => now(),
                'updated_at' => now(),
            ]);
        }

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'tags' => [
                ['name' => 'Marcus Sakey', 'client_ids' => ['calibre:tag:1' => 1]],
                ['name' => 'Québec', 'client_ids' => ['calibre:tag:2' => 2]],
                ['name' => 'AC/DC', 'client_ids' => ['calibre:tag:3' => 3]],
                ['name' => 'H. G. Wells', 'client_ids' => ['calibre:tag:4' => 4]],
                ['name' => 'Robert A. Heinlein', 'client_ids' => ['calibre:tag:5' => 5]],
            ],
        ], $user, $library->id);

        $mappingSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'from "sync_mappings"') || str_contains($sql, 'from `sync_mappings`');
        }));

        $this->assertLessThanOrEqual(
            2,
            count($mappingSelects),
            'Tag mapping resolution should be prefetched in bulk, not one SELECT per tag mapping'
        );
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

    private function createTag(User $user, Library $library, int $id, string $name, string $link = ''): Tag
    {
        return Tag::create([
            'id' => $id,
            'idx' => $id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => $name,
            'link' => $link,
            'uuid' => sprintf('00000000-0000-4000-8000-%012d', $id),
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
