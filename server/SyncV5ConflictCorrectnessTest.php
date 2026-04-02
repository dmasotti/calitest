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
 * Conflict and correctness tests for Merkle-leaf sync protocol.
 *
 * Matrix:
 *   M. Server modifies metadata → client gets update on next sync
 *   N. Client sends new metadata → server applies, hash updated
 *   O. Two clients conflict on same book → second client sees server's version
 *   P. Hash on-write correctness under load (many books, many fields)
 *   Q. Incremental sync: first sync populates, second sync skips matched
 */
class SyncV5ConflictCorrectnessTest extends TestCase
{
    use RefreshDatabase;

    private function makeUser(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);
        return [$user, $library];
    }

    private function createBook(Library $library, array $overrides = []): UserBook
    {
        return UserBook::create(array_merge([
            'id' => rand(60000, 69999),
            'uuid' => (string) Str::uuid(),
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'title' => 'Test Book',
            'path' => 'Test Book',
            'pubdate' => '2020-01-01 00:00:00',
            'last_modified' => now(),
        ], $overrides));
    }

    private function applyMetadata(UserBook $book, array $item, User $user, int $libraryId): void
    {
        app(BookMetadataHandler::class)->applyBookMetadata($book, $item, $user, $libraryId);
        $book->refresh();
    }

    private function syncRequest(Library $library, array $clientBooks, array $candidates): \Illuminate\Testing\TestResponse
    {
        return $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => min(count($candidates) + 100, 1000),
            'client_books' => ['b' => $clientBooks, 'd' => []],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => $candidates,
            ],
        ]);
    }

    // ── M. Server modifies → client sees update ─────────────────────────

    public function test_m1_server_title_change_detected_by_client(): void
    {
        [$user, $library] = $this->makeUser();
        $book = $this->createBook($library);

        // Client syncs, gets initial metadata
        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Original',
            'authors' => [['name' => 'Author A']],
            'tags' => [['name' => 'Fiction']], 'series' => null,
            'identifiers' => [], 'publisher' => 'Pub1',
            'languages' => ['eng'], 'comments' => 'Desc', 'rating' => 6,
            'pubdate' => '2020-01-01',
        ], $user, $library->id);
        $hashAfterFirstSync = $book->metadata_hash;

        // Server-side modification (admin, web UI, another process)
        $book->title = 'Modified By Server';
        $book->save();
        // Re-apply to update hash (simulates server-side handler)
        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Modified By Server',
            'authors' => [['name' => 'Author A']],
            'tags' => [['name' => 'Fiction']], 'series' => null,
            'identifiers' => [], 'publisher' => 'Pub1',
            'languages' => ['eng'], 'comments' => 'Desc', 'rating' => 6,
            'pubdate' => '2020-01-01',
        ], $user, $library->id);
        $hashAfterServerChange = $book->metadata_hash;

        $this->assertNotSame($hashAfterFirstSync, $hashAfterServerChange);

        // Client syncs with old hash → gets update
        $r = $this->syncRequest($library,
            [$book->uuid => ['m' => $hashAfterFirstSync, 'c' => null, 'f' => null]],
            [$book->uuid]);
        $r->assertOk();
        $updates = $r->json('updates_for_client') ?? [];
        $this->assertCount(1, $updates);
        $this->assertSame('Modified By Server', $updates[0]['title']);
        $this->assertSame($hashAfterServerChange, $updates[0]['metadata_hash']);
    }

    public function test_m2_server_adds_author_detected_by_client(): void
    {
        [$user, $library] = $this->makeUser();
        $book = $this->createBook($library);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Multi Author',
            'authors' => [['name' => 'Author One']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hash1 = $book->metadata_hash;

        // Server adds a second author
        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Multi Author',
            'authors' => [['name' => 'Author One'], ['name' => 'Author Two']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hash2 = $book->metadata_hash;

        $this->assertNotSame($hash1, $hash2, 'Adding author must change hash');

        // Client with old hash gets update with both authors
        $r = $this->syncRequest($library,
            [$book->uuid => ['m' => $hash1, 'c' => null, 'f' => null]],
            [$book->uuid]);
        $r->assertOk();
        $updates = $r->json('updates_for_client') ?? [];
        $this->assertCount(1, $updates);
        $authors = $updates[0]['authors'] ?? [];
        $this->assertCount(2, $authors);
    }

    // ── N. Client sends metadata → server applies + hash updated ────────

    public function test_n1_client_uploads_book_server_stores_hash(): void
    {
        [$user, $library] = $this->makeUser();
        $uuid = (string) Str::uuid();

        // Client reports book that server doesn't have
        $r = $this->syncRequest($library,
            [$uuid => ['m' => str_repeat('a', 64), 'c' => null, 'f' => null]],
            [$uuid]);
        $r->assertOk();
        $missing = collect($r->json('missing_from_server') ?? []);
        $this->assertNotNull($missing->firstWhere('uuid', $uuid), 'Book must be in missing_from_server');

        // Client "uploads" by POSTing metadata via applyBookMetadata
        $book = UserBook::create([
            'id' => rand(60000, 69999),
            'uuid' => $uuid,
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'title' => 'Uploaded By Client',
            'path' => 'Uploaded By Client',
            'last_modified' => now(),
        ]);
        $this->applyMetadata($book, [
            'uuid' => $uuid, 'title' => 'Uploaded By Client',
            'authors' => [['name' => 'Client Author']],
            'tags' => [['name' => 'ClientTag']], 'series' => null,
            'identifiers' => ['isbn' => '9780000000001'],
            'publisher' => 'Client Pub', 'languages' => ['eng'],
            'comments' => 'Client description', 'rating' => 8,
            'pubdate' => '2023-01-15',
        ], $user, $library->id);

        $this->assertNotNull($book->metadata_hash, 'Hash must be stored after upload');

        // Second sync with correct hash → no update needed
        $r2 = $this->syncRequest($library,
            [$uuid => ['m' => $book->metadata_hash, 'c' => null, 'f' => null]],
            [$uuid]);
        $r2->assertOk();
        $this->assertCount(0, $r2->json('updates_for_client') ?? []);
        $this->assertCount(0, $r2->json('missing_from_server') ?? []);
    }

    // ── O. Two clients conflict on same book ────────────────────────────

    public function test_o1_two_clients_modify_same_book_second_sees_first_change(): void
    {
        [$user, $library] = $this->makeUser();
        $book = $this->createBook($library);

        // Initial state
        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Initial',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $initialHash = $book->metadata_hash;

        // Client A syncs and takes the current hash
        $clientAHash = $initialHash;

        // Client B also has the same initial hash
        $clientBHash = $initialHash;

        // Client A modifies title (pushes to server via applyBookMetadata)
        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Client A Title',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hashAfterClientA = $book->metadata_hash;
        $this->assertNotSame($initialHash, $hashAfterClientA);

        // Client B syncs with old hash → sees Client A's change
        $r = $this->syncRequest($library,
            [$book->uuid => ['m' => $clientBHash, 'c' => null, 'f' => null]],
            [$book->uuid]);
        $r->assertOk();
        $updates = $r->json('updates_for_client') ?? [];
        $this->assertCount(1, $updates, 'Client B must get update after Client A modified');
        $this->assertSame('Client A Title', $updates[0]['title']);
        $this->assertSame($hashAfterClientA, $updates[0]['metadata_hash']);
    }

    public function test_o2_two_clients_conflict_last_write_wins(): void
    {
        [$user, $library] = $this->makeUser();
        $book = $this->createBook($library);

        // Initial
        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Initial',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);

        // Client A writes
        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Client A Version',
            'authors' => [['name' => 'Author A']], 'tags' => [],
            'series' => null, 'identifiers' => [], 'publisher' => null,
            'languages' => [], 'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hashA = $book->metadata_hash;

        // Client B writes (overwrites Client A)
        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Client B Version',
            'authors' => [['name' => 'Author B']], 'tags' => [],
            'series' => null, 'identifiers' => [], 'publisher' => null,
            'languages' => [], 'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);
        $hashB = $book->metadata_hash;

        $this->assertNotSame($hashA, $hashB);

        // Any client syncing now sees Client B's version
        $r = $this->syncRequest($library,
            [$book->uuid => ['m' => $hashA, 'c' => null, 'f' => null]],
            [$book->uuid]);
        $r->assertOk();
        $updates = $r->json('updates_for_client') ?? [];
        $this->assertCount(1, $updates);
        $this->assertSame('Client B Version', $updates[0]['title']);
    }

    public function test_o3_client_with_current_hash_sees_no_conflict(): void
    {
        [$user, $library] = $this->makeUser();
        $book = $this->createBook($library);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Stable',
            'authors' => [['name' => 'Stable Author']], 'tags' => [],
            'series' => null, 'identifiers' => [], 'publisher' => null,
            'languages' => [], 'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);

        // Client has current hash → no update, no conflict
        $r = $this->syncRequest($library,
            [$book->uuid => ['m' => $book->metadata_hash, 'c' => null, 'f' => null]],
            [$book->uuid]);
        $r->assertOk();
        $this->assertCount(0, $r->json('updates_for_client') ?? []);
        $this->assertCount(0, $r->json('missing_from_server') ?? []);
    }

    // ── P. Hash correctness under load ──────────────────────────────────

    public function test_p1_100_books_all_get_unique_hashes(): void
    {
        [$user, $library] = $this->makeUser();
        $hashes = [];

        for ($i = 0; $i < 100; $i++) {
            $book = $this->createBook($library, ['id' => 62000 + $i]);
            $this->applyMetadata($book, [
                'uuid' => $book->uuid,
                'title' => 'Book Number ' . $i,
                'authors' => [['name' => 'Author ' . ($i % 10)]],
                'tags' => ($i % 3 === 0) ? [['name' => 'TagA']] : [],
                'series' => ($i % 5 === 0) ? ['name' => 'Series X', 'index' => (float) $i] : null,
                'identifiers' => ($i % 7 === 0) ? ['isbn' => '978' . str_pad($i, 10, '0', STR_PAD_LEFT)] : [],
                'publisher' => ($i % 4 === 0) ? 'Publisher ' . ($i % 3) : null,
                'languages' => ['eng'],
                'comments' => ($i % 2 === 0) ? 'Description ' . $i : null,
                'rating' => ($i % 5 === 0) ? (($i % 10) + 2) : null,
                'pubdate' => '20' . str_pad($i % 30, 2, '0', STR_PAD_LEFT) . '-01-01',
            ], $user, $library->id);

            $this->assertNotNull($book->metadata_hash, "Book $i must have hash");
            $hashes[$book->uuid] = $book->metadata_hash;
        }

        // All hashes must be unique (different titles guarantee this)
        $uniqueHashes = array_unique(array_values($hashes));
        $this->assertCount(100, $uniqueHashes, 'All 100 books must have unique hashes');
    }

    public function test_p2_hash_on_write_matches_sync_response(): void
    {
        [$user, $library] = $this->makeUser();
        $book = $this->createBook($library);

        $this->applyMetadata($book, [
            'uuid' => $book->uuid, 'title' => 'Hash Parity',
            'authors' => [['name' => 'Parity Author']],
            'tags' => [['name' => 'Parity Tag']],
            'series' => ['name' => 'Parity Series', 'index' => 3.0],
            'identifiers' => ['isbn' => '1234567890'],
            'publisher' => 'Parity Pub',
            'languages' => ['eng'],
            'comments' => 'Parity description',
            'rating' => 8,
            'pubdate' => '2022-06-15',
        ], $user, $library->id);

        $storedHash = $book->metadata_hash;

        // Sync with wrong hash → response includes metadata_hash
        $r = $this->syncRequest($library,
            [$book->uuid => ['m' => str_repeat('0', 64), 'c' => null, 'f' => null]],
            [$book->uuid]);
        $r->assertOk();
        $updates = $r->json('updates_for_client') ?? [];
        $this->assertCount(1, $updates);
        $responseHash = $updates[0]['metadata_hash'] ?? null;

        $this->assertSame($storedHash, $responseHash, 'On-write hash must match sync response hash');
    }

    // ── Q. Incremental sync correctness ─────────────────────────────────

    public function test_q1_first_sync_populates_second_sync_skips(): void
    {
        [$user, $library] = $this->makeUser();
        $books = [];
        for ($i = 0; $i < 20; $i++) {
            $book = $this->createBook($library, ['id' => 63000 + $i]);
            $this->applyMetadata($book, [
                'uuid' => $book->uuid, 'title' => 'Incremental ' . $i,
                'authors' => [], 'tags' => [], 'series' => null,
                'identifiers' => [], 'publisher' => null, 'languages' => [],
                'comments' => null, 'rating' => null, 'pubdate' => null,
            ], $user, $library->id);
            $books[] = $book;
        }

        $uuids = array_map(fn ($b) => $b->uuid, $books);

        // First sync: wrong hashes → 20 updates
        $cb1 = [];
        foreach ($uuids as $u) $cb1[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        $r1 = $this->syncRequest($library, $cb1, $uuids);
        $r1->assertOk();
        $this->assertCount(20, $r1->json('updates_for_client') ?? []);

        // Collect correct hashes from response
        $cb2 = [];
        foreach ($r1->json('updates_for_client') as $u) {
            $cb2[$u['uuid']] = ['m' => $u['metadata_hash'], 'c' => null, 'f' => null];
        }

        // Second sync: correct hashes → 0 updates
        $r2 = $this->syncRequest($library, $cb2, $uuids);
        $r2->assertOk();
        $this->assertCount(0, $r2->json('updates_for_client') ?? []);
    }

    public function test_q2_modify_one_book_only_that_book_returns_as_update(): void
    {
        [$user, $library] = $this->makeUser();
        $books = [];
        $hashes = [];
        for ($i = 0; $i < 10; $i++) {
            $book = $this->createBook($library, ['id' => 64000 + $i]);
            $this->applyMetadata($book, [
                'uuid' => $book->uuid, 'title' => 'Selective ' . $i,
                'authors' => [], 'tags' => [], 'series' => null,
                'identifiers' => [], 'publisher' => null, 'languages' => [],
                'comments' => null, 'rating' => null, 'pubdate' => null,
            ], $user, $library->id);
            $books[] = $book;
            $hashes[$book->uuid] = $book->metadata_hash;
        }

        // Modify only book 5
        $this->applyMetadata($books[5], [
            'uuid' => $books[5]->uuid, 'title' => 'MODIFIED Selective 5',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ], $user, $library->id);

        // Sync with old hashes → only book 5 should come back
        $cb = [];
        $uuids = [];
        foreach ($books as $b) {
            $cb[$b->uuid] = ['m' => $hashes[$b->uuid], 'c' => null, 'f' => null];
            $uuids[] = $b->uuid;
        }
        $r = $this->syncRequest($library, $cb, $uuids);
        $r->assertOk();
        $updates = $r->json('updates_for_client') ?? [];
        $this->assertCount(1, $updates, 'Only modified book should return as update');
        $this->assertSame($books[5]->uuid, $updates[0]['uuid']);
        $this->assertSame('MODIFIED Selective 5', $updates[0]['title']);
    }

    // ── R. Stress: rapid apply + sync cycle ─────────────────────────────

    public function test_r1_50_apply_then_sync_all_hashes_consistent(): void
    {
        [$user, $library] = $this->makeUser();
        $books = [];

        // Apply metadata for 50 books rapidly
        for ($i = 0; $i < 50; $i++) {
            $book = $this->createBook($library, ['id' => 65000 + $i]);
            $this->applyMetadata($book, [
                'uuid' => $book->uuid,
                'title' => 'Rapid ' . $i,
                'authors' => [['name' => 'Rapid Author']],
                'tags' => [['name' => 'Rapid']], 'series' => null,
                'identifiers' => [], 'publisher' => null,
                'languages' => ['eng'], 'comments' => 'Desc ' . $i,
                'rating' => null, 'pubdate' => null,
            ], $user, $library->id);
            $books[] = $book;
        }

        // All must have hashes
        $uuids = [];
        $cb = [];
        foreach ($books as $b) {
            $this->assertNotNull($b->metadata_hash, "Book {$b->uuid} missing hash");
            $uuids[] = $b->uuid;
            $cb[$b->uuid] = ['m' => $b->metadata_hash, 'c' => null, 'f' => null];
        }

        // Sync with correct hashes → all skipped
        $r = $this->syncRequest($library, $cb, $uuids);
        $r->assertOk();
        $this->assertCount(0, $r->json('updates_for_client') ?? []);
        $this->assertCount(0, $r->json('missing_from_server') ?? []);
    }
}
