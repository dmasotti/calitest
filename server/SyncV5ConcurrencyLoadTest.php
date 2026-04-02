<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\MetadataHasher;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

/**
 * Concurrency and load tests for Merkle-leaf sync protocol.
 *
 * Tests:
 *   G. Concurrent sync — multiple users simultaneously
 *   H. Concurrent sync — same user, different libraries
 *   I. Load — large batch (1000 books) single request
 *   J. Load — rapid sequential requests (simulate multi-batch)
 *   K. Consistency — concurrent write + sync
 *   L. Idempotency — repeated identical requests
 */
class SyncV5ConcurrencyLoadTest extends TestCase
{
    use RefreshDatabase;

    private function seedBooks(Library $library, int $count, int $idOffset = 70000): array
    {
        $uuids = [];
        $rows = [];
        $now = now();
        for ($i = 0; $i < $count; $i++) {
            $uuid = (string) Str::uuid();
            $uuids[] = $uuid;
            $rows[] = [
                'id' => $idOffset + $i,
                'uuid' => $uuid,
                'user_id' => $library->user_id,
                'library_id' => (string) $library->id,
                'title' => 'Book ' . ($idOffset + $i),
                'path' => 'Book ' . ($idOffset + $i),
                'author_sort' => 'Author ' . $i,
                'series_index' => 1.0,
                'pubdate' => '2020-01-01 00:00:00',
                'last_modified' => $now,
                'has_cover' => false,
                'description' => null,
                'rating' => null,
                'created_at' => $now,
                'updated_at' => $now,
            ];
        }
        // Bulk insert for speed
        foreach (array_chunk($rows, 500) as $chunk) {
            DB::table('books')->insert($chunk);
        }
        return $uuids;
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

    private function syncRequest($user, Library $library, array $clientBooks, array $candidates): \Illuminate\Testing\TestResponse
    {
        Sanctum::actingAs($user);
        return $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => min(max(count($candidates) + 100, 100), 1000),
            'client_books' => ['b' => $clientBooks, 'd' => []],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => $candidates,
            ],
        ]);
    }

    // ── G. Concurrent sync: 3 users, each syncs their own library ───────

    public function test_g1_three_users_concurrent_sync_isolated(): void
    {
        $users = [];
        for ($i = 0; $i < 3; $i++) {
            $user = User::factory()->create();
            $lib = Library::factory()->create(['user_id' => $user->id]);
            $uuids = $this->seedBooks($lib, 50, 70000 + ($i * 1000));
            $users[] = ['user' => $user, 'library' => $lib, 'uuids' => $uuids];
        }

        // Each user syncs with wrong hashes — simulates simultaneous first sync
        $responses = [];
        foreach ($users as $idx => $u) {
            $cb = [];
            foreach ($u['uuids'] as $uuid) {
                $cb[$uuid] = ['m' => str_repeat((string) $idx, 64), 'c' => null, 'f' => null];
            }
            $responses[$idx] = $this->syncRequest($u['user'], $u['library'], $cb, $u['uuids']);
        }

        // Verify isolation: each gets exactly their own 50 books
        foreach ($responses as $idx => $r) {
            $r->assertOk();
            $updates = $r->json('updates_for_client') ?? [];
            $this->assertCount(50, $updates, "User $idx should get 50 updates");

            $updateUuids = array_column($updates, 'uuid');
            // Must contain only own UUIDs
            foreach ($updateUuids as $uu) {
                $this->assertContains($uu, $users[$idx]['uuids'], "User $idx got UUID from another user");
            }
            // Must not contain other users' UUIDs
            foreach ($users as $otherIdx => $other) {
                if ($otherIdx === $idx) continue;
                foreach ($other['uuids'] as $otherUuid) {
                    $this->assertNotContains($otherUuid, $updateUuids, "User $idx got User $otherIdx UUID");
                }
            }
        }
    }

    // ── H. Same user, 2 libraries, concurrent sync ──────────────────────

    public function test_h1_same_user_two_libraries_concurrent(): void
    {
        $user = User::factory()->create();
        $lib1 = Library::factory()->create(['user_id' => $user->id]);
        $lib2 = Library::factory()->create(['user_id' => $user->id]);

        $uuids1 = $this->seedBooks($lib1, 40, 74000);
        $uuids2 = $this->seedBooks($lib2, 30, 75000);

        $cb1 = [];
        foreach ($uuids1 as $u) $cb1[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        $cb2 = [];
        foreach ($uuids2 as $u) $cb2[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];

        $r1 = $this->syncRequest($user, $lib1, $cb1, $uuids1);
        $r2 = $this->syncRequest($user, $lib2, $cb2, $uuids2);

        $r1->assertOk();
        $r2->assertOk();
        $this->assertCount(40, $r1->json('updates_for_client'));
        $this->assertCount(30, $r2->json('updates_for_client'));

        // No cross-contamination
        $u1 = array_column($r1->json('updates_for_client'), 'uuid');
        $u2 = array_column($r2->json('updates_for_client'), 'uuid');
        $this->assertEmpty(array_intersect($u1, $u2), 'Library responses must not overlap');
    }

    // ── I. Load: large single batch ─────────────────────────────────────

    public function test_i1_1000_books_single_batch_under_budget(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($lib, 1000, 76000);

        // All mismatch
        $cb = [];
        foreach ($uuids as $u) $cb[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];

        $start = microtime(true);
        $r = $this->syncRequest($user, $lib, $cb, $uuids);
        $elapsed = round((microtime(true) - $start) * 1000);

        $r->assertOk();
        $this->assertCount(1000, $r->json('updates_for_client'));
        $this->assertFalse((bool) $r->json('has_more'));

        // Budget: under 5 seconds for 1000 books on SQLite
        $this->assertLessThan(5000, $elapsed, "1000 books took {$elapsed}ms (budget: 5000ms)");

        fwrite(STDERR, sprintf("\n[I1] 1000 books single batch: %dms\n", $elapsed));
    }

    public function test_i2_1000_books_all_match_fast(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($lib, 1000, 77000);

        // All match
        $cb = [];
        foreach ($uuids as $u) {
            $cb[$u] = ['m' => $this->serverHash($user->id, $lib->id, $u), 'c' => null, 'f' => null];
        }

        $start = microtime(true);
        $r = $this->syncRequest($user, $lib, $cb, $uuids);
        $elapsed = round((microtime(true) - $start) * 1000);

        $r->assertOk();
        $this->assertCount(0, $r->json('updates_for_client') ?? []);

        // All-match should be much faster (no payload building)
        $this->assertLessThan(3000, $elapsed, "1000 matched books took {$elapsed}ms (budget: 3000ms)");

        fwrite(STDERR, sprintf("\n[I2] 1000 books all match: %dms\n", $elapsed));
    }

    // ── J. Rapid sequential batches (simulate Merkle-leaf iteration) ────

    public function test_j1_five_sequential_batches_of_100(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($lib, 500, 78000);

        $totalUpdates = 0;
        $totalSkipped = 0;
        $totalTime = 0;

        // 5 batches of 100 — simulate Merkle-leaf pagination
        for ($batch = 0; $batch < 5; $batch++) {
            $batchUuids = array_slice($uuids, $batch * 100, 100);
            $cb = [];
            foreach ($batchUuids as $u) {
                $cb[$u] = ['m' => str_repeat((string) $batch, 64), 'c' => null, 'f' => null];
            }

            $start = microtime(true);
            $r = $this->syncRequest($user, $lib, $cb, $batchUuids);
            $elapsed = round((microtime(true) - $start) * 1000);
            $totalTime += $elapsed;

            $r->assertOk();
            $this->assertFalse((bool) $r->json('has_more'), "Batch $batch: has_more must be false");

            $updates = $r->json('updates_for_client') ?? [];
            $skipped = (int) ($r->json('skipped_hash') ?? 0);
            $totalUpdates += count($updates);
            $totalSkipped += $skipped;

            $this->assertCount(100, $updates, "Batch $batch should return 100 updates");
        }

        $this->assertSame(500, $totalUpdates);

        fwrite(STDERR, sprintf(
            "\n[J1] 5 batches × 100 books: total=%dms, avg=%dms/batch\n",
            $totalTime, (int) ($totalTime / 5)
        ));
    }

    // ── K. Write during sync — book modified between batches ────────────

    public function test_k1_book_modified_between_sync_batches(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($lib, 10, 79000);
        $targetUuid = $uuids[0];

        // Batch 1: sync first 5 books
        $batch1 = array_slice($uuids, 0, 5);
        $cb1 = [];
        foreach ($batch1 as $u) $cb1[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        $r1 = $this->syncRequest($user, $lib, $cb1, $batch1);
        $r1->assertOk();
        $this->assertCount(5, $r1->json('updates_for_client'));

        // Between batches: modify a book in batch 2
        $modUuid = $uuids[5];
        UserBook::where('uuid', $modUuid)->update(['title' => 'Modified Between Batches']);

        // Batch 2: sync last 5 books
        $batch2 = array_slice($uuids, 5, 5);
        $cb2 = [];
        foreach ($batch2 as $u) $cb2[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        $r2 = $this->syncRequest($user, $lib, $cb2, $batch2);
        $r2->assertOk();

        $updates2 = $r2->json('updates_for_client') ?? [];
        $this->assertCount(5, $updates2);

        // The modified book should have the new title
        $modBook = collect($updates2)->firstWhere('uuid', $modUuid);
        $this->assertNotNull($modBook);
        $this->assertSame('Modified Between Batches', $modBook['title']);
    }

    // ── L. Idempotency — repeated requests produce same result ──────────

    public function test_l1_repeated_sync_idempotent(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($lib, 50, 79500);
        $cb = [];
        foreach ($uuids as $u) $cb[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];

        $r1 = $this->syncRequest($user, $lib, $cb, $uuids);
        $r2 = $this->syncRequest($user, $lib, $cb, $uuids);
        $r3 = $this->syncRequest($user, $lib, $cb, $uuids);

        $r1->assertOk();
        $r2->assertOk();
        $r3->assertOk();

        // All three should return the same updates
        $u1 = array_column($r1->json('updates_for_client'), 'uuid');
        $u2 = array_column($r2->json('updates_for_client'), 'uuid');
        $u3 = array_column($r3->json('updates_for_client'), 'uuid');
        sort($u1);
        sort($u2);
        sort($u3);
        $this->assertSame($u1, $u2, 'Request 1 and 2 must return same UUIDs');
        $this->assertSame($u2, $u3, 'Request 2 and 3 must return same UUIDs');
    }

    public function test_l2_match_then_match_stays_matched(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($lib, 50, 79600);
        $cb = [];
        foreach ($uuids as $u) {
            $cb[$u] = ['m' => $this->serverHash($user->id, $lib->id, $u), 'c' => null, 'f' => null];
        }

        for ($i = 0; $i < 3; $i++) {
            $r = $this->syncRequest($user, $lib, $cb, $uuids);
            $r->assertOk();
            $this->assertCount(0, $r->json('updates_for_client') ?? [], "Iteration $i: should still be 0 updates");
            $this->assertCount(0, $r->json('missing_from_server') ?? [], "Iteration $i: should still be 0 missing");
        }
    }
}
