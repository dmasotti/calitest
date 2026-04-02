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
        $this->markTestSkipped('metadata_hash_cache column deprecated — VIEW is only source of truth');
    }

    public function test_pgsql_materialized_metadata_rebuild_uses_valid_book_cache_without_books_hash_view(): void
    {
        $this->markTestSkipped('metadata_hash_cache column deprecated — VIEW is only source of truth');
    }

    public function test_pgsql_materialized_metadata_rebuild_matches_full_rebuild_with_mixed_cache_hits_and_misses(): void
    {
        $this->markTestSkipped('metadata_hash_cache column deprecated — VIEW is only source of truth');
    }

    public function test_pgsql_touched_metadata_rebuild_falls_back_to_books_hash_v2_only_for_touched_uuids(): void
    {
        $this->markTestSkipped('metadata_hash_cache column deprecated — VIEW is only source of truth');
    }

    public function test_pgsql_refreshing_touched_metadata_cache_after_write_avoids_books_hash_v2_in_rebuild(): void
    {
        $this->markTestSkipped('metadata_hash_cache column deprecated — VIEW is only source of truth');
    }

    public function test_pgsql_refreshing_touched_metadata_cache_can_run_inside_transaction(): void
    {
        $this->markTestSkipped('metadata_hash_cache column deprecated — VIEW is only source of truth');
    }

    public function test_mysql_full_metadata_rebuild_handles_large_single_leaf_without_group_concat_truncation(): void
    {
        if (!in_array(DB::getDriverName(), ['mysql', 'mariadb'], true)) {
            $this->markTestSkipped('MySQL-only GROUP_CONCAT guardrail');
        }

        [$user, $library] = $this->makeContext();
        $service = app(MaterializedMerkleService::class);

        for ($i = 1; $i <= 20; $i++) {
            UserBook::create([
                'id' => 11000 + $i,
                'uuid' => sprintf('aa000000-0000-4000-8000-%012d', $i),
                'user_id' => $user->id,
                'library_id' => $library->id,
                'title' => 'Large Leaf ' . $i,
                'path' => 'large-leaf-' . $i,
                'author_sort' => 'Tester, LargeLeaf ' . $i,
                'description' => str_repeat('metadata-leaf-', 32) . $i,
                'last_modified' => Carbon::create(2026, 3, 19, 12, 0, 0, 'UTC')->addSeconds($i),
            ]);
        }

        $service->rebuildLibraryDimensions((int) $user->id, (int) $library->id, ['metadata']);

        $leaf = DB::table('sync_merkle_leaves')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 170)
            ->first(['leaf_hash', 'book_count']);

        $root = DB::table('sync_merkle_roots')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $library->id)
            ->where('dimension', 'metadata')
            ->value('root_hash');

        $this->assertNotNull($leaf, 'Metadata rebuild should materialize the overloaded MySQL leaf instead of failing on GROUP_CONCAT truncation');
        $this->assertSame(20, (int) $leaf->book_count);
        $this->assertMatchesRegularExpression('/^[0-9a-f]{64}$/', (string) $leaf->leaf_hash);
        $this->assertMatchesRegularExpression('/^[0-9a-f]{64}$/', (string) $root);
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
