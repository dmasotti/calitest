<?php

namespace Tests\Server;

use App\Models\BookFile;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\MetadataHasher;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

/**
 * E2E test battery for Merkle-leaf pagination sync protocol.
 *
 * Matrix:
 *   A. Bidirectional — server→client, client→server
 *   B. Partial mismatch — only subset needs sync
 *   C. Multi-user concurrency — different users/libraries don't interfere
 *   D. Load — 500+ books in single batch
 *   E. Edge cases — empty library, all deleted, single book
 *   F. Server metadata changes propagate to client response
 */
class SyncV5MerkleLeafE2ETest extends TestCase
{
    use RefreshDatabase;

    // ── Helpers ───────────────────────────────────────────────────────────

    private function makeUser(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);
        return [$user, $library];
    }

    private function seedBooks(Library $library, int $count, int $idOffset = 90000): array
    {
        $books = [];
        $lm = Carbon::create(2026, 3, 1, 12, 0, 0, 'UTC');
        for ($i = 0; $i < $count; $i++) {
            $uuid = (string) Str::uuid();
            UserBook::create([
                'id' => $idOffset + $i,
                'uuid' => $uuid,
                'user_id' => $library->user_id,
                'library_id' => (string) $library->id,
                'title' => 'Book ' . ($idOffset + $i),
                'path' => 'Book ' . ($idOffset + $i),
                'author_sort' => 'Author ' . $i,
                'series_index' => 1.0,
                'pubdate' => '2020-01-01 00:00:00',
                'last_modified' => $lm,
                'has_cover' => false,
                'description' => null,
                'rating' => null,
                'created_at' => now(),
                'updated_at' => now(),
            ]);
            $books[] = $uuid;
        }
        return $books;
    }

    private function serverHash(int $userId, int $libraryId, string $uuid): string
    {
        if (Schema::hasTable('books_hash_v2')) {
            $h = DB::table('books_hash_v2')
                ->where('user_id', $userId)->where('library_id', $libraryId)
                ->where('uuid', $uuid)->value('metadata_hash');
            if ($h) return strtolower((string) $h);
        }
        $book = UserBook::where('uuid', $uuid)->firstOrFail();
        return (string) MetadataHasher::computeHash([
            'uuid' => $book->uuid, 'title' => $book->title,
            'author_sort' => $book->author_sort, 'authors' => [],
            'series' => null, 'series_index' => $book->series_index,
            'tags' => [], 'identifiers' => [], 'publisher' => null,
            'languages' => [], 'pubdate' => $book->pubdate,
            'description' => $book->description, 'rating' => $book->rating,
        ]);
    }

    private function syncRequest(Library $library, array $clientBooks, array $candidateUuids, array $extra = []): \Illuminate\Testing\TestResponse
    {
        return $this->postJson('/api/sync/v5', array_merge([
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => max(count($candidateUuids) + 100, 100),
            'client_books' => ['b' => $clientBooks, 'd' => $extra['deleted'] ?? []],
            'options' => [
                'sync_files_enabled' => $extra['sync_files'] ?? false,
                'sync_covers_enabled' => $extra['sync_covers'] ?? false,
                'metadata_candidate_uuids' => $candidateUuids,
            ],
        ], $extra['merge'] ?? []));
    }

    // ── A. Full lifecycle: first sync (mismatch) → second sync (match) ──

    public function test_a1_full_lifecycle_500_books(): void
    {
        [$user, $library] = $this->makeUser();
        $uuids = $this->seedBooks($library, 500);

        // Sync 1: all wrong hashes → 500 updates
        $cb1 = [];
        foreach ($uuids as $u) $cb1[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];

        $t1 = microtime(true);
        $r1 = $this->syncRequest($library, $cb1, $uuids);
        $t1ms = round((microtime(true) - $t1) * 1000);
        $r1->assertOk();
        $this->assertCount(500, $r1->json('updates_for_client'));
        $this->assertFalse((bool) $r1->json('has_more'), 'Merkle path: no has_more');

        // Sync 2: correct hashes → 0 updates
        $cb2 = [];
        foreach ($uuids as $u) $cb2[$u] = ['m' => $this->serverHash($user->id, $library->id, $u), 'c' => null, 'f' => null];

        $t2 = microtime(true);
        $r2 = $this->syncRequest($library, $cb2, $uuids);
        $t2ms = round((microtime(true) - $t2) * 1000);
        $r2->assertOk();
        $this->assertCount(0, $r2->json('updates_for_client') ?? []);
        $this->assertCount(0, $r2->json('missing_from_server') ?? []);

        fwrite(STDERR, sprintf("\n[A1] 500 books: Sync1=%dms (500 updates), Sync2=%dms (0 updates)\n", $t1ms, $t2ms));
    }

    // ── B. Partial mismatch — Merkle drilldown sends only candidates ────

    public function test_b1_partial_mismatch_50_of_200(): void
    {
        [$user, $library] = $this->makeUser();
        $uuids = $this->seedBooks($library, 200);

        // First 150: correct hash. Last 50: wrong hash.
        $cb = [];
        $candidates = [];
        foreach ($uuids as $i => $u) {
            if ($i < 150) {
                $cb[$u] = ['m' => $this->serverHash($user->id, $library->id, $u), 'c' => null, 'f' => null];
            } else {
                $cb[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
                $candidates[] = $u;
            }
        }

        // Send only 50 candidates (Merkle drilldown result)
        $r = $this->syncRequest($library, $cb, $candidates);
        $r->assertOk();
        $updates = $r->json('updates_for_client') ?? [];
        $this->assertCount(50, $updates, 'Only 50 mismatched candidates should produce updates');

        // Verify none of the 150 matched UUIDs leaked
        $updateUuids = array_column($updates, 'uuid');
        foreach (array_slice($uuids, 0, 150) as $matchUuid) {
            $this->assertNotContains($matchUuid, $updateUuids);
        }
    }

    public function test_b2_candidates_with_all_matching_returns_no_updates(): void
    {
        [$user, $library] = $this->makeUser();
        $uuids = $this->seedBooks($library, 50);

        // All hashes match → 0 updates
        $cb = [];
        foreach ($uuids as $u) {
            $cb[$u] = ['m' => $this->serverHash($user->id, $library->id, $u), 'c' => null, 'f' => null];
        }
        $r = $this->syncRequest($library, $cb, $uuids);
        $r->assertOk();
        $this->assertCount(0, $r->json('updates_for_client') ?? []);
        $this->assertCount(0, $r->json('missing_from_server') ?? []);
    }

    // ── C. Multi-user concurrency — users don't see each other's books ──

    public function test_c1_two_users_isolated(): void
    {
        // User A
        $userA = User::factory()->create();
        $libA = Library::factory()->create(['user_id' => $userA->id]);
        $uuidsA = $this->seedBooks($libA, 30, 80000);

        // User B
        $userB = User::factory()->create();
        $libB = Library::factory()->create(['user_id' => $userB->id]);
        $uuidsB = $this->seedBooks($libB, 20, 81000);

        // User A syncs — should see only their 30 books
        Sanctum::actingAs($userA);
        $cbA = [];
        foreach ($uuidsA as $u) $cbA[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        $rA = $this->syncRequest($libA, $cbA, $uuidsA);
        $rA->assertOk();
        $this->assertCount(30, $rA->json('updates_for_client'));
        $updatesA = array_column($rA->json('updates_for_client'), 'uuid');
        foreach ($uuidsB as $ub) {
            $this->assertNotContains($ub, $updatesA, 'User A must not see User B books');
        }

        // User B syncs — should see only their 20 books
        Sanctum::actingAs($userB);
        $cbB = [];
        foreach ($uuidsB as $u) $cbB[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        $rB = $this->syncRequest($libB, $cbB, $uuidsB);
        $rB->assertOk();
        $this->assertCount(20, $rB->json('updates_for_client'));
        $updatesB = array_column($rB->json('updates_for_client'), 'uuid');
        foreach ($uuidsA as $ua) {
            $this->assertNotContains($ua, $updatesB, 'User B must not see User A books');
        }
    }

    public function test_c2_same_user_two_libraries_isolated(): void
    {
        $user = User::factory()->create();
        $lib1 = Library::factory()->create(['user_id' => $user->id]);
        $lib2 = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids1 = $this->seedBooks($lib1, 15, 82000);
        $uuids2 = $this->seedBooks($lib2, 10, 83000);

        $cb1 = [];
        foreach ($uuids1 as $u) $cb1[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        $r1 = $this->syncRequest($lib1, $cb1, $uuids1);
        $r1->assertOk();
        $this->assertCount(15, $r1->json('updates_for_client'));

        $cb2 = [];
        foreach ($uuids2 as $u) $cb2[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        $r2 = $this->syncRequest($lib2, $cb2, $uuids2);
        $r2->assertOk();
        $this->assertCount(10, $r2->json('updates_for_client'));

        // Cross-check: lib1 UUIDs not in lib2 response
        $u2 = array_column($r2->json('updates_for_client'), 'uuid');
        foreach ($uuids1 as $u) $this->assertNotContains($u, $u2);
    }

    // ── D. Server metadata change → client gets update ──────────────────

    public function test_d1_server_title_change_propagates(): void
    {
        [$user, $library] = $this->makeUser();
        $uuids = $this->seedBooks($library, 1, 84000);
        $uuid = $uuids[0];

        // Client has old hash
        $oldHash = $this->serverHash($user->id, $library->id, $uuid);

        // Server changes title
        UserBook::where('uuid', $uuid)->update(['title' => 'Updated Title']);

        // New hash should differ
        $newHash = $this->serverHash($user->id, $library->id, $uuid);
        $this->assertNotSame($oldHash, $newHash, 'Hash must change after title update');

        // Client syncs with old hash → gets update with new title
        $r = $this->syncRequest($library, [$uuid => ['m' => $oldHash, 'c' => null, 'f' => null]], [$uuid]);
        $r->assertOk();
        $updates = $r->json('updates_for_client') ?? [];
        $this->assertCount(1, $updates);
        $this->assertSame('Updated Title', $updates[0]['title']);
    }

    public function test_d2_server_description_cleared_propagates(): void
    {
        [$user, $library] = $this->makeUser();
        $uuid = (string) Str::uuid();
        UserBook::create([
            'id' => 84100,
            'uuid' => $uuid,
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'title' => 'Has Description',
            'path' => 'Has Description',
            'pubdate' => '2020-01-01',
            'last_modified' => now(),
            'description' => '<p>Some text</p>',
        ]);
        $oldHash = $this->serverHash($user->id, $library->id, $uuid);

        // Clear description on server
        UserBook::where('uuid', $uuid)->update(['description' => null]);
        $newHash = $this->serverHash($user->id, $library->id, $uuid);
        $this->assertNotSame($oldHash, $newHash);

        $r = $this->syncRequest($library, [$uuid => ['m' => $oldHash, 'c' => null, 'f' => null]], [$uuid]);
        $r->assertOk();
        $updates = $r->json('updates_for_client') ?? [];
        $this->assertCount(1, $updates);
        $this->assertNull($updates[0]['description']);
    }

    // ── E. Client has book server doesn't → missing_from_server ─────────

    public function test_e1_client_only_book_reported_missing(): void
    {
        [$user, $library] = $this->makeUser();
        $unknownUuid = (string) Str::uuid();

        $r = $this->syncRequest(
            $library,
            [$unknownUuid => ['m' => str_repeat('a', 64), 'c' => null, 'f' => null]],
            [$unknownUuid]
        );
        $r->assertOk();
        $missing = $r->json('missing_from_server') ?? [];
        $missingUuids = array_column($missing, 'uuid');
        $this->assertContains($unknownUuid, $missingUuids);
    }

    public function test_e2_deleted_book_not_in_missing(): void
    {
        [$user, $library] = $this->makeUser();
        $uuids = $this->seedBooks($library, 1, 85000);
        $uuid = $uuids[0];

        // Soft-delete on server
        UserBook::where('uuid', $uuid)->update(['deleted_at' => now()]);

        $r = $this->syncRequest(
            $library,
            [$uuid => ['m' => str_repeat('0', 64), 'c' => null, 'f' => null]],
            [$uuid]
        );
        $r->assertOk();
        $deleted = $r->json('deleted_on_server') ?? [];
        $this->assertContains($uuid, $deleted);
        $missingUuids = array_column($r->json('missing_from_server') ?? [], 'uuid');
        $this->assertNotContains($uuid, $missingUuids, 'Deleted book must not appear in missing_from_server');
    }

    // ── F. Edge cases ────────────────────────────────────────────────────

    public function test_f1_empty_library_sync(): void
    {
        [$user, $library] = $this->makeUser();
        $r = $this->syncRequest($library, [], []);
        $r->assertOk();
        $this->assertCount(0, $r->json('updates_for_client') ?? []);
        $this->assertCount(0, $r->json('missing_from_server') ?? []);
    }

    public function test_f2_single_book_exact_match(): void
    {
        [$user, $library] = $this->makeUser();
        $uuids = $this->seedBooks($library, 1, 86000);
        $uuid = $uuids[0];
        $hash = $this->serverHash($user->id, $library->id, $uuid);

        $r = $this->syncRequest($library, [$uuid => ['m' => $hash, 'c' => null, 'f' => null]], [$uuid]);
        $r->assertOk();
        $this->assertCount(0, $r->json('updates_for_client') ?? []);
        $this->assertCount(0, $r->json('missing_from_server') ?? []);
    }

    public function test_f3_client_sends_delete_and_server_confirms(): void
    {
        [$user, $library] = $this->makeUser();
        $uuids = $this->seedBooks($library, 1, 87000);
        $uuid = $uuids[0];

        $r = $this->syncRequest($library, [], [$uuid], ['deleted' => [$uuid]]);
        $r->assertOk();

        // Book should be soft-deleted on server
        $book = UserBook::withTrashed()->where('uuid', $uuid)->first();
        $this->assertNotNull($book);
        $this->assertNotNull($book->deleted_at);
    }

    public function test_f4_has_more_always_false_with_merkle_path(): void
    {
        [$user, $library] = $this->makeUser();
        $uuids = $this->seedBooks($library, 100, 88000);

        $cb = [];
        foreach ($uuids as $u) $cb[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];

        // Even with batch_size=10, Merkle path ignores it
        $r = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 10,
            'client_books' => ['b' => $cb, 'd' => []],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => $uuids,
            ],
        ]);
        $r->assertOk();
        $this->assertFalse((bool) $r->json('has_more'), 'Merkle path: has_more must be false regardless of batch_size');
        $this->assertCount(100, $r->json('updates_for_client'));
    }

    public function test_f5_mixed_match_mismatch_missing_deleted(): void
    {
        [$user, $library] = $this->makeUser();

        // 3 books on server
        $uuids = $this->seedBooks($library, 3, 89000);
        $matchUuid = $uuids[0];
        $mismatchUuid = $uuids[1];
        $deletedUuid = $uuids[2];

        // Delete one on server
        UserBook::where('uuid', $deletedUuid)->update(['deleted_at' => now()]);

        // Client has 4 books: 1 match, 1 mismatch, 1 deleted on server, 1 unknown
        $unknownUuid = (string) Str::uuid();
        $allCandidates = [$matchUuid, $mismatchUuid, $deletedUuid, $unknownUuid];

        $cb = [
            $matchUuid => ['m' => $this->serverHash($user->id, $library->id, $matchUuid), 'c' => null, 'f' => null],
            $mismatchUuid => ['m' => str_repeat('0', 64), 'c' => null, 'f' => null],
            $deletedUuid => ['m' => str_repeat('0', 64), 'c' => null, 'f' => null],
            $unknownUuid => ['m' => str_repeat('a', 64), 'c' => null, 'f' => null],
        ];

        $r = $this->syncRequest($library, $cb, $allCandidates);
        $r->assertOk();

        $updates = collect($r->json('updates_for_client') ?? []);
        $missing = collect($r->json('missing_from_server') ?? []);
        $deleted = $r->json('deleted_on_server') ?? [];

        // Match: skipped (not in updates)
        $this->assertNull($updates->firstWhere('uuid', $matchUuid), 'Matched book should not be in updates');
        // Mismatch: in updates
        $this->assertNotNull($updates->firstWhere('uuid', $mismatchUuid), 'Mismatched book should be in updates');
        // Deleted: in deleted_on_server
        $this->assertContains($deletedUuid, $deleted, 'Deleted book should be in deleted_on_server');
        // Unknown: in missing_from_server
        $missingUuids = $missing->pluck('uuid')->toArray();
        $this->assertContains($unknownUuid, $missingUuids, 'Unknown book should be in missing_from_server');
    }
}
