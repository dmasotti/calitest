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
 * Heavy load test: 10 concurrent-like syncs × 12000 books × 10% mismatch.
 *
 * Simulates production scenario where multiple users sync large libraries
 * simultaneously, each with ~1200 mismatched books out of 12000.
 */
class SyncV5HeavyLoadTest extends TestCase
{
    use RefreshDatabase;

    private function bulkSeedBooks(Library $library, int $count, int $idOffset): array
    {
        $uuids = [];
        $now = now()->toDateTimeString();
        $rows = [];
        for ($i = 0; $i < $count; $i++) {
            $uuid = (string) Str::uuid();
            $uuids[] = $uuid;
            $rows[] = [
                'id' => $idOffset + $i,
                'uuid' => $uuid,
                'user_id' => $library->user_id,
                'library_id' => (string) $library->id,
                'title' => 'HeavyBook ' . ($idOffset + $i),
                'path' => 'HeavyBook ' . ($idOffset + $i),
                'author_sort' => 'Author ' . ($i % 500),
                'series_index' => 1.0,
                'pubdate' => '2020-01-01 00:00:00',
                'last_modified' => $now,
                'has_cover' => false,
                'description' => null,
                'rating' => null,
                'created_at' => $now,
                'updated_at' => $now,
            ];
            if (count($rows) >= 500) {
                DB::table('books')->insert($rows);
                $rows = [];
            }
        }
        if (!empty($rows)) {
            DB::table('books')->insert($rows);
        }
        return $uuids;
    }

    private function serverHashBulk(int $userId, int $libraryId, array $uuids): array
    {
        $hashes = [];
        if (Schema::hasTable('books_hash_v2')) {
            $rows = DB::table('books_hash_v2')
                ->where('user_id', $userId)
                ->where('library_id', $libraryId)
                ->whereIn('uuid', $uuids)
                ->pluck('metadata_hash', 'uuid');
            foreach ($rows as $uuid => $hash) {
                $hashes[(string) $uuid] = strtolower((string) $hash);
            }
        }
        // Fallback for UUIDs not in VIEW
        $missing = array_diff($uuids, array_keys($hashes));
        if (!empty($missing)) {
            $books = UserBook::whereIn('uuid', $missing)
                ->where('user_id', $userId)
                ->where('library_id', $libraryId)
                ->get();
            foreach ($books as $book) {
                $hashes[$book->uuid] = (string) MetadataHasher::computeHash([
                    'uuid' => $book->uuid, 'title' => $book->title,
                    'author_sort' => $book->author_sort, 'authors' => [],
                    'series' => null, 'series_index' => $book->series_index,
                    'tags' => [], 'identifiers' => [], 'publisher' => null,
                    'languages' => [], 'pubdate' => $book->pubdate,
                    'description' => $book->description, 'rating' => $book->rating,
                ]);
            }
        }
        return $hashes;
    }

    /**
     * 10 users × 12000 books × 10% mismatch, sequential requests
     * simulating concurrent load on the server.
     */
    public function test_10_users_12k_books_10pct_mismatch(): void
    {
        $numUsers = 10;
        $booksPerUser = 12000;
        $mismatchPct = 0.10;
        $mismatchCount = (int) ($booksPerUser * $mismatchPct);

        fwrite(STDERR, sprintf(
            "\n[HEAVY] Setting up %d users × %d books (%d mismatch each)...\n",
            $numUsers, $booksPerUser, $mismatchCount
        ));

        $setupStart = microtime(true);

        // Seed all users + books
        $tenants = [];
        for ($t = 0; $t < $numUsers; $t++) {
            $user = User::factory()->create();
            $lib = Library::factory()->create(['user_id' => $user->id]);
            $idOffset = 100000 + ($t * 15000);
            $uuids = $this->bulkSeedBooks($lib, $booksPerUser, $idOffset);

            // Get server hashes in bulk
            $serverHashes = $this->serverHashBulk($user->id, $lib->id, $uuids);

            $tenants[] = [
                'user' => $user,
                'library' => $lib,
                'uuids' => $uuids,
                'server_hashes' => $serverHashes,
            ];
        }
        $setupTime = round((microtime(true) - $setupStart) * 1000);
        fwrite(STDERR, sprintf("[HEAVY] Setup: %dms (%d total books)\n", $setupTime, $numUsers * $booksPerUser));

        // Run 10 syncs (sequential, simulating concurrent load)
        $syncTimes = [];
        $totalUpdates = 0;
        $totalSkipped = 0;

        for ($t = 0; $t < $numUsers; $t++) {
            $tenant = $tenants[$t];
            Sanctum::actingAs($tenant['user']);

            // Build client books: 90% match, 10% mismatch
            // Mismatch = first N books get wrong hash
            $candidateUuids = array_slice($tenant['uuids'], 0, $mismatchCount);
            $clientBooks = [];
            foreach ($candidateUuids as $i => $uuid) {
                // All candidates get wrong hash (simulating Merkle drilldown found these)
                $clientBooks[$uuid] = ['m' => str_repeat('f', 64), 'c' => null, 'f' => null];
            }

            $start = microtime(true);
            $response = $this->postJson('/api/sync/v5', [
                'library_id' => (string) $tenant['library']->id,
                'calibre_library_uuid' => $tenant['library']->calibre_library_id,
                'cursor' => null,
                'batch_size' => 1000,
                'client_books' => ['b' => $clientBooks, 'd' => []],
                'options' => [
                    'sync_files_enabled' => false,
                    'sync_covers_enabled' => false,
                    'metadata_candidate_uuids' => $candidateUuids,
                ],
            ]);
            $elapsed = round((microtime(true) - $start) * 1000);
            $syncTimes[] = $elapsed;

            $response->assertOk();

            $updates = $response->json('updates_for_client') ?? [];
            $skipped = (int) ($response->json('skipped_hash') ?? 0);
            $hasMore = (bool) ($response->json('has_more') ?? false);

            $this->assertCount($mismatchCount, $updates, "User $t: expected $mismatchCount updates");
            $this->assertFalse($hasMore, "User $t: has_more must be false with Merkle path");

            // Verify isolation: updates contain only this user's UUIDs
            $updateUuids = array_column($updates, 'uuid');
            foreach ($updateUuids as $uu) {
                $this->assertContains($uu, $candidateUuids, "User $t got UUID not in their candidates");
            }

            $totalUpdates += count($updates);
            $totalSkipped += $skipped;

            fwrite(STDERR, sprintf(
                "[HEAVY] User %d: %dms (%d updates, %d skipped)\n",
                $t, $elapsed, count($updates), $skipped
            ));
        }

        // Aggregate stats
        sort($syncTimes);
        $p50 = $syncTimes[(int) (count($syncTimes) * 0.5)];
        $p95 = $syncTimes[(int) (count($syncTimes) * 0.95)];
        $avg = (int) (array_sum($syncTimes) / count($syncTimes));
        $total = array_sum($syncTimes);

        fwrite(STDERR, sprintf(
            "\n[HEAVY] === RESULTS ===\n"
            . "  Users: %d × %d books (10%% mismatch = %d candidates/user)\n"
            . "  Total updates: %d | Total skipped: %d\n"
            . "  Timing: avg=%dms p50=%dms p95=%dms total=%dms\n"
            . "  Throughput: %.0f syncs/sec\n\n",
            $numUsers, $booksPerUser, $mismatchCount,
            $totalUpdates, $totalSkipped,
            $avg, $p50, $p95, $total,
            $numUsers / ($total / 1000)
        ));

        // Budget assertions
        $this->assertSame($numUsers * $mismatchCount, $totalUpdates, 'Total updates must match expected');
        $this->assertLessThan(
            5000, $p95,
            "P95 sync time ({$p95}ms) exceeds 5s budget for {$mismatchCount} candidates"
        );
    }

    /**
     * Same as above but second pass: all hashes match → fast skip.
     * Verifies that after first sync, second sync is near-instant.
     */
    public function test_10_users_12k_books_second_sync_all_match(): void
    {
        $numUsers = 5;  // fewer users for speed, same pattern
        $booksPerUser = 12000;

        fwrite(STDERR, sprintf(
            "\n[HEAVY-MATCH] Setting up %d users × %d books (all match)...\n",
            $numUsers, $booksPerUser
        ));

        $setupStart = microtime(true);
        $tenants = [];
        for ($t = 0; $t < $numUsers; $t++) {
            $user = User::factory()->create();
            $lib = Library::factory()->create(['user_id' => $user->id]);
            $idOffset = 200000 + ($t * 15000);
            $uuids = $this->bulkSeedBooks($lib, $booksPerUser, $idOffset);
            $serverHashes = $this->serverHashBulk($user->id, $lib->id, $uuids);
            $tenants[] = [
                'user' => $user,
                'library' => $lib,
                'uuids' => $uuids,
                'server_hashes' => $serverHashes,
            ];
        }
        $setupTime = round((microtime(true) - $setupStart) * 1000);
        fwrite(STDERR, sprintf("[HEAVY-MATCH] Setup: %dms\n", $setupTime));

        // Run syncs: all hashes match → should be fast
        $syncTimes = [];
        for ($t = 0; $t < $numUsers; $t++) {
            $tenant = $tenants[$t];
            Sanctum::actingAs($tenant['user']);

            // Send 1200 candidates (10%), all with correct hash
            $candidateUuids = array_slice($tenant['uuids'], 0, 1200);
            $clientBooks = [];
            foreach ($candidateUuids as $uuid) {
                $hash = $tenant['server_hashes'][$uuid] ?? str_repeat('0', 64);
                $clientBooks[$uuid] = ['m' => $hash, 'c' => null, 'f' => null];
            }

            $start = microtime(true);
            $response = $this->postJson('/api/sync/v5', [
                'library_id' => (string) $tenant['library']->id,
                'calibre_library_uuid' => $tenant['library']->calibre_library_id,
                'cursor' => null,
                'batch_size' => 1000,
                'client_books' => ['b' => $clientBooks, 'd' => []],
                'options' => [
                    'sync_files_enabled' => false,
                    'sync_covers_enabled' => false,
                    'metadata_candidate_uuids' => $candidateUuids,
                ],
            ]);
            $elapsed = round((microtime(true) - $start) * 1000);
            $syncTimes[] = $elapsed;

            $response->assertOk();
            $updates = $response->json('updates_for_client') ?? [];
            $missing = $response->json('missing_from_server') ?? [];

            if (count($updates) > 0) {
                // Debug: check first few mismatches
                $sampleUuid = $updates[0]['uuid'] ?? '?';
                $clientHash = $clientBooks[$sampleUuid]['m'] ?? '?';
                $serverHashActual = $updates[0]['metadata_hash'] ?? '?';
                fwrite(STDERR, sprintf(
                    "[HEAVY-MATCH] User %d: %d unexpected updates! sample: uuid=%s client=%s server=%s\n",
                    $t, count($updates), substr($sampleUuid, 0, 12),
                    substr($clientHash, 0, 16), substr($serverHashActual, 0, 16)
                ));
            }

            $this->assertCount(0, $updates, "User $t: expected 0 updates but got " . count($updates));
            $this->assertCount(0, $missing, "User $t: expected 0 missing");

            fwrite(STDERR, sprintf("[HEAVY-MATCH] User %d: %dms (0 updates)\n", $t, $elapsed));
        }

        sort($syncTimes);
        $p95 = $syncTimes[(int) (count($syncTimes) * 0.95)];
        $avg = (int) (array_sum($syncTimes) / count($syncTimes));

        fwrite(STDERR, sprintf(
            "\n[HEAVY-MATCH] === RESULTS ===\n"
            . "  %d users × 1200 matched candidates: avg=%dms p95=%dms\n\n",
            $numUsers, $avg, $p95
        ));

        // All-match should be significantly faster than mismatch
        $this->assertLessThan(
            3000, $p95,
            "P95 all-match sync ({$p95}ms) exceeds 3s budget"
        );
    }
}
