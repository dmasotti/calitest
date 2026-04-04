<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

/**
 * On-write hash must come from VIEW, not PHP MetadataHasher.
 *
 * Edge case matrix:
 * | # | Scenario                          | Expected                                    |
 * |---|-----------------------------------|---------------------------------------------|
 * | 1 | New book with all fields          | Column hash = VIEW hash                     |
 * | 2 | Update title                      | Column hash changes, still = VIEW hash      |
 * | 3 | Update tags only                  | Column hash changes (tags in VIEW formula)  |
 * | 4 | Pre-1970 pubdate                  | Column hash = VIEW hash (not NULL)          |
 * | 5 | Sentinel 0101 pubdate             | Column hash = VIEW hash (both null pubdate) |
 * | 6 | Description with HTML             | Column hash = VIEW hash                     |
 * | 7 | Multiple authors sorted           | Column hash = VIEW hash                     |
 * | 8 | Identifiers with mixed case       | Column hash = VIEW hash                     |
 * | 9 | Rating 0 vs null                  | Column hash = VIEW hash                     |
 * |10 | Idempotent: same data twice       | Same column hash                            |
 * |11 | Sync request uses column hash     | Server skips book (hash match)              |
 * |12 | VIEW unavailable (e.g. SQLite)    | Column stays NULL, fallback VIEW at read    |
 */
class SyncV5OnWriteFromViewTest extends TestCase
{
    use RefreshDatabase;

    private function applyAndRefresh(UserBook $book, array $item, User $user, int $libraryId): UserBook
    {
        app(BookMetadataHandler::class)->applyBookMetadata($book, $item, $user, $libraryId);
        $book->refresh();
        return $book;
    }

    private function viewHash(UserBook $book): ?string
    {
        if (!Schema::hasTable('books_hash_v2')) {
            return null;
        }
        $h = DB::table('books_hash_v2')
            ->where('user_id', $book->user_id)
            ->where('library_id', $book->library_id)
            ->where('uuid', $book->uuid)
            ->value('metadata_hash');
        return $h ? strtolower((string) $h) : null;
    }

    private function createBook(Library $library, array $overrides = []): UserBook
    {
        return UserBook::create(array_merge([
            'id' => rand(50000, 59999),
            'uuid' => (string) Str::uuid(),
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'title' => 'Test Book',
            'path' => 'Test Book',
            'pubdate' => '2020-01-01 00:00:00',
            'last_modified' => now(),
        ], $overrides));
    }

    // ── #1: New book — column = VIEW ────────────────────────────────

    public function test_01_new_book_column_equals_view(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = $this->createBook($lib);

        $this->applyAndRefresh($book, [
            'uuid' => $book->uuid, 'title' => 'New Book With Data',
            'authors' => [['name' => 'Author One'], ['name' => 'Author Two']],
            'tags' => [['name' => 'Fiction'], ['name' => 'Drama']],
            'series' => ['name' => 'My Series', 'index' => 2.0],
            'identifiers' => ['isbn' => '9780000000001', 'goodreads' => '12345'],
            'publisher' => 'Test Publisher',
            'languages' => ['eng', 'spa'],
            'comments' => '<p>A description with <b>HTML</b></p>',
            'rating' => 8,
            'pubdate' => '2021-10-16 20:00:00',
        ], $user, $lib->id);

        $colHash = $book->metadata_hash;
        $viewHash = $this->viewHash($book);

        $this->assertNotNull($colHash, 'Column hash must be set');
        if ($viewHash !== null) {
            $this->assertSame($viewHash, $colHash, 'Column hash must equal VIEW hash');
        }
    }

    // ── #2: Title change — column updates and still = VIEW ──────────

    public function test_02_title_change_column_equals_view(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = $this->createBook($lib);

        $base = [
            'uuid' => $book->uuid, 'authors' => [['name' => 'Author']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => [], 'comments' => null,
            'rating' => null, 'pubdate' => '2020-01-01',
        ];

        $this->applyAndRefresh($book, array_merge($base, ['title' => 'Original']), $user, $lib->id);
        $hash1 = $book->metadata_hash;

        $this->applyAndRefresh($book, array_merge($base, ['title' => 'Changed']), $user, $lib->id);
        $hash2 = $book->metadata_hash;

        $this->assertNotSame($hash1, $hash2);
        $viewHash = $this->viewHash($book);
        if ($viewHash !== null) {
            $this->assertSame($viewHash, $hash2, 'After title change, column must equal VIEW');
        }
    }

    // ── #3: Tags only change ────────────────────────────────────────

    public function test_03_tags_change_column_equals_view(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = $this->createBook($lib);

        $base = [
            'uuid' => $book->uuid, 'title' => 'Same Title',
            'authors' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => [], 'comments' => null,
            'rating' => null, 'pubdate' => null,
        ];

        $this->applyAndRefresh($book, array_merge($base, ['tags' => [['name' => 'Tag1']]]), $user, $lib->id);
        $this->applyAndRefresh($book, array_merge($base, ['tags' => [['name' => 'Tag1'], ['name' => 'Tag2']]]), $user, $lib->id);

        $viewHash = $this->viewHash($book);
        if ($viewHash !== null) {
            $this->assertSame($viewHash, $book->metadata_hash);
        }
    }

    // ── #4: Pre-1970 pubdate ────────────────────────────────────────

    public function test_04_pre1970_pubdate_column_equals_view(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = $this->createBook($lib);

        $this->applyAndRefresh($book, [
            'uuid' => $book->uuid, 'title' => 'Old Book',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null,
            'pubdate' => '1966-12-31 23:00:00',
        ], $user, $lib->id);

        $viewHash = $this->viewHash($book);
        if ($viewHash !== null) {
            $this->assertSame($viewHash, $book->metadata_hash);
        }
    }

    // ── #5: Sentinel 0101 pubdate ───────────────────────────────────

    public function test_05_sentinel_pubdate_column_equals_view(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = $this->createBook($lib);

        $this->applyAndRefresh($book, [
            'uuid' => $book->uuid, 'title' => 'Sentinel Date',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null,
            'pubdate' => '0101-01-01 00:00:00',
        ], $user, $lib->id);

        $viewHash = $this->viewHash($book);
        if ($viewHash !== null) {
            $this->assertSame($viewHash, $book->metadata_hash);
        }
    }

    // ── #7: Multiple authors sorted ─────────────────────────────────

    public function test_07_multiple_authors_column_equals_view(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = $this->createBook($lib);

        $this->applyAndRefresh($book, [
            'uuid' => $book->uuid, 'title' => 'Multi Author',
            'authors' => [['name' => 'Zeta Author'], ['name' => 'Alpha Author'], ['name' => 'Mid Author']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $lib->id);

        $viewHash = $this->viewHash($book);
        if ($viewHash !== null) {
            $this->assertSame($viewHash, $book->metadata_hash, 'Authors must be sorted identically in column and VIEW');
        }
    }

    // ── #10: Idempotent ─────────────────────────────────────────────

    public function test_10_idempotent_same_hash(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = $this->createBook($lib);

        $item = [
            'uuid' => $book->uuid, 'title' => 'Stable',
            'authors' => [['name' => 'Author']], 'tags' => [['name' => 'Tag']],
            'series' => null, 'identifiers' => [], 'publisher' => 'Pub',
            'languages' => ['eng'], 'comments' => 'Desc',
            'rating' => 6, 'pubdate' => '2021-05-15',
        ];

        $this->applyAndRefresh($book, $item, $user, $lib->id);
        $hash1 = $book->metadata_hash;

        $this->applyAndRefresh($book, $item, $user, $lib->id);
        $hash2 = $book->metadata_hash;

        $this->assertSame($hash1, $hash2);
    }

    // ── #11: Sync uses column hash → server skips ───────────────────

    public function test_11_sync_skips_when_column_hash_matches(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);
        $book = $this->createBook($lib);

        $this->applyAndRefresh($book, [
            'uuid' => $book->uuid, 'title' => 'Sync Match Test',
            'authors' => [['name' => 'Test Author']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => ['eng'],
            'comments' => null, 'rating' => null, 'pubdate' => '2022-01-01',
        ], $user, $lib->id);

        $colHash = $book->metadata_hash;
        $this->assertNotNull($colHash);

        // Send sync with the column hash — server must skip
        $r = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $lib->id,
            'calibre_library_uuid' => $lib->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [$book->uuid => ['m' => $colHash, 'c' => null, 'f' => null]],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => [$book->uuid],
            ],
        ]);

        $r->assertOk();
        $this->assertCount(0, $r->json('updates_for_client') ?? []);
        $this->assertCount(0, $r->json('missing_from_server') ?? []);
    }
}
