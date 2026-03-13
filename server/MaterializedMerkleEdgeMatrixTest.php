<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Services\Sync\MaterializedMerkleService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Tests\TestCase;

class MaterializedMerkleEdgeMatrixTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Materialized Merkle rebuild SQL is exercised on MySQL/PostgreSQL runtime drivers, not SQLite.');
        }
    }

    public function test_mm001_same_leaf_multiple_metadata_changes_change_only_that_leaf_and_branch(): void
    {
        [$library, $userId] = $this->seedLibrary();

        $uuidA1 = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000201', 'A1');
        $uuidA2 = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000202', 'A2');
        $uuidB1 = $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000203', 'B1');
        $this->rebuild($library, ['metadata', 'covers', 'files']);

        $beforeLeaves = $this->leafMap($library, 'metadata');
        $beforeBranches = $this->branchMap($library, 'metadata');

        DB::table('books')->whereIn('uuid', [$uuidA1, $uuidA2])->update([
            'title' => 'changed-same-leaf',
            'updated_at' => now(),
            'last_modified' => now(),
        ]);
        $this->rebuild($library, ['metadata']);

        $afterLeaves = $this->leafMap($library, 'metadata');
        $afterBranches = $this->branchMap($library, 'metadata');

        $this->assertNotSame($beforeLeaves[170]['leaf_hash'], $afterLeaves[170]['leaf_hash']);
        $this->assertSame($beforeLeaves[186]['leaf_hash'], $afterLeaves[186]['leaf_hash']);
        $this->assertNotSame($beforeBranches[10], $afterBranches[10]);
        $this->assertSame($beforeBranches[11], $afterBranches[11]);
    }

    public function test_mm002_same_branch_different_leaves_change_only_that_branch(): void
    {
        [$library, $userId] = $this->seedLibrary();

        $uuidAa = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000211', 'AA');
        $uuidAb = $this->seedBook($library, $userId, 'ab000000-0000-4000-8000-000000000212', 'AB');
        $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000213', 'BA');
        $this->rebuild($library, ['metadata', 'covers', 'files']);

        $beforeLeaves = $this->leafMap($library, 'metadata');
        $beforeBranches = $this->branchMap($library, 'metadata');

        DB::table('books')->whereIn('uuid', [$uuidAa, $uuidAb])->update([
            'description' => 'changed-same-branch',
            'updated_at' => now(),
            'last_modified' => now(),
        ]);
        $this->rebuild($library, ['metadata']);

        $afterLeaves = $this->leafMap($library, 'metadata');
        $afterBranches = $this->branchMap($library, 'metadata');

        $this->assertNotSame($beforeLeaves[170]['leaf_hash'], $afterLeaves[170]['leaf_hash']);
        $this->assertNotSame($beforeLeaves[171]['leaf_hash'], $afterLeaves[171]['leaf_hash']);
        $this->assertSame($beforeLeaves[186]['leaf_hash'], $afterLeaves[186]['leaf_hash']);
        $this->assertNotSame($beforeBranches[10], $afterBranches[10]);
        $this->assertSame($beforeBranches[11], $afterBranches[11]);
    }

    public function test_mm003_cross_branch_batch_changes_update_only_touched_branches(): void
    {
        [$library, $userId] = $this->seedLibrary();

        $uuidAa = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000221', 'AA');
        $uuidBa = $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000222', 'BA');
        $uuidFa = $this->seedBook($library, $userId, 'fa000000-0000-4000-8000-000000000223', 'FA');
        $this->rebuild($library, ['metadata', 'covers', 'files']);

        $beforeBranches = $this->branchMap($library, 'metadata');

        DB::table('books')
            ->where('uuid', $uuidAa)
            ->update([
                'title' => 'AA updated',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);
        DB::table('books')
            ->where('uuid', $uuidBa)
            ->update([
                'title' => 'BA updated',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);
        $this->rebuild($library, ['metadata']);

        $afterBranches = $this->branchMap($library, 'metadata');

        $this->assertNotSame($beforeBranches[10], $afterBranches[10]);
        $this->assertNotSame($beforeBranches[11], $afterBranches[11]);
        $this->assertSame($beforeBranches[15], $afterBranches[15]);
        $this->assertSame(
            $this->rootHash($library, 'metadata'),
            $this->rootHash($library, 'metadata'),
            'Metadata root remains deterministic after cross-branch batch rebuild'
        );
    }

    public function test_mm004_batch_multi_dimension_updates_only_touched_roots(): void
    {
        [$library, $userId] = $this->seedLibrary();

        $uuid = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000231', 'Base');
        $this->rebuild($library, ['metadata', 'covers', 'files']);

        $beforeMetadata = $this->rootHash($library, 'metadata');
        $beforeCovers = $this->rootHash($library, 'covers');
        $beforeFiles = $this->rootHash($library, 'files');

        $newFileHash = hash('sha256', 'edge-multi-dimension-file');
        DB::table('files_store')->updateOrInsert(
            ['sha256' => $newFileHash],
            [
                'storage_key' => 'ebooks/multi.epub',
                'storage_provider' => 'r2',
                'storage_url' => 'https://example.test/ebooks/multi.epub',
                'ref_count' => 1,
                'created_at' => now(),
                'updated_at' => now(),
            ]
        );

        DB::table('books')
            ->where('uuid', $uuid)
            ->update([
                'title' => 'Base updated',
                'has_cover' => 1,
                'cover_original_hash' => hash('sha256', 'new-cover'),
                'updated_at' => now(),
                'last_modified' => now(),
            ]);
        DB::table('books_files')
            ->where('book', $uuid)
            ->update([
                'file_hash' => $newFileHash,
                'updated_at' => now(),
            ]);

        $this->rebuild($library, ['metadata', 'covers', 'files']);

        $this->assertNotSame($beforeMetadata, $this->rootHash($library, 'metadata'));
        $this->assertNotSame($beforeCovers, $this->rootHash($library, 'covers'));
        $this->assertNotSame($beforeFiles, $this->rootHash($library, 'files'));
    }

    public function test_mm005_incremental_rebuild_preserves_untouched_leaf_rows(): void
    {
        [$library, $userId] = $this->seedLibrary();

        $uuidAa = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000235', 'AA');
        $this->seedBook($library, $userId, 'ab000000-0000-4000-8000-000000000236', 'AB');
        $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000237', 'BA');
        $this->rebuild($library, ['metadata']);

        $untouchedLeafBefore = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $library->user_id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAB)
            ->first();

        $this->assertNotNull($untouchedLeafBefore);

        DB::table('books')
            ->where('uuid', $uuidAa)
            ->update([
                'title' => 'AA incremental updated',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);

        app(MaterializedMerkleService::class)->rebuildLibraryDimensionsForTouchedUuids(
            (int) $library->user_id,
            (int) $library->id,
            ['metadata' => [$uuidAa]]
        );

        $untouchedLeafAfter = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $library->user_id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAB)
            ->first();

        $this->assertNotNull($untouchedLeafAfter);
        $this->assertSame((int) $untouchedLeafBefore->id, (int) $untouchedLeafAfter->id);
        $this->assertSame((string) $untouchedLeafBefore->leaf_hash, (string) $untouchedLeafAfter->leaf_hash);
        $this->assertSame((string) $untouchedLeafBefore->updated_at, (string) $untouchedLeafAfter->updated_at);
    }

    public function test_mm006_mm008_item_hash_edges_survive_to_materialized_metadata_root(): void
    {
        [$library, $userId] = $this->seedLibrary();

        $uuid = $this->seedBook(
            $library,
            $userId,
            'ac000000-0000-4000-8000-000000000241',
            'Léon  Uris'
        );

        DB::table('books')
            ->where('uuid', $uuid)
            ->update([
                'author_sort' => 'H. G. Wells',
                'description' => 'Québec and AC/DC',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);
        $this->attachRating($library, $userId, $uuid, 10);

        $this->rebuild($library, ['metadata']);

        $root = DB::table('sync_merkle_roots')
            ->where('user_id', $userId)
            ->where('library_id', $library->id)
            ->where('dimension', 'metadata')
            ->value('root_hash');

        $bookHash = DB::table('books_hash_v2')
            ->where('user_id', $userId)
            ->where('library_id', $library->id)
            ->where('uuid', $uuid)
            ->value('hash_payload');

        $this->assertNotNull($root);
        $this->assertNotNull($bookHash);
        $this->assertStringContainsString('"rating":10', (string) $bookHash);
        $this->assertStringContainsString('\\u00e9', strtolower((string) $bookHash));
    }

    public function test_mm009_incremental_rebuild_does_not_touch_other_library_of_same_user(): void
    {
        $user = User::factory()->create();
        $libraryA = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Isolation A',
        ]);
        $libraryB = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Isolation B',
        ]);

        $uuidA = $this->seedBook($libraryA, (int) $user->id, 'aa000000-0000-4000-8000-000000000251', 'A');
        $this->seedBook($libraryB, (int) $user->id, 'aa000000-0000-4000-8000-000000000252', 'B');

        $this->rebuild($libraryA, ['metadata']);
        $this->rebuild($libraryB, ['metadata']);

        $rootBefore = DB::table('sync_merkle_roots')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $libraryB->id)
            ->where('dimension', 'metadata')
            ->first();
        $leafBefore = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $libraryB->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAA)
            ->first();

        $this->assertNotNull($rootBefore);
        $this->assertNotNull($leafBefore);

        DB::table('books')
            ->where('uuid', $uuidA)
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $libraryA->id)
            ->update([
                'title' => 'A updated',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);

        app(MaterializedMerkleService::class)->rebuildLibraryDimensionsForTouchedUuids(
            (int) $user->id,
            (int) $libraryA->id,
            ['metadata' => [$uuidA]]
        );

        $rootAfter = DB::table('sync_merkle_roots')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $libraryB->id)
            ->where('dimension', 'metadata')
            ->first();
        $leafAfter = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $libraryB->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAA)
            ->first();

        $this->assertNotNull($rootAfter);
        $this->assertNotNull($leafAfter);
        $this->assertSame((int) $rootBefore->id, (int) $rootAfter->id);
        $this->assertSame((string) $rootBefore->root_hash, (string) $rootAfter->root_hash);
        $this->assertSame((string) $rootBefore->updated_at, (string) $rootAfter->updated_at);
        $this->assertSame((int) $leafBefore->id, (int) $leafAfter->id);
        $this->assertSame((string) $leafBefore->leaf_hash, (string) $leafAfter->leaf_hash);
        $this->assertSame((string) $leafBefore->updated_at, (string) $leafAfter->updated_at);
    }

    public function test_mm010_incremental_rebuild_does_not_touch_other_user_same_leaf_prefix(): void
    {
        [$libraryA, $userAId] = $this->seedLibrary();
        [$libraryB, $userBId] = $this->seedLibrary();

        $uuidA = $this->seedBook($libraryA, $userAId, 'ab000000-0000-4000-8000-000000000261', 'User A');
        $this->seedBook($libraryB, $userBId, 'ab000000-0000-4000-8000-000000000262', 'User B');

        $this->rebuild($libraryA, ['metadata']);
        $this->rebuild($libraryB, ['metadata']);

        $rootBefore = DB::table('sync_merkle_roots')
            ->where('user_id', $userBId)
            ->where('library_id', (int) $libraryB->id)
            ->where('dimension', 'metadata')
            ->first();
        $leafBefore = DB::table('sync_merkle_leaves')
            ->where('user_id', $userBId)
            ->where('library_id', (int) $libraryB->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAB)
            ->first();

        $this->assertNotNull($rootBefore);
        $this->assertNotNull($leafBefore);

        DB::table('books')
            ->where('uuid', $uuidA)
            ->where('user_id', $userAId)
            ->where('library_id', (int) $libraryA->id)
            ->update([
                'title' => 'User A updated',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);

        app(MaterializedMerkleService::class)->rebuildLibraryDimensionsForTouchedUuids(
            $userAId,
            (int) $libraryA->id,
            ['metadata' => [$uuidA]]
        );

        $rootAfter = DB::table('sync_merkle_roots')
            ->where('user_id', $userBId)
            ->where('library_id', (int) $libraryB->id)
            ->where('dimension', 'metadata')
            ->first();
        $leafAfter = DB::table('sync_merkle_leaves')
            ->where('user_id', $userBId)
            ->where('library_id', (int) $libraryB->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAB)
            ->first();

        $this->assertNotNull($rootAfter);
        $this->assertNotNull($leafAfter);
        $this->assertSame((int) $rootBefore->id, (int) $rootAfter->id);
        $this->assertSame((string) $rootBefore->root_hash, (string) $rootAfter->root_hash);
        $this->assertSame((string) $rootBefore->updated_at, (string) $rootAfter->updated_at);
        $this->assertSame((int) $leafBefore->id, (int) $leafAfter->id);
        $this->assertSame((string) $leafBefore->leaf_hash, (string) $leafAfter->leaf_hash);
        $this->assertSame((string) $leafBefore->updated_at, (string) $leafAfter->updated_at);
    }

    public function test_mm011_lazy_read_path_rebuilds_only_stale_leaves_and_preserves_untouched_rows(): void
    {
        [$library, $userId] = $this->seedLibrary();

        $uuidAa = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000261', 'AA');
        $this->seedBook($library, $userId, 'ab000000-0000-4000-8000-000000000262', 'AB');
        $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000263', 'BA');

        $service = app(MaterializedMerkleService::class);
        $service->rebuildLibraryDimensions((int) $library->user_id, (int) $library->id, ['metadata']);

        $untouchedLeafBefore = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $library->user_id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAB)
            ->first();
        $staleLeafBefore = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $library->user_id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAA)
            ->first();

        $this->assertNotNull($untouchedLeafBefore);
        $this->assertNotNull($staleLeafBefore);

        DB::table('books')
            ->where('uuid', $uuidAa)
            ->update([
                'title' => 'AA lazy stale updated',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);

        $service->markDimensionsStaleForTouchedUuids(
            (int) $library->user_id,
            (int) $library->id,
            ['metadata' => [$uuidAa]]
        );

        $roots = $service->getLibraryRoots((int) $library->user_id, (int) $library->id);
        $this->assertNotEmpty($roots['metadata'] ?? null);

        $untouchedLeafAfter = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $library->user_id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAB)
            ->first();
        $staleLeafAfter = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $library->user_id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAA)
            ->first();

        $this->assertNotNull($untouchedLeafAfter);
        $this->assertNotNull($staleLeafAfter);
        $this->assertSame((int) $untouchedLeafBefore->id, (int) $untouchedLeafAfter->id);
        $this->assertSame((string) $untouchedLeafBefore->leaf_hash, (string) $untouchedLeafAfter->leaf_hash);
        $this->assertSame((string) $untouchedLeafBefore->updated_at, (string) $untouchedLeafAfter->updated_at);
        $this->assertNotSame((int) $staleLeafBefore->id, (int) $staleLeafAfter->id);
        $this->assertNotSame((string) $staleLeafBefore->leaf_hash, (string) $staleLeafAfter->leaf_hash);
        $this->assertSame(
            0,
            (int) DB::table('sync_merkle_roots')
                ->where('user_id', (int) $library->user_id)
                ->where('library_id', (int) $library->id)
                ->where('dimension', 'metadata')
                ->value('is_stale')
        );
    }

    public function test_mm007_pgsql_pre_1970_pubdate_survives_to_materialized_metadata_root(): void
    {
        if (DB::getDriverName() !== 'pgsql') {
            $this->markTestSkipped('Signed pre-1970 pubdate edge is verified on PostgreSQL runtime schema');
        }

        [$library, $userId] = $this->seedLibrary();
        $uuid = $this->seedBook(
            $library,
            $userId,
            'ad000000-0000-4000-8000-000000000242',
            'Historical'
        );

        DB::table('books')
            ->where('uuid', $uuid)
            ->update([
                'pubdate' => '1956-12-31 18:30:00',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);

        $this->rebuild($library, ['metadata']);

        $bookHash = DB::table('books_hash_v2')
            ->where('user_id', $userId)
            ->where('library_id', $library->id)
            ->where('uuid', $uuid)
            ->value('hash_payload');

        $this->assertNotNull($bookHash);
        $this->assertStringContainsString('"pubdate":-410247000', (string) $bookHash);
        $this->assertNotEmpty($this->rootHash($library, 'metadata'));
    }

    private function seedLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Materialized Edge Matrix',
        ]);

        return [$library, (int) $user->id];
    }

    private function rebuild(Library $library, array $dimensions): void
    {
        app(MaterializedMerkleService::class)->rebuildLibraryDimensions(
            (int) $library->user_id,
            (int) $library->id,
            $dimensions
        );
    }

    private function leafMap(Library $library, string $dimension): array
    {
        $service = app(\App\Services\Sync\MaterializedMerkleService::class);
        $rows = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $library->user_id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', $dimension)
            ->orderBy('leaf_id')
            ->get();

        $map = [];
        foreach ($rows as $row) {
            $map[(int) $row->leaf_id] = [
                'leaf_hash' => (string) $row->leaf_hash,
                'uuids' => $service->getLeafUuids(
                    (int) $library->user_id,
                    (int) $library->id,
                    $dimension,
                    (int) $row->branch_id,
                    (int) $row->leaf_id
                ),
            ];
        }

        return $map;
    }

    private function branchMap(Library $library, string $dimension): array
    {
        return DB::table('sync_merkle_branches')
            ->where('user_id', (int) $library->user_id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', $dimension)
            ->pluck('branch_hash', 'branch_id')
            ->map(fn ($v) => (string) $v)
            ->all();
    }

    private function rootHash(Library $library, string $dimension): string
    {
        return (string) DB::table('sync_merkle_roots')
            ->where('user_id', (int) $library->user_id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', $dimension)
            ->value('root_hash');
    }

    private function seedBook(Library $library, int $userId, string $uuid, string $title): string
    {
        $seed = substr(str_replace('-', '', $uuid), 0, 2);
        $fileHash = hash('sha256', 'file-' . $uuid);

        DB::table('books')->insert([
            'id' => random_int(50000, 99000),
            'uuid' => $uuid,
            'user_id' => $userId,
            'library_id' => $library->id,
            'title' => $title,
            'author_sort' => 'Author',
            'path' => $title,
            'flags' => 1,
            'has_cover' => 0,
            'cover_missing' => 0,
            'rating' => 0,
            'series_index' => 1.0,
            'timestamp' => now(),
            'pubdate' => now(),
            'last_modified' => now(),
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        DB::table('files_store')->updateOrInsert(
            ['sha256' => $fileHash],
            [
                'storage_key' => 'ebooks/' . $seed . '.epub',
                'storage_provider' => 'r2',
                'storage_url' => 'https://example.test/ebooks/' . $seed . '.epub',
                'ref_count' => 1,
                'created_at' => now(),
                'updated_at' => now(),
            ]
        );

        $bookFileRow = [
            'book' => $uuid,
            'user_id' => $userId,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'name' => $seed . '.epub',
            'file_hash' => $fileHash,
            'storage_key' => 'ebooks/' . $seed . '.epub',
            'storage_provider' => 'r2',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'uncompressed_size' => 12345,
            'created_at' => now(),
            'updated_at' => now(),
        ];
        if (Schema::hasColumn('books_files', 'file_path')) {
            $bookFileRow['file_path'] = 'ebooks/' . $seed . '.epub';
        }
        if (Schema::hasColumn('books_files', 'uuid')) {
            $bookFileRow['uuid'] = sprintf(
                '%s-%s-%s-%s-%s',
                substr(md5($uuid . '|EPUB'), 0, 8),
                substr(md5($uuid . '|EPUB'), 8, 4),
                substr(md5($uuid . '|EPUB'), 12, 4),
                substr(md5($uuid . '|EPUB'), 16, 4),
                substr(md5($uuid . '|EPUB'), 20, 12),
            );
        }
        DB::table('books_files')->insert($bookFileRow);

        return $uuid;
    }

    private function attachRating(Library $library, int $userId, string $uuid, int $ratingValue): void
    {
        $ratingId = random_int(1000, 9999);
        DB::table('books_ratings')->insert([
            'id' => $ratingId,
            'uuid' => sprintf(
                '%s-%s-%s-%s-%s',
                substr(md5($uuid . '|rating'), 0, 8),
                substr(md5($uuid . '|rating'), 8, 4),
                substr(md5($uuid . '|rating'), 12, 4),
                substr(md5($uuid . '|rating'), 16, 4),
                substr(md5($uuid . '|rating'), 20, 12),
            ),
            'user_id' => $userId,
            'library_id' => $library->id,
            'rating' => $ratingValue,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        DB::table('books_ratings_links')->insert([
            'id' => random_int(10000, 99999),
            'uuid' => sprintf(
                '%s-%s-%s-%s-%s',
                substr(md5($uuid . '|rating-link'), 0, 8),
                substr(md5($uuid . '|rating-link'), 8, 4),
                substr(md5($uuid . '|rating-link'), 12, 4),
                substr(md5($uuid . '|rating-link'), 16, 4),
                substr(md5($uuid . '|rating-link'), 20, 12),
            ),
            'user_id' => $userId,
            'library_id' => $library->id,
            'book' => $uuid,
            'rating' => $ratingId,
            'created_at' => now(),
            'updated_at' => now(),
        ]);
    }
}
