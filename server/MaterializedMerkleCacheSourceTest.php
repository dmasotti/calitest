<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\MaterializedMerkleService;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class MaterializedMerkleCacheSourceTest extends TestCase
{
    use RefreshDatabase;

    public function test_mysql_refreshing_touched_metadata_cache_uses_books_hash_v2_and_writes_versioned_cache(): void
    {
        if (!in_array(DB::getDriverName(), ['mysql', 'mariadb'], true)) {
            $this->markTestSkipped('MySQL-only cache source check');
        }

        [$user, $library] = $this->makeContext();
        $service = app(MaterializedMerkleService::class);

        $book = UserBook::create([
            'id' => 9691,
            'uuid' => 'aa000000-0000-4000-8000-000000009691',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'MySQL View Refresh',
            'path' => 'mysql-view-refresh',
            'author_sort' => 'Tester, Mysql',
            'last_modified' => Carbon::create(2026, 3, 19, 11, 0, 0, 'UTC'),
        ])->fresh();

        $expectedHash = (string) DB::table('books_hash_v2')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('uuid', $book->uuid)
            ->value('metadata_hash');

        $book->forceFill([
            'metadata_hash_cache' => null,
        ])->saveQuietly();

        DB::flushQueryLog();
        DB::enableQueryLog();

        try {
            $service->refreshMetadataHashCacheForTouchedUuids(
                (int) $user->id,
                (int) $library->id,
                [$book->uuid]
            );
        } finally {
            $queries = DB::getQueryLog();
            DB::disableQueryLog();
        }

        $book->refresh();

        $booksHashQueries = array_values(array_filter($queries, static function (array $entry): bool {
            $sql = strtolower((string) ($entry['query'] ?? ''));
            return str_contains($sql, 'books_hash_v2');
        }));

        $this->assertNotEmpty(
            $booksHashQueries,
            'MySQL refresh path should still read metadata hash from books_hash_v2 until a different strategy is explicitly adopted'
        );
        $this->assertSame(
            'v2:' . $expectedHash . ':' . $book->last_modified->timestamp,
            (string) $book->metadata_hash_cache
        );
    }

    public function test_pgsql_materialized_metadata_rebuild_uses_valid_book_cache_without_books_hash_view(): void
    {
        if (DB::getDriverName() !== 'pgsql') {
            $this->markTestSkipped('PGSQL-only cache source check');
        }

        [$user, $library] = $this->makeContext();
        $service = app(MaterializedMerkleService::class);

        $uuids = [];
        for ($i = 1; $i <= 5; $i++) {
            $book = UserBook::create([
                'id' => 9700 + $i,
                'uuid' => sprintf('aa000000-0000-4000-8000-%012d', $i),
                'user_id' => $user->id,
                'library_id' => $library->id,
                'title' => 'Cache Source ' . $i,
                'path' => 'cache-source-' . $i,
                'author_sort' => 'Tester, Cache',
                'last_modified' => Carbon::create(2026, 3, 11, 13, 0, 0, 'UTC')->addSeconds($i),
            ])->fresh();

            $hash = (string) DB::table('books_hash_v2')
                ->where('user_id', $user->id)
                ->where('library_id', $library->id)
                ->where('uuid', $book->uuid)
                ->value('metadata_hash');

            $book->forceFill([
                'metadata_hash_cache' => 'v2:' . $hash . ':' . $book->last_modified->timestamp,
            ])->saveQuietly();

            $uuids[] = $book->uuid;
        }

        DB::flushQueryLog();
        DB::enableQueryLog();

        try {
            $service->rebuildLibraryDimensionsForTouchedUuids(
                (int) $user->id,
                (int) $library->id,
                ['metadata' => $uuids]
            );
        } finally {
            $queries = DB::getQueryLog();
            DB::disableQueryLog();
        }

        $booksHashQueries = array_values(array_filter($queries, static function (array $entry): bool {
            $sql = strtolower((string) ($entry['query'] ?? ''));
            return str_contains($sql, 'books_hash_v2');
        }));

        $this->assertCount(
            0,
            $booksHashQueries,
            'Materialized metadata rebuild should use valid books.metadata_hash_cache before falling back to books_hash_v2'
        );
    }

    public function test_pgsql_materialized_metadata_rebuild_matches_full_rebuild_with_mixed_cache_hits_and_misses(): void
    {
        if (DB::getDriverName() !== 'pgsql') {
            $this->markTestSkipped('PGSQL-only cache source check');
        }

        [$user, $library] = $this->makeContext();
        $service = app(MaterializedMerkleService::class);

        $uuids = [];
        for ($i = 1; $i <= 5; $i++) {
            $book = UserBook::create([
                'id' => 9800 + $i,
                'uuid' => sprintf('ab000000-0000-4000-8000-%012d', $i),
                'user_id' => $user->id,
                'library_id' => $library->id,
                'title' => 'Mixed Cache ' . $i,
                'path' => 'mixed-cache-' . $i,
                'author_sort' => 'Tester, Mixed',
                'last_modified' => Carbon::create(2026, 3, 11, 14, 0, 0, 'UTC')->addSeconds($i),
            ])->fresh();

            $hash = (string) DB::table('books_hash_v2')
                ->where('user_id', $user->id)
                ->where('library_id', $library->id)
                ->where('uuid', $book->uuid)
                ->value('metadata_hash');

            $cache = 'v2:' . $hash . ':' . $book->last_modified->timestamp;
            if ($i === 3) {
                $cache = 'v2:' . $hash . ':' . ($book->last_modified->timestamp - 1);
            }

            $book->forceFill([
                'metadata_hash_cache' => $cache,
            ])->saveQuietly();

            $uuids[] = $book->uuid;
        }

        $service->rebuildLibraryDimensions(
            (int) $user->id,
            (int) $library->id,
            ['metadata']
        );

        $expectedLeaves = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->orderBy('leaf_id')
            ->get(['leaf_id', 'leaf_hash', 'book_count'])
            ->map(static fn ($row): array => [
                'leaf_id' => (int) $row->leaf_id,
                'leaf_hash' => (string) $row->leaf_hash,
                'book_count' => (int) $row->book_count,
            ])
            ->all();

        DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->delete();
        DB::table('sync_merkle_branches')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->delete();
        DB::table('sync_merkle_roots')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->delete();

        $service->rebuildLibraryDimensionsForTouchedUuids(
            (int) $user->id,
            (int) $library->id,
            ['metadata' => $uuids]
        );

        $actualLeaves = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->orderBy('leaf_id')
            ->get(['leaf_id', 'leaf_hash', 'book_count'])
            ->map(static fn ($row): array => [
                'leaf_id' => (int) $row->leaf_id,
                'leaf_hash' => (string) $row->leaf_hash,
                'book_count' => (int) $row->book_count,
            ])
            ->all();

        $this->assertSame($expectedLeaves, $actualLeaves);
    }

    public function test_pgsql_touched_metadata_rebuild_falls_back_to_books_hash_v2_only_for_touched_uuids(): void
    {
        if (DB::getDriverName() !== 'pgsql') {
            $this->markTestSkipped('PGSQL-only cache source check');
        }

        [$user, $library] = $this->makeContext();
        $service = app(MaterializedMerkleService::class);

        $validBook = UserBook::create([
            'id' => 9901,
            'uuid' => 'aa000000-0000-4000-8000-000000009901',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Valid Cache',
            'path' => 'valid-cache',
            'author_sort' => 'Tester, Valid',
            'last_modified' => Carbon::create(2026, 3, 11, 15, 0, 0, 'UTC'),
        ])->fresh();

        $touchedBook = UserBook::create([
            'id' => 9902,
            'uuid' => 'aa000000-0000-4000-8000-000000009902',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Touched Cache Miss',
            'path' => 'touched-cache-miss',
            'author_sort' => 'Tester, Miss',
            'last_modified' => Carbon::create(2026, 3, 11, 15, 0, 1, 'UTC'),
        ])->fresh();

        $validHash = (string) DB::table('books_hash_v2')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('uuid', $validBook->uuid)
            ->value('metadata_hash');

        $validBook->forceFill([
            'metadata_hash_cache' => 'v2:' . $validHash . ':' . $validBook->last_modified->timestamp,
        ])->saveQuietly();

        $touchedBook->forceFill([
            'metadata_hash_cache' => null,
        ])->saveQuietly();

        DB::flushQueryLog();
        DB::enableQueryLog();

        try {
            $service->rebuildLibraryDimensionsForTouchedUuids(
                (int) $user->id,
                (int) $library->id,
                ['metadata' => [$touchedBook->uuid]]
            );
        } finally {
            $queries = DB::getQueryLog();
            DB::disableQueryLog();
        }

        $booksHashQueries = array_values(array_filter($queries, static function (array $entry): bool {
            $sql = strtolower((string) ($entry['query'] ?? ''));
            return str_contains($sql, 'books_hash_v2');
        }));

        $this->assertCount(1, $booksHashQueries);
        $bindings = array_map(static fn ($value): string => (string) $value, $booksHashQueries[0]['bindings'] ?? []);
        $this->assertContains($touchedBook->uuid, $bindings);
        $this->assertNotContains($validBook->uuid, $bindings);
    }

    public function test_pgsql_refreshing_touched_metadata_cache_after_write_avoids_books_hash_v2_in_rebuild(): void
    {
        if (DB::getDriverName() !== 'pgsql') {
            $this->markTestSkipped('PGSQL-only cache source check');
        }

        [$user, $library] = $this->makeContext();
        $service = app(MaterializedMerkleService::class);

        $book = UserBook::create([
            'id' => 9910,
            'uuid' => 'aa000000-0000-4000-8000-000000009910',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Write-Time Refresh',
            'path' => 'write-time-refresh',
            'author_sort' => 'Tester, Refresh',
            'last_modified' => Carbon::create(2026, 3, 12, 8, 0, 0, 'UTC'),
        ])->fresh();

        $book->forceFill([
            'metadata_hash_cache' => null,
        ])->saveQuietly();

        $service->refreshMetadataHashCacheForTouchedUuids(
            (int) $user->id,
            (int) $library->id,
            [$book->uuid]
        );

        $book->refresh();
        $this->assertMatchesRegularExpression(
            '/^v2:[0-9a-f]{64}:\d+$/',
            (string) $book->metadata_hash_cache
        );

        DB::flushQueryLog();
        DB::enableQueryLog();

        try {
            $service->rebuildLibraryDimensionsForTouchedUuids(
                (int) $user->id,
                (int) $library->id,
                ['metadata' => [$book->uuid]]
            );
        } finally {
            $queries = DB::getQueryLog();
            DB::disableQueryLog();
        }

        $booksHashQueries = array_values(array_filter($queries, static function (array $entry): bool {
            $sql = strtolower((string) ($entry['query'] ?? ''));
            return str_contains($sql, 'books_hash_v2');
        }));

        $this->assertCount(
            0,
            $booksHashQueries,
            'Refreshing metadata_hash_cache for touched UUIDs should keep the rebuild on cache-only source'
        );
    }

    public function test_pgsql_refreshing_touched_metadata_cache_can_run_inside_transaction(): void
    {
        if (DB::getDriverName() !== 'pgsql') {
            $this->markTestSkipped('PGSQL-only cache source check');
        }

        [$user, $library] = $this->makeContext();
        $service = app(MaterializedMerkleService::class);

        $book = UserBook::create([
            'id' => 9911,
            'uuid' => 'aa000000-0000-4000-8000-000000009911',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Write-Time Refresh TX',
            'path' => 'write-time-refresh-tx',
            'author_sort' => 'Tester, RefreshTx',
            'last_modified' => Carbon::create(2026, 3, 12, 8, 0, 1, 'UTC'),
        ])->fresh();

        $book->forceFill([
            'metadata_hash_cache' => null,
        ])->saveQuietly();

        DB::transaction(function () use ($service, $user, $library, $book): void {
            $service->refreshMetadataHashCacheForTouchedUuids(
                (int) $user->id,
                (int) $library->id,
                [$book->uuid]
            );
        });

        $book->refresh();
        $this->assertMatchesRegularExpression(
            '/^v2:[0-9a-f]{64}:\d+$/',
            (string) $book->metadata_hash_cache
        );
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Merkle Cache Source',
        ]);

        return [$user, $library];
    }
}
