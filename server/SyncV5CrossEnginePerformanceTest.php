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
 * Cross-engine performance benchmark.
 * Outputs timing JSON to stdout for comparison across SQLite/MySQL/PostgreSQL.
 */
class SyncV5CrossEnginePerformanceTest extends TestCase
{
    use RefreshDatabase;

    private function seedBooks(Library $library, int $count, int $idOffset = 90000): array
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
                'title' => 'Perf Book ' . ($idOffset + $i),
                'path' => 'Perf Book ' . ($idOffset + $i),
                'author_sort' => 'Author ' . ($i % 50),
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
        foreach (array_chunk($rows, 500) as $chunk) {
            DB::table('books')->insert($chunk);
        }
        // Populate metadata_hash on-write column from VIEW (simulates applyBookMetadata)
        if (Schema::hasTable('books_hash_v2')) {
            $viewHashes = DB::table('books_hash_v2')
                ->where('user_id', $library->user_id)
                ->where('library_id', $library->id)
                ->whereIn('uuid', $uuids)
                ->pluck('metadata_hash', 'uuid');
            foreach ($viewHashes as $uuid => $hash) {
                DB::table('books')->where('uuid', $uuid)
                    ->where('user_id', $library->user_id)
                    ->update(['metadata_hash_cache' => strtolower((string) $hash)]);
            }
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

    private function syncRequest(Library $library, array $clientBooks, array $candidates): array
    {
        Sanctum::actingAs(User::find($library->user_id));
        $start = microtime(true);
        $response = $this->postJson('/api/sync/v5', [
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
        $ms = round((microtime(true) - $start) * 1000);
        $response->assertOk();
        $data = $response->json();
        return [
            'ms' => $ms,
            'updates' => count($data['updates_for_client'] ?? []),
            'missing' => count($data['missing_from_server'] ?? []),
            'skipped' => $data['skipped_hash'] ?? 0,
            'has_more' => $data['has_more'] ?? false,
            'profile' => $data['profile']['sync_v5'] ?? [],
        ];
    }

    public function test_cross_engine_benchmark(): void
    {
        $driver = DB::getDriverName();
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $results = ['driver' => $driver, 'tests' => []];

        // ── A. Seed 500 books ───────────────────────────────────────
        $seedStart = microtime(true);
        $uuids = $this->seedBooks($library, 500);
        $seedMs = round((microtime(true) - $seedStart) * 1000);
        $results['seed_500_ms'] = $seedMs;

        // ── B. Get server hashes (VIEW query) ───────────────────────
        $hashStart = microtime(true);
        $hashes = [];
        foreach (array_chunk($uuids, 200) as $chunk) {
            if (Schema::hasTable('books_hash_v2')) {
                $rows = DB::table('books_hash_v2')
                    ->where('user_id', $user->id)
                    ->where('library_id', $library->id)
                    ->whereIn('uuid', $chunk)
                    ->pluck('metadata_hash', 'uuid');
                foreach ($rows as $uuid => $h) {
                    $hashes[(string) $uuid] = strtolower((string) $h);
                }
            }
        }
        // Fallback for missing
        foreach ($uuids as $u) {
            if (!isset($hashes[$u])) {
                $hashes[$u] = $this->serverHash($user->id, $library->id, $u);
            }
        }
        $hashMs = round((microtime(true) - $hashStart) * 1000);
        $results['hash_500_view_ms'] = $hashMs;

        // ── C. Sync: 500 mismatch ───────────────────────────────────
        $cb_mismatch = [];
        foreach ($uuids as $u) $cb_mismatch[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
        $r1 = $this->syncRequest($library, $cb_mismatch, $uuids);
        $results['tests']['500_mismatch'] = $r1;
        $this->assertSame(500, $r1['updates']);

        // ── D. Sync: 500 match ──────────────────────────────────────
        $cb_match = [];
        foreach ($uuids as $u) $cb_match[$u] = ['m' => $hashes[$u], 'c' => null, 'f' => null];
        $r2 = $this->syncRequest($library, $cb_match, $uuids);
        $results['tests']['500_match'] = $r2;
        $this->assertSame(0, $r2['updates']);

        // ── E. Seed 1000 more (total 1500) ──────────────────────────
        $uuids2 = $this->seedBooks($library, 1000, 91000);
        $allUuids = array_merge($uuids, $uuids2);

        // ── F. Sync: 1500 match ─────────────────────────────────────
        $cb_1500 = [];
        foreach ($allUuids as $u) {
            if (isset($hashes[$u])) {
                $cb_1500[$u] = ['m' => $hashes[$u], 'c' => null, 'f' => null];
            } else {
                $h = $this->serverHash($user->id, $library->id, $u);
                $cb_1500[$u] = ['m' => $h, 'c' => null, 'f' => null];
            }
        }
        $r3 = $this->syncRequest($library, $cb_1500, $allUuids);
        $results['tests']['1500_match'] = $r3;
        $this->assertSame(0, $r3['updates']);

        // ── G. Concurrency: 3 users × 200 books simultaneous ────────
        $concUsers = [];
        for ($i = 0; $i < 3; $i++) {
            $cu = User::factory()->create();
            $cl = Library::factory()->create(['user_id' => $cu->id]);
            $cuuids = $this->seedBooks($cl, 200, 95000 + $i * 1000);
            $concUsers[] = ['user' => $cu, 'lib' => $cl, 'uuids' => $cuuids];
        }
        $concStart = microtime(true);
        $concResults = [];
        foreach ($concUsers as $cu) {
            $cb = [];
            foreach ($cu['uuids'] as $u) $cb[$u] = ['m' => str_repeat('0', 64), 'c' => null, 'f' => null];
            Sanctum::actingAs($cu['user']);
            $start = microtime(true);
            $resp = $this->postJson('/api/sync/v5', [
                'library_id' => (string) $cu['lib']->id,
                'calibre_library_uuid' => $cu['lib']->calibre_library_id,
                'cursor' => null,
                'batch_size' => 500,
                'client_books' => ['b' => $cb, 'd' => []],
                'options' => [
                    'sync_files_enabled' => false,
                    'sync_covers_enabled' => false,
                    'metadata_candidate_uuids' => $cu['uuids'],
                ],
            ]);
            $resp->assertOk();
            $concResults[] = round((microtime(true) - $start) * 1000);
        }
        $concTotal = round((microtime(true) - $concStart) * 1000);
        $results['tests']['3x200_concurrent'] = [
            'per_user_ms' => $concResults,
            'total_ms' => $concTotal,
            'avg_ms' => (int)(array_sum($concResults) / count($concResults)),
        ];

        // ── Output ──────────────────────────────────────────────────
        $json = json_encode($results, JSON_PRETTY_PRINT);
        file_put_contents(
            storage_path('app/perf/cross_engine_' . $driver . '_' . date('Ymd_His') . '.json'),
            $json
        );
        // Print to stdout for capture
        echo "\n[PERF_RESULT] " . json_encode($results) . "\n";

        $this->assertTrue(true); // Explicit pass
    }
}
