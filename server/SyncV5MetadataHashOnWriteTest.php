<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use App\Services\Sync\MetadataHasher;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

/**
 * Edge case matrix for metadata_hash computed on-write.
 *
 * After applyBookMetadata(), the metadata_hash column must be populated
 * with the same value as the VIEW books_hash_v2 would compute.
 */
class SyncV5MetadataHashOnWriteTest extends TestCase
{
    use RefreshDatabase;

    private function makeUserLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        return [$user, $library];
    }

    private function applyMetadata(UserBook $book, array $item, User $user, int $libraryId): void
    {
        app(BookMetadataHandler::class)->applyBookMetadata($book, $item, $user, $libraryId);
        $book->refresh();
    }

    private function viewHash(UserBook $book): ?string
    {
        if (!Schema::hasTable('books_hash_v2')) {
            return null;
        }
        return strtolower((string) DB::table('books_hash_v2')
            ->where('user_id', $book->user_id)
            ->where('library_id', $book->library_id)
            ->where('uuid', $book->uuid)
            ->value('metadata_hash'));
    }

    private function createBook(Library $library, array $overrides = []): UserBook
    {
        return UserBook::create(array_merge([
            'id' => rand(50000, 99999),
            'uuid' => (string) Str::uuid(),
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'title' => 'Test Book',
            'path' => 'Test Book',
            'pubdate' => '2020-01-01 00:00:00',
            'last_modified' => now(),
        ], $overrides));
    }

    // ── #1: New book via sync — hash populated ──────────────────────────

    public function test_01_new_book_gets_hash_after_apply(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        $book = $this->createBook($library);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid,
            'title' => 'New Book',
            'authors' => [['name' => 'Author One']],
            'tags' => [],
            'series' => null,
            'identifiers' => [],
            'publisher' => null,
            'languages' => [],
            'comments' => null,
            'rating' => null,
            'pubdate' => '2020-01-01',
        ], $user, $library->id);

        $this->assertNotNull($book->metadata_hash, 'Hash must be populated after apply');
        $this->assertSame(64, strlen($book->metadata_hash), 'Hash must be 64 hex chars');
    }

    // ── #2: Title update → different hash ───────────────────────────────

    public function test_02_title_change_produces_different_hash(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        $book = $this->createBook($library);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Original Title',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hash1 = $book->metadata_hash;

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Changed Title',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hash2 = $book->metadata_hash;

        $this->assertNotSame($hash1, $hash2, 'Title change must produce different hash');
    }

    // ── #3: Tag-only change → different hash ────────────────────────────

    public function test_03_tag_change_produces_different_hash(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        $book = $this->createBook($library);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Same Title',
            'authors' => [], 'tags' => [['name' => 'Fiction']],
            'series' => null, 'identifiers' => [], 'publisher' => null,
            'languages' => [], 'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hash1 = $book->metadata_hash;

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Same Title',
            'authors' => [], 'tags' => [['name' => 'Fiction'], ['name' => 'Drama']],
            'series' => null, 'identifiers' => [], 'publisher' => null,
            'languages' => [], 'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hash2 = $book->metadata_hash;

        $this->assertNotSame($hash1, $hash2, 'Tag change must produce different hash');
    }

    // ── #4: Rating change → different hash ──────────────────────────────

    public function test_04_rating_change_produces_different_hash(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        $book = $this->createBook($library);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Rated Book',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => 4, 'pubdate' => null,
        ], $user, $library->id);
        $hash1 = $book->metadata_hash;

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Rated Book',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => 8, 'pubdate' => null,
        ], $user, $library->id);
        $hash2 = $book->metadata_hash;

        $this->assertNotSame($hash1, $hash2, 'Rating change must produce different hash');
    }

    // ── #5: No real change → same hash (idempotent) ─────────────────────

    public function test_05_no_change_produces_same_hash(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        $book = $this->createBook($library);

        $item = [
            'uuid' => $book->uuid, 'title' => 'Stable Book',
            'authors' => [['name' => 'Author A']], 'tags' => [['name' => 'Tag1']],
            'series' => null, 'identifiers' => [], 'publisher' => 'Pub',
            'languages' => ['eng'], 'comments' => 'A description',
            'rating' => 6, 'pubdate' => '2021-05-15',
        ];

        $this->applyMetadata($book, $item, $user, $library->id);
        $hash1 = $book->metadata_hash;

        $this->applyMetadata($book, $item, $user, $library->id);
        $hash2 = $book->metadata_hash;

        $this->assertSame($hash1, $hash2, 'Same data must produce same hash');
    }

    // ── #6: All relations empty → valid hash ────────────────────────────

    public function test_06_empty_relations_valid_hash(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        $book = $this->createBook($library);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Bare Book',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);

        $this->assertNotNull($book->metadata_hash);
        $this->assertSame(64, strlen($book->metadata_hash));
    }

    // ── #8: Pubdate null → valid hash ───────────────────────────────────

    public function test_08_pubdate_null_valid_hash(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        $book = $this->createBook($library, ['pubdate' => null]);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'No Date',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);

        $this->assertNotNull($book->metadata_hash);
    }

    // ── #10: Rating 0 treated as null ───────────────────────────────────

    public function test_10_rating_zero_same_as_null(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        $book = $this->createBook($library);

        $base = [
            'uuid' => $book->uuid,
            'title' => 'Rating Test', 'authors' => [], 'tags' => [],
            'series' => null, 'identifiers' => [], 'publisher' => null,
            'languages' => [], 'comments' => null, 'pubdate' => null,
        ];

        $this->applyMetadata($book, array_merge($base, ['rating' => 0]), $user, $library->id);
        $hash0 = $book->metadata_hash;

        $this->applyMetadata($book, array_merge($base, ['rating' => null]), $user, $library->id);
        $hashNull = $book->metadata_hash;

        $this->assertSame($hash0, $hashNull, 'Rating 0 must equal null');
    }

    // ── #12: Description cleared → hash changes ─────────────────────────

    public function test_12_description_cleared_changes_hash(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        $book = $this->createBook($library);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Has Desc',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => '<p>Some text</p>', 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hash1 = $book->metadata_hash;

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Has Desc',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hash2 = $book->metadata_hash;

        $this->assertNotSame($hash1, $hash2, 'Clearing description must change hash');
    }

    // ── #13: Column NULL → sync falls back to VIEW ──────────────────────

    public function test_13_null_column_falls_back_to_view(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        Sanctum::actingAs($user);

        $book = $this->createBook($library);
        // Ensure column is NULL (pre-migration state)
        DB::table('books')->where('id', $book->id)->update(['metadata_hash_cache' => null]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [$book->uuid => ['m' => str_repeat('0', 64), 'c' => null, 'f' => null]],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => [$book->uuid],
            ],
        ]);

        $response->assertOk();
        // Book must appear in updates (hash mismatch, whether from column or VIEW)
        $updates = $response->json('updates_for_client') ?? [];
        $this->assertCount(1, $updates, 'Book with NULL hash column must still work via VIEW fallback');
    }

    // ── #14: Hash column matches VIEW ───────────────────────────────────

    public function test_14_stored_hash_matches_view_hash(): void
    {
        if (!Schema::hasTable('books_hash_v2')) {
            $this->markTestSkipped('books_hash_v2 VIEW not available on this DB driver');
        }

        [$user, $library] = $this->makeUserLibrary();
        $book = $this->createBook($library);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Parity Check',
            'authors' => [['name' => 'Parity Author']],
            'tags' => [['name' => 'Parity Tag']],
            'series' => ['name' => 'Parity Series', 'index' => 2.0],
            'identifiers' => ['isbn' => '1234567890'],
            'publisher' => 'Parity Pub',
            'languages' => ['eng', 'spa'],
            'comments' => '<p>Parity description</p>',
            'rating' => 8,
            'pubdate' => '2022-06-15',
        ], $user, $library->id);

        $storedHash = $book->metadata_hash;
        $viewHash = $this->viewHash($book);

        $this->assertNotNull($storedHash, 'Stored hash must not be null');
        $this->assertNotNull($viewHash, 'VIEW hash must not be null');
        $this->assertSame($viewHash, $storedHash, 'Stored hash must match VIEW hash');
    }

    // ── #16: Soft-deleted book — hash not needed ────────────────────────

    public function test_16_soft_deleted_book_excluded(): void
    {
        [$user, $library] = $this->makeUserLibrary();
        Sanctum::actingAs($user);

        $book = $this->createBook($library);
        $book->delete(); // soft delete

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [$book->uuid => ['m' => str_repeat('0', 64), 'c' => null, 'f' => null]],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => [$book->uuid],
            ],
        ]);

        $response->assertOk();
        $deleted = $response->json('deleted_on_server') ?? [];
        $this->assertContains($book->uuid, $deleted);
    }
}
