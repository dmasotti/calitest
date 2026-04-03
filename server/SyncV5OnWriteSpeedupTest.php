<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Services\Sync\MetadataHasher;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

/**
 * A/B test: measure sync speed WITH vs WITHOUT on-write metadata_hash column.
 */
class SyncV5OnWriteSpeedupTest extends TestCase
{
    use RefreshDatabase;

    public function test_onwrite_column_speedup(): void
    {
        $driver = DB::getDriverName();
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);
        $now = now()->toDateTimeString();

        // Seed 500 books
        $uuids = [];
        for ($i = 0; $i < 500; $i++) {
            $uuid = (string) Str::uuid();
            $uuids[] = $uuid;
            DB::table('books')->insert([
                'id' => 90000 + $i, 'uuid' => $uuid, 'user_id' => $user->id,
                'library_id' => (string) $lib->id, 'title' => 'Book ' . $i,
                'path' => 'b' . $i, 'author_sort' => 'A' . $i,
                'series_index' => 1.0, 'pubdate' => '2020-01-01',
                'last_modified' => $now, 'has_cover' => false,
                'created_at' => $now, 'updated_at' => $now,
            ]);
        }

        // Get hashes from VIEW
        $hashes = [];
        if (Schema::hasTable('books_hash_v2')) {
            $rows = DB::table('books_hash_v2')
                ->where('user_id', $user->id)
                ->where('library_id', $lib->id)
                ->whereIn('uuid', $uuids)
                ->pluck('metadata_hash', 'uuid');
            foreach ($rows as $u => $h) {
                $hashes[(string) $u] = strtolower((string) $h);
            }
        }
        // Fallback
        foreach ($uuids as $u) {
            if (!isset($hashes[$u])) {
                $hashes[$u] = (string) MetadataHasher::computeHash([
                    'uuid' => $u, 'title' => 'Book', 'authors' => [],
                    'series' => null, 'series_index' => 1.0, 'tags' => [],
                    'identifiers' => [], 'publisher' => null, 'languages' => [],
                    'pubdate' => '2020-01-01', 'description' => null, 'rating' => null,
                ]);
            }
        }

        // Client books: all match
        $cb = [];
        foreach ($uuids as $u) {
            $cb[$u] = ['m' => $hashes[$u], 'c' => null, 'f' => null];
        }
        $body = [
            'library_id' => (string) $lib->id,
            'calibre_library_uuid' => $lib->calibre_library_id,
            'cursor' => null,
            'batch_size' => 1000,
            'client_books' => ['b' => $cb, 'd' => []],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => $uuids,
            ],
        ];

        // ── A: WITHOUT on-write column (NULL) → VIEW fallback ───────
        DB::table('books')
            ->where('user_id', $user->id)
            ->where('library_id', $lib->id)
            ->update(['metadata_hash_cache' => null]);

        $timesA = [];
        for ($i = 0; $i < 3; $i++) {
            $start = microtime(true);
            $this->postJson('/api/sync/v5', $body)->assertOk();
            $timesA[] = round((microtime(true) - $start) * 1000);
        }

        // ── B: WITH on-write column (populated) → direct read ───────
        foreach ($hashes as $uuid => $hash) {
            DB::table('books')
                ->where('uuid', $uuid)
                ->where('user_id', $user->id)
                ->update(['metadata_hash_cache' => $hash]);
        }

        $timesB = [];
        for ($i = 0; $i < 3; $i++) {
            $start = microtime(true);
            $this->postJson('/api/sync/v5', $body)->assertOk();
            $timesB[] = round((microtime(true) - $start) * 1000);
        }

        $avgA = (int) (array_sum($timesA) / count($timesA));
        $avgB = (int) (array_sum($timesB) / count($timesB));
        $speedup = $avgA > 0 ? round($avgA / max($avgB, 1), 1) : 0;

        $result = [
            'driver' => $driver,
            'books' => 500,
            'without_column_ms' => $timesA,
            'with_column_ms' => $timesB,
            'avg_without' => $avgA,
            'avg_with' => $avgB,
            'speedup' => $speedup,
        ];

        $json = json_encode($result, JSON_PRETTY_PRINT);
        @mkdir(storage_path('app/perf'), 0775, true);
        file_put_contents(
            storage_path('app/perf/onwrite_speedup_' . $driver . '_' . date('Ymd_His') . '.json'),
            $json
        );

        // Must pass
        $this->assertGreaterThanOrEqual(1.0, $speedup,
            "On-write column should not be slower. Driver={$driver} avg_without={$avgA}ms avg_with={$avgB}ms");
    }
}
