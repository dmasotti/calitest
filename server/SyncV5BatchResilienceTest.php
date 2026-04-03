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
 * Batch resilience tests — verify server behavior under error conditions.
 *
 * These test the SERVER side: what happens when batches arrive in various
 * states. The CLIENT retry logic is tested in sync_calimob Python tests.
 *
 * Edge case matrix from TODO 2026-04-03_sync_batch_resilience.md
 */
class SyncV5BatchResilienceTest extends TestCase
{
    use RefreshDatabase;

    private function seedBooks(Library $library, int $count, int $idOffset = 90000): array
    {
        $uuids = [];
        $now = now()->toDateTimeString();
        for ($i = 0; $i < $count; $i++) {
            $uuid = (string) Str::uuid();
            $uuids[] = $uuid;
            DB::table('books')->insert([
                'id' => $idOffset + $i, 'uuid' => $uuid,
                'user_id' => $library->user_id,
                'library_id' => (string) $library->id,
                'title' => 'Book ' . ($idOffset + $i),
                'path' => 'Book ' . ($idOffset + $i),
                'pubdate' => '2020-01-01', 'last_modified' => $now,
                'has_cover' => false, 'created_at' => $now, 'updated_at' => $now,
            ]);
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

    // ── #8: Partial batch success — first batch OK, second has different data ──

    public function test_partial_batch_first_ok_second_mismatch(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($library, 100);

        // Batch 1: all match
        $cb1 = [];
        $batch1 = array_slice($uuids, 0, 50);
        foreach ($batch1 as $u) {
            $cb1[$u] = ['m' => $this->serverHash($user->id, $library->id, $u), 'c' => null, 'f' => null];
        }
        $r1 = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null, 'batch_size' => 1000,
            'client_books' => ['b' => $cb1, 'd' => []],
            'options' => ['sync_files_enabled' => false, 'sync_covers_enabled' => false,
                          'metadata_candidate_uuids' => $batch1],
        ]);
        $r1->assertOk();
        $this->assertCount(0, $r1->json('updates_for_client') ?? []);

        // Batch 2: all mismatch (simulates what would happen after a timeout+retry)
        $cb2 = [];
        $batch2 = array_slice($uuids, 50, 50);
        foreach ($batch2 as $u) {
            $cb2[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        }
        $r2 = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null, 'batch_size' => 1000,
            'client_books' => ['b' => $cb2, 'd' => []],
            'options' => ['sync_files_enabled' => false, 'sync_covers_enabled' => false,
                          'metadata_candidate_uuids' => $batch2],
        ]);
        $r2->assertOk();
        $this->assertCount(50, $r2->json('updates_for_client') ?? []);

        // Batch 1 and 2 are independent — batch 2's results don't affect batch 1
    }

    // ── #7: Repeated batch (retry) is idempotent ──

    public function test_repeated_batch_is_idempotent(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($library, 50);

        $cb = [];
        foreach ($uuids as $u) {
            $cb[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        }
        $body = [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null, 'batch_size' => 1000,
            'client_books' => ['b' => $cb, 'd' => []],
            'options' => ['sync_files_enabled' => false, 'sync_covers_enabled' => false,
                          'metadata_candidate_uuids' => $uuids],
        ];

        // Same request 3 times (simulates retry after timeout)
        $r1 = $this->postJson('/api/sync/v5', $body);
        $r2 = $this->postJson('/api/sync/v5', $body);
        $r3 = $this->postJson('/api/sync/v5', $body);

        $r1->assertOk();
        $r2->assertOk();
        $r3->assertOk();

        // All must return the same result
        $u1 = collect($r1->json('updates_for_client'))->pluck('uuid')->sort()->values();
        $u2 = collect($r2->json('updates_for_client'))->pluck('uuid')->sort()->values();
        $u3 = collect($r3->json('updates_for_client'))->pluck('uuid')->sort()->values();
        $this->assertEquals($u1, $u2, 'Retry must be idempotent');
        $this->assertEquals($u2, $u3, 'Retry must be idempotent');
    }

    // ── #11: Empty batch (no candidates) does not crash ──

    public function test_empty_client_books_no_crash(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($library, 10);

        // Client sends candidates but no client_books (e.g. hash build failed)
        $r = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null, 'batch_size' => 100,
            'client_books' => ['b' => [], 'd' => []],
            'options' => ['sync_files_enabled' => false, 'sync_covers_enabled' => false,
                          'metadata_candidate_uuids' => $uuids],
        ]);
        // Server should not crash — returns books as updates (no client hash to compare)
        $r->assertOk();
    }

    // ── #10: Invalid payload returns 422, not 500 ──

    public function test_invalid_payload_returns_422(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $r = $this->postJson('/api/sync/v5', [
            'library_id' => 'not-a-number',
            'calibre_library_uuid' => 'not-a-uuid!!!',
        ]);
        $r->assertStatus(422);
    }

    // ── #12: Batch after partial sync sees only remaining mismatches ──

    public function test_batch_after_partial_sync_only_remaining(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($library, 20);

        // Batch 1: first 10, all mismatch → server sends updates
        $batch1 = array_slice($uuids, 0, 10);
        $cb1 = [];
        foreach ($batch1 as $u) {
            $cb1[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        }
        $r1 = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null, 'batch_size' => 1000,
            'client_books' => ['b' => $cb1, 'd' => []],
            'options' => ['sync_files_enabled' => false, 'sync_covers_enabled' => false,
                          'metadata_candidate_uuids' => $batch1],
        ]);
        $r1->assertOk();
        $this->assertCount(10, $r1->json('updates_for_client'));

        // Batch 2: last 10, correct hashes → all match
        $batch2 = array_slice($uuids, 10, 10);
        $cb2 = [];
        foreach ($batch2 as $u) {
            $cb2[$u] = ['m' => $this->serverHash($user->id, $library->id, $u), 'c' => null, 'f' => null];
        }
        $r2 = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null, 'batch_size' => 1000,
            'client_books' => ['b' => $cb2, 'd' => []],
            'options' => ['sync_files_enabled' => false, 'sync_covers_enabled' => false,
                          'metadata_candidate_uuids' => $batch2],
        ]);
        $r2->assertOk();
        $this->assertCount(0, $r2->json('updates_for_client') ?? []);

        // Now "retry" batch 1 with correct hashes (client applied updates) → 0 updates
        $cb1_fixed = [];
        foreach ($r1->json('updates_for_client') as $upd) {
            $cb1_fixed[$upd['uuid']] = ['m' => $upd['metadata_hash'], 'c' => null, 'f' => null];
        }
        $r1_retry = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null, 'batch_size' => 1000,
            'client_books' => ['b' => $cb1_fixed, 'd' => []],
            'options' => ['sync_files_enabled' => false, 'sync_covers_enabled' => false,
                          'metadata_candidate_uuids' => $batch1],
        ]);
        $r1_retry->assertOk();
        $this->assertCount(0, $r1_retry->json('updates_for_client') ?? []);
    }

    // ── #9: Concurrent batches from same library don't interfere ──

    public function test_concurrent_batches_same_library(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuids = $this->seedBooks($library, 40);

        $batch1 = array_slice($uuids, 0, 20);
        $batch2 = array_slice($uuids, 20, 20);

        $cb1 = $cb2 = [];
        foreach ($batch1 as $u) $cb1[$u] = ['m' => str_repeat('a', 64), 'c' => null, 'f' => null];
        foreach ($batch2 as $u) $cb2[$u] = ['m' => str_repeat('b', 64), 'c' => null, 'f' => null];

        // Fire both batches
        $r1 = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null, 'batch_size' => 1000,
            'client_books' => ['b' => $cb1, 'd' => []],
            'options' => ['sync_files_enabled' => false, 'sync_covers_enabled' => false,
                          'metadata_candidate_uuids' => $batch1],
        ]);
        $r2 = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null, 'batch_size' => 1000,
            'client_books' => ['b' => $cb2, 'd' => []],
            'options' => ['sync_files_enabled' => false, 'sync_covers_enabled' => false,
                          'metadata_candidate_uuids' => $batch2],
        ]);

        $r1->assertOk();
        $r2->assertOk();

        // Each batch only returns its own books
        $u1 = collect($r1->json('updates_for_client'))->pluck('uuid')->toArray();
        $u2 = collect($r2->json('updates_for_client'))->pluck('uuid')->toArray();
        $this->assertCount(20, $u1);
        $this->assertCount(20, $u2);
        $this->assertEmpty(array_intersect($u1, $u2), 'Batches must not overlap');
    }
}
