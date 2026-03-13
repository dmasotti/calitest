<?php

namespace Tests\Server;

use App\Services\Sync\MaterializedMerkleService;
use App\Models\Library;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncV5PreflightAndMerkleDrilldownTodoTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Sync v5 preflight and materialized Merkle drill-down are validated on MySQL/PostgreSQL.');
        }
    }

    private function actingUserWithLibrary(): Library
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Merkle Drilldown TODO',
        ]);
        Sanctum::actingAs($user);

        return $library;
    }

    public function test_unified_preflight_library_hash_returns_only_dimension_roots(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);

        $response->assertOk();
        $response->assertJsonStructure([
            'library_metadata_hash',
            'library_covers_hash',
            'library_files_hash',
            'total_books',
            'last_modified',
        ]);
        $response->assertJsonMissingPath('library_hash');
        $response->assertJsonMissingPath('root_hash');
        $response->assertJsonMissingPath('metadata_merkle_root');
        $response->assertJsonMissingPath('covers_merkle_root');
        $response->assertJsonMissingPath('files_merkle_root');
    }

    public function test_unified_preflight_uses_library_metadata_hash_as_single_metadata_root(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);
        $response->assertOk();
        $response->assertJsonMissingPath('root_hash');
        $response->assertJsonMissingPath('metadata_merkle_root');
        $this->assertNotNull($response->json('library_metadata_hash'));
    }

    public function test_unified_preflight_accepts_calibre_library_uuid(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/library-hash?calibre_library_uuid=' . $library->calibre_library_id);

        $response->assertOk();
        $response->assertJsonStructure([
            'library_metadata_hash',
            'library_covers_hash',
            'library_files_hash',
        ]);
    }

    public function test_unified_preflight_accepts_uuid_passed_in_library_id_for_client_bug_compatibility(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->calibre_library_id);

        $response->assertOk();
        $response->assertJsonStructure([
            'library_metadata_hash',
            'library_covers_hash',
            'library_files_hash',
        ]);
    }

    public function test_merkle_branches_requires_authentication(): void
    {
        $library = Library::factory()->create();

        $response = $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata');

        $response->assertStatus(401);
    }

    public function test_merkle_leaves_requires_authentication(): void
    {
        $library = Library::factory()->create();

        $response = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=0');

        $response->assertStatus(401);
    }

    public function test_merkle_branches_requires_library_identifier(): void
    {
        $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/merkle/branches?dimension=metadata');

        $response->assertStatus(400)
            ->assertJson(['error' => 'library_id or calibre_library_uuid required']);
    }

    public function test_merkle_leaves_requires_branch_id(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata');

        $response->assertStatus(400)
            ->assertJson(['error' => 'branch_id required']);
    }

    public function test_merkle_endpoints_validate_dimension_metadata_only(): void
    {
        $library = $this->actingUserWithLibrary();

        $branches = $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=invalid');
        $branches->assertStatus(422)
            ->assertJsonValidationErrors(['dimension']);

        $leaves = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=invalid&branch_id=0');
        $leaves->assertStatus(422)
            ->assertJsonValidationErrors(['dimension']);
    }

    public function test_merkle_leaves_rejects_negative_branch_id(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=-1');

        $response->assertStatus(422)
            ->assertJsonValidationErrors(['branch_id']);
    }

    public function test_merkle_metadata_branches_endpoint_contract_exists(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata');

        $response->assertOk();
        $response->assertJsonStructure([
            'branch_count',
            'dimension',
            'branches' => [
                '*' => ['branch_id', 'branch_hash'],
            ],
        ]);
        $response->assertJsonMissingPath('root_hash');
    }

    public function test_merkle_metadata_leaves_endpoint_contract_exists(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=0');

        $response->assertOk();
        $response->assertJsonStructure([
            'branch_id',
            'leaf_count',
            'dimension',
            'leaves' => [
                '*' => ['leaf_id', 'leaf_hash', 'uuids'],
            ],
        ]);
    }

    public function test_merkle_metadata_leaves_response_is_consistent_with_requested_branch(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=7');

        $response->assertOk()
            ->assertJsonPath('branch_id', 7)
            ->assertJsonPath('dimension', 'metadata');
    }

    public function test_merkle_branches_empty_library_returns_zero_branches(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata');

        $response->assertOk()
            ->assertJsonPath('branch_count', 0)
            ->assertJsonPath('branches', []);
    }

    public function test_merkle_leaves_unknown_branch_returns_empty_list(): void
    {
        $library = $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=15');

        $response->assertOk()
            ->assertJsonPath('branch_id', 15)
            ->assertJsonPath('leaf_count', 0)
            ->assertJsonPath('leaves', []);
    }

    public function test_preflight_metadata_hash_matches_merkle_root_endpoint_for_same_library(): void
    {
        $library = $this->actingUserWithLibrary();

        $preflight = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);
        $preflight->assertOk();
        $rootEndpoint = $this->getJson('/api/sync/v5/merkle-root?library_id=' . $library->id);
        $rootEndpoint->assertOk();

        $this->assertSame(
            $preflight->json('library_metadata_hash'),
            $rootEndpoint->json('root_hash'),
            'Preflight library_metadata_hash and merkle-root endpoint must be aligned'
        );
    }

    public function test_runtime_merkle_views_exist_and_aggregate_metadata_deterministically(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;

        $bookAa = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000201', 'A1');
        $bookAb = $this->seedBook($library, $userId, 'ab000000-0000-4000-8000-000000000202', 'A2');
        $bookBa = $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000203', 'B1');

        $leaves = DB::table('merkle_leaves')
            ->where('user_id', $userId)
            ->where('library_id', $library->id)
            ->orderBy('leaf_id')
            ->get();

        $this->assertCount(3, $leaves, 'merkle_leaves must expose one row per UUID-prefix leaf');
        $this->assertSame([170, 171, 186], $leaves->pluck('leaf_id')->map(fn ($v) => (int) $v)->all());
        $this->assertSame([10, 10, 11], $leaves->pluck('branch_id')->map(fn ($v) => (int) $v)->all());

        $service = app(\App\Services\Sync\MaterializedMerkleService::class);
        $leafMap = [];
        foreach ($leaves as $leaf) {
            $leafMap[(int) $leaf->leaf_id] = $service->getLeafUuids(
                $userId,
                (int) $library->id,
                'metadata',
                (int) $leaf->branch_id,
                (int) $leaf->leaf_id
            );
        }
        $this->assertSame([$bookAa], $leafMap[170]);
        $this->assertSame([$bookAb], $leafMap[171]);
        $this->assertSame([$bookBa], $leafMap[186]);

        $branches = DB::table('merkle_branches')
            ->where('user_id', $userId)
            ->where('library_id', $library->id)
            ->orderBy('branch_id')
            ->get();

        $this->assertCount(2, $branches, 'merkle_branches must aggregate leaf rows by stable branch id');
        $this->assertSame([10, 11], $branches->pluck('branch_id')->map(fn ($v) => (int) $v)->all());
        $this->assertSame([2, 1], $branches->pluck('book_count')->map(fn ($v) => (int) $v)->all());

        $root = DB::table('merkle_root')
            ->where('user_id', $userId)
            ->where('library_id', $library->id)
            ->first();

        $this->assertNotNull($root, 'merkle_root must expose one aggregated row per library');
        $this->assertSame(3, (int) $root->total_books);

        $preflight = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);
        $preflight->assertOk();
        $this->assertSame($root->root_hash, $preflight->json('library_metadata_hash'));
    }

    public function test_merkle_endpoints_are_isolated_by_user_and_library(): void
    {
        // User A + library A
        $libraryA = $this->actingUserWithLibrary();
        $userA = (int) $libraryA->user_id;
        $bookA = $this->seedBook($libraryA, $userA, 'ac000000-0000-4000-8000-000000000001', 'Book A');

        // User B + library B
        $userBModel = User::factory()->create();
        $libraryB = Library::factory()->create(['user_id' => $userBModel->id]);
        $bookB = $this->seedBook($libraryB, (int) $userBModel->id, 'ad000000-0000-4000-8000-000000000002', 'Book B');

        // As user A we must never see UUIDs from user B library.
        Sanctum::actingAs(User::query()->findOrFail($userA));
        $leavesA = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $libraryA->id . '&dimension=metadata&branch_id=10');
        $leavesA->assertOk();
        $allUuidsA = [];
        foreach (($leavesA->json('leaves') ?? []) as $leaf) {
            foreach (($leaf['uuids'] ?? []) as $u) {
                $allUuidsA[] = $u;
            }
        }
        $this->assertNotContains($bookB, $allUuidsA);
        if (!empty($allUuidsA)) {
            $this->assertContains($bookA, $allUuidsA);
        }
    }

    public function test_merkle_drilldown_flow_identifies_only_changed_leaf_uuid_candidates(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;

        $bookAa = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000001', 'Book AA');
        $bookAb = $this->seedBook($library, $userId, 'ab000000-0000-4000-8000-000000000002', 'Book AB');
        $bookBa = $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000003', 'Book BA');

        $branchesBefore = $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata');
        $branchesBefore->assertOk();
        $branchMapBefore = $this->toBranchMap($branchesBefore->json('branches') ?? []);

        $leavesA_before = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=10');
        $leavesA_before->assertOk();
        $leafMapBefore = $this->toLeafMap($leavesA_before->json('leaves') ?? []);

        // Mutate only AB metadata (same branch as AA, different leaf).
        DB::table('books')
            ->where('uuid', $bookAb)
            ->where('library_id', $library->id)
            ->where('user_id', $userId)
            ->update([
                'title' => 'Book AB updated',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);
        $this->rebuildMerkle($library, ['metadata']);

        $branchesAfter = $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata');
        $branchesAfter->assertOk();
        $branchMapAfter = $this->toBranchMap($branchesAfter->json('branches') ?? []);

        $this->assertArrayHasKey(10, $branchMapBefore);
        $this->assertArrayHasKey(10, $branchMapAfter);
        $this->assertNotSame($branchMapBefore[10], $branchMapAfter[10], 'Branch "a" must change after AB metadata update');

        // Branch "b" contains only BA and must remain stable.
        $this->assertArrayHasKey(11, $branchMapBefore);
        $this->assertArrayHasKey(11, $branchMapAfter);
        $this->assertSame($branchMapBefore[11], $branchMapAfter[11], 'Branch "b" must not change');

        $leavesA_after = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=10');
        $leavesA_after->assertOk();
        $leafMapAfter = $this->toLeafMap($leavesA_after->json('leaves') ?? []);

        $this->assertArrayHasKey(170, $leafMapBefore); // aa
        $this->assertArrayHasKey(171, $leafMapBefore); // ab
        $this->assertArrayHasKey(170, $leafMapAfter);
        $this->assertArrayHasKey(171, $leafMapAfter);

        // Only AB leaf must differ.
        $this->assertSame($leafMapBefore[170]['leaf_hash'], $leafMapAfter[170]['leaf_hash']);
        $this->assertNotSame($leafMapBefore[171]['leaf_hash'], $leafMapAfter[171]['leaf_hash']);
        $this->assertEquals([$bookAb], $leafMapAfter[171]['uuids']);
        $this->assertEquals([$bookAa], $leafMapAfter[170]['uuids']);
        $this->assertEquals([$bookBa], $this->toLeafMap(
            $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=11')
                ->assertOk()
                ->json('leaves') ?? []
        )[186]['uuids']); // ba
    }

    public function test_merkle_drilldown_core_change_in_branch_b_does_not_change_branch_a(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;

        $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000011', 'A1');
        $this->seedBook($library, $userId, 'ab000000-0000-4000-8000-000000000012', 'A2');
        $bookBa = $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000013', 'B1');

        $before = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        DB::table('books')
            ->where('uuid', $bookBa)
            ->where('library_id', $library->id)
            ->where('user_id', $userId)
            ->update([
                'title' => 'B1 updated',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);
        $this->rebuildMerkle($library, ['metadata']);

        $after = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        $this->assertArrayHasKey(10, $before);
        $this->assertArrayHasKey(10, $after);
        $this->assertArrayHasKey(11, $before);
        $this->assertArrayHasKey(11, $after);
        $this->assertSame($before[10], $after[10], 'Branch A must remain unchanged');
        $this->assertNotSame($before[11], $after[11], 'Branch B must change');
    }

    public function test_merkle_drilldown_core_two_branch_changes_produce_two_mismatched_branches(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;

        $bookAa = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000021', 'A1');
        $bookBa = $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000022', 'B1');

        $before = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        DB::table('books')
            ->where('uuid', $bookAa)
            ->where('library_id', $library->id)
            ->where('user_id', $userId)
            ->update([
                'title' => 'A1 updated',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);
        DB::table('books')
            ->where('uuid', $bookBa)
            ->where('library_id', $library->id)
            ->where('user_id', $userId)
            ->update([
                'title' => 'B1 updated',
                'updated_at' => now(),
                'last_modified' => now(),
            ]);
        $this->rebuildMerkle($library, ['metadata']);

        $after = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        $this->assertArrayHasKey(10, $before);
        $this->assertArrayHasKey(11, $before);
        $this->assertArrayHasKey(10, $after);
        $this->assertArrayHasKey(11, $after);
        $this->assertNotSame($before[10], $after[10], 'Branch A must change');
        $this->assertNotSame($before[11], $after[11], 'Branch B must change');
    }

    public function test_merkle_drilldown_core_soft_deleted_book_not_present_in_leaves(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;

        $bookAa = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000031', 'A1');
        $bookAb = $this->seedBook($library, $userId, 'ab000000-0000-4000-8000-000000000032', 'A2');

        DB::table('books')
            ->where('uuid', $bookAb)
            ->where('library_id', $library->id)
            ->where('user_id', $userId)
            ->update([
                'deleted_at' => now(),
                'updated_at' => now(),
                'last_modified' => now(),
            ]);
        $this->rebuildMerkle($library, ['metadata']);

        $leaves = $this->toLeafMap(
            $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=10')
                ->assertOk()
                ->json('leaves') ?? []
        );

        $allUuids = [];
        foreach ($leaves as $leaf) {
            $allUuids = array_merge($allUuids, $leaf['uuids']);
        }

        $this->assertContains($bookAa, $allUuids);
        $this->assertNotContains($bookAb, $allUuids);
    }

    public function test_merkle_drilldown_core_files_change_only_does_not_change_metadata_branches(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;

        $bookAa = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000041', 'A1');
        $this->seedBook($library, $userId, 'ab000000-0000-4000-8000-000000000042', 'A2');

        $before = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        $newFileHash = hash('sha256', 'new-file-hash-only-change');
        DB::table('files_store')->updateOrInsert(
            ['sha256' => $newFileHash],
            [
                'storage_key' => 'ebooks/new-aa.epub',
                'storage_provider' => 'r2',
                'storage_url' => 'https://example.test/ebooks/new-aa.epub',
                'ref_count' => 1,
                'created_at' => now(),
                'updated_at' => now(),
            ]
        );
        DB::table('books_files')
            ->where('book', $bookAa)
            ->where('library_id', $library->id)
            ->where('user_id', $userId)
            ->update([
                'file_hash' => $newFileHash,
                'storage_key' => 'ebooks/new-aa.epub',
                'updated_at' => now(),
            ]);
        $this->rebuildMerkle($library, ['files']);

        $after = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        $this->assertSame($before, $after, 'Metadata Merkle branches must not change for file-only updates');
    }

    public function test_merkle_core_seeded_books_must_produce_non_empty_branches(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;

        $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000051', 'A1');
        $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000052', 'B1');

        $response = $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata');
        $response->assertOk();
        $this->assertGreaterThan(
            0,
            (int) ($response->json('branch_count') ?? 0),
            'Seeded books should produce at least one metadata branch'
        );
    }

    public function test_merkle_core_seeded_book_must_be_present_in_expected_leaf_uuid_list(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;
        $bookAa = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000061', 'A1');

        $leaves = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=10');
        $leaves->assertOk();

        $all = [];
        foreach (($leaves->json('leaves') ?? []) as $leaf) {
            foreach (($leaf['uuids'] ?? []) as $u) {
                $all[] = $u;
            }
        }

        $this->assertContains(
            $bookAa,
            $all,
            'Seeded branch-A UUID must appear in branch_id=10 leaves'
        );
    }

    public function test_merkle_core_branch_hash_is_deterministic_between_two_reads_without_changes(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;

        $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000071', 'A1');
        $this->seedBook($library, $userId, 'ab000000-0000-4000-8000-000000000072', 'A2');

        $first = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );
        $second = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        $this->assertSame($first, $second, 'Merkle branches must be deterministic between identical reads');
    }

    public function test_merkle_core_insert_new_book_in_branch_a_changes_branch_a_only(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;

        $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000081', 'A1');
        $this->seedBook($library, $userId, 'ba000000-0000-4000-8000-000000000082', 'B1');

        $before = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        $this->seedBook($library, $userId, 'af000000-0000-4000-8000-000000000083', 'A-new');

        $after = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        $this->assertArrayHasKey(10, $before);
        $this->assertArrayHasKey(10, $after);
        $this->assertNotSame($before[10], $after[10], 'Branch A must change after new A-book');

        if (array_key_exists(11, $before) && array_key_exists(11, $after)) {
            $this->assertSame($before[11], $after[11], 'Branch B must remain unchanged');
        }
    }

    public function test_merkle_core_soft_delete_and_restore_changes_branch_then_restores_consistency(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;
        $uuid = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000091', 'A1');

        $before = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        DB::table('books')
            ->where('uuid', $uuid)
            ->where('library_id', $library->id)
            ->where('user_id', $userId)
            ->update(['deleted_at' => now(), 'updated_at' => now(), 'last_modified' => now()]);
        $this->rebuildMerkle($library, ['metadata']);

        $afterDelete = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        DB::table('books')
            ->where('uuid', $uuid)
            ->where('library_id', $library->id)
            ->where('user_id', $userId)
            ->update(['deleted_at' => null, 'updated_at' => now(), 'last_modified' => now()]);
        $this->rebuildMerkle($library, ['metadata']);

        $afterRestore = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );

        $this->assertNotSame($before, $afterDelete, 'Soft-delete must affect metadata branch map');
        $this->assertNotEmpty($afterRestore, 'Restore should rebuild non-empty branch map');
    }

    public function test_merkle_core_branch_and_leaf_mapping_for_f_prefix_uuid(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;
        $uuid = $this->seedBook($library, $userId, 'fa000000-0000-4000-8000-000000000101', 'F-branch');

        $branches = $this->toBranchMap(
            $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata')
                ->assertOk()
                ->json('branches') ?? []
        );
        $this->assertArrayHasKey(15, $branches, 'UUID starting with f* must map to branch_id=15');

        $leaves = $this->toLeafMap(
            $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=15')
                ->assertOk()
                ->json('leaves') ?? []
        );
        $this->assertArrayHasKey(250, $leaves, 'UUID starting with fa* must map to leaf_id=250');
        $this->assertContains($uuid, $leaves[250]['uuids']);
    }

    public function test_merkle_core_branch_specific_empty_when_other_branches_have_books(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;
        $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000111', 'A1');

        $branchA = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=10');
        $branchA->assertOk();
        $this->assertGreaterThan(0, (int) ($branchA->json('leaf_count') ?? 0));

        $branchF = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=15');
        $branchF->assertOk()
            ->assertJsonPath('leaf_count', 0)
            ->assertJsonPath('leaves', []);
    }

    public function test_merkle_branches_fallback_works_when_books_hash_view_is_missing(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;
        $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000131', 'A1');

        if (DB::getDriverName() === 'pgsql') {
            DB::statement('DROP VIEW IF EXISTS library_hash CASCADE');
            DB::statement('DROP VIEW IF EXISTS books_hash_v2 CASCADE');
        } else {
            DB::statement('DROP VIEW IF EXISTS books_hash_v2');
            DB::statement('DROP TABLE IF EXISTS books_hash_v2');
        }

        $response = $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata');
        $response->assertOk();
        $this->assertGreaterThan(
            0,
            (int) ($response->json('branch_count') ?? 0),
            'Fallback from books_hash_v2 to books table should keep Merkle branches available'
        );
    }

    public function test_preflight_total_books_excludes_soft_deleted_books(): void
    {
        $library = $this->actingUserWithLibrary();
        $userId = (int) $library->user_id;
        $uuidAlive = $this->seedBook($library, $userId, 'aa000000-0000-4000-8000-000000000121', 'Alive');
        $uuidDeleted = $this->seedBook($library, $userId, 'ab000000-0000-4000-8000-000000000122', 'Deleted');

        $before = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);
        $before->assertOk();
        $this->assertGreaterThanOrEqual(2, (int) ($before->json('total_books') ?? 0));

        DB::table('books')
            ->whereIn('uuid', [$uuidDeleted])
            ->where('library_id', $library->id)
            ->where('user_id', $userId)
            ->update(['deleted_at' => now(), 'updated_at' => now(), 'last_modified' => now()]);
        $this->rebuildMerkle($library, ['metadata']);

        $after = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);
        $after->assertOk();
        $this->assertSame(
            1,
            (int) ($after->json('total_books') ?? 0),
            'Preflight total_books must count only non-soft-deleted books'
        );

        // sanity: alive UUID still present in merkle leaves
        $leaves = $this->getJson('/api/sync/v5/merkle/leaves?library_id=' . $library->id . '&dimension=metadata&branch_id=10');
        $leaves->assertOk();
        $all = [];
        foreach (($leaves->json('leaves') ?? []) as $leaf) {
            foreach (($leaf['uuids'] ?? []) as $u) {
                $all[] = $u;
            }
        }
        $this->assertContains($uuidAlive, $all);
        $this->assertNotContains($uuidDeleted, $all);
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

        $this->rebuildMerkle($library, ['metadata', 'files', 'covers']);

        return $uuid;
    }

    private function rebuildMerkle(Library $library, array $dimensions): void
    {
        app(MaterializedMerkleService::class)->rebuildLibraryDimensions(
            (int) $library->user_id,
            (int) $library->id,
            $dimensions
        );
    }

    private function toBranchMap(array $branches): array
    {
        $map = [];
        foreach ($branches as $branch) {
            $map[(int) ($branch['branch_id'] ?? -1)] = (string) ($branch['branch_hash'] ?? '');
        }
        return $map;
    }

    private function toLeafMap(array $leaves): array
    {
        $map = [];
        foreach ($leaves as $leaf) {
            $map[(int) ($leaf['leaf_id'] ?? -1)] = [
                'leaf_hash' => (string) ($leaf['leaf_hash'] ?? ''),
                'uuids' => array_values($leaf['uuids'] ?? []),
            ];
        }
        return $map;
    }
}
