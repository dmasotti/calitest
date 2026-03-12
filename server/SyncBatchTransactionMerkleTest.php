<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use App\Services\Sync\ConflictHandler;
use App\Services\Sync\CoreDelegate;
use App\Services\Sync\CoverHandler;
use App\Services\Sync\IdempotencyHandler;
use App\Services\Sync\InventoryHandler;
use App\Services\Sync\MaterializedMerkleService;
use App\Services\SyncService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Mockery;
use Tests\TestCase;

class SyncBatchTransactionMerkleTest extends TestCase
{
    use RefreshDatabase;

    protected function tearDown(): void
    {
        Mockery::close();
        parent::tearDown();
    }

    public function test_metadata_batch_marks_nodes_stale_and_defers_rebuild_until_read_path(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Batch transaction semantics are validated on MySQL/PostgreSQL.');
        }

        [$user, $library] = $this->makeContext();
        UserBook::query()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => 501,
            'uuid' => 'aa000000-0000-4000-8000-00000000b501',
            'title' => 'Batch TX Book',
            'last_modified' => now(),
        ]);
        app(MaterializedMerkleService::class)->rebuildLibraryDimensions($user->id, (int) $library->id, ['metadata']);

        $merkle = Mockery::mock(MaterializedMerkleService::class)->makePartial();
        $merkle->shouldReceive('markDimensionsStaleForTouchedUuids')
            ->once()
            ->withArgs(function (int $userId, int $libraryId, array $dimensionUuids) use ($user, $library): bool {
                $this->assertSame((int) $user->id, $userId);
                $this->assertSame((int) $library->id, $libraryId);
                $this->assertArrayHasKey('metadata', $dimensionUuids);
                return true;
            })
            ->passthru();
        $merkle->shouldNotReceive('rebuildLibraryDimensionsForTouchedUuids');

        $service = $this->makeSyncService($merkle);

        $changes = [[
            'op' => 'upsert',
            'idempotency_key' => 'batch-tx-merkle-1',
            'client_change_id' => 'batch-tx-merkle-1',
            'item' => [
                'id' => 501,
                'uuid' => 'aa000000-0000-4000-8000-00000000b501',
                'title' => 'Batch TX Book',
                'last_modified' => 1772200001,
            ],
        ]];

        $response = $service->applySyncChanges($user, $changes, null, $library->id, false);

        $this->assertSame('applied', data_get($response, 'results.0.status'));
        $this->assertDatabaseHas('books', [
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => 'aa000000-0000-4000-8000-00000000b501',
        ]);
        $this->assertSame(
            1,
            (int) DB::table('sync_merkle_roots')
                ->where('user_id', $user->id)
                ->where('library_id', $library->id)
                ->where('dimension', 'metadata')
                ->value('is_stale')
        );
        $this->assertSame(
            1,
            (int) DB::table('sync_merkle_leaves')
                ->where('user_id', $user->id)
                ->where('library_id', $library->id)
                ->where('dimension', 'metadata')
                ->where('leaf_id', 0xAA)
                ->value('is_stale')
        );

        $roots = app(MaterializedMerkleService::class)->getLibraryRoots($user->id, (int) $library->id);
        $this->assertNotEmpty($roots['metadata'] ?? null);
        $this->assertSame(
            0,
            (int) DB::table('sync_merkle_roots')
                ->where('user_id', $user->id)
                ->where('library_id', $library->id)
                ->where('dimension', 'metadata')
                ->value('is_stale')
        );
        $this->assertSame(
            0,
            (int) DB::table('sync_merkle_leaves')
                ->where('user_id', $user->id)
                ->where('library_id', $library->id)
                ->where('dimension', 'metadata')
                ->where('leaf_id', 0xAA)
                ->value('is_stale')
        );
    }

    public function test_apply_sync_changes_preserves_successful_metadata_batch_changes_and_leaves_nodes_stale_for_later_recovery(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Batch transaction semantics are validated on MySQL/PostgreSQL.');
        }

        [$user, $library] = $this->makeContext();
        UserBook::query()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => 502,
            'uuid' => 'ab000000-0000-4000-8000-00000000b502',
            'title' => 'Rollback Book',
            'last_modified' => now(),
        ]);
        app(MaterializedMerkleService::class)->rebuildLibraryDimensions($user->id, (int) $library->id, ['metadata']);

        $merkle = Mockery::mock(MaterializedMerkleService::class)->makePartial();
        $merkle->shouldReceive('markDimensionsStaleForTouchedUuids')->once()->passthru();
        $merkle->shouldNotReceive('rebuildLibraryDimensionsForTouchedUuids');

        $service = $this->makeSyncService($merkle);

        $changes = [[
            'op' => 'upsert',
            'idempotency_key' => 'batch-tx-merkle-rollback-1',
            'client_change_id' => 'batch-tx-merkle-rollback-1',
            'item' => [
                'id' => 502,
                'uuid' => 'ab000000-0000-4000-8000-00000000b502',
                'title' => 'Rollback Book',
                'last_modified' => 1772200002,
            ],
        ]];

        $response = $service->applySyncChanges($user, $changes, null, $library->id, false);

        $this->assertSame('applied', data_get($response, 'results.0.status'));
        $this->assertDatabaseHas('books', [
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => 'ab000000-0000-4000-8000-00000000b502',
            'title' => 'Rollback Book',
        ]);
        $this->assertSame(1, (int) DB::table('sync_merkle_roots')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('dimension', 'metadata')
            ->value('is_stale'));
        $this->assertSame(1, (int) DB::table('sync_merkle_leaves')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAB)
            ->value('is_stale'));
    }

    public function test_batch_item_failure_rolls_back_only_failed_item_and_lazy_materialization_includes_only_successes(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Batch transaction semantics are validated on MySQL/PostgreSQL.');
        }

        [$user, $library] = $this->makeContext();
        $failingUuid = 'ad000000-0000-4000-8000-00000000b504';

        $service = $this->makeSyncServiceWithFailingUuid($failingUuid);

        $changes = [
            [
                'op' => 'upsert',
                'idempotency_key' => 'batch-item-ok-1',
                'client_change_id' => 'batch-item-ok-1',
                'item' => [
                    'id' => 503,
                    'uuid' => 'ac000000-0000-4000-8000-00000000b503',
                    'title' => 'Book OK',
                    'last_modified' => 1772200003,
                ],
            ],
            [
                'op' => 'upsert',
                'idempotency_key' => 'batch-item-fail-1',
                'client_change_id' => 'batch-item-fail-1',
                'item' => [
                    'id' => 504,
                    'uuid' => $failingUuid,
                    'title' => 'Book FAIL',
                    'last_modified' => 1772200004,
                ],
            ],
        ];

        $response = $service->applySyncChanges($user, $changes, null, $library->id, false);

        $this->assertSame('applied', data_get($response, 'results.0.status'));
        $this->assertSame('error', data_get($response, 'results.1.status'));
        $this->assertStringContainsString('forced item failure', (string) data_get($response, 'results.1.error'));

        $this->assertDatabaseHas('books', [
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => 'ac000000-0000-4000-8000-00000000b503',
        ]);
        $this->assertDatabaseMissing('books', [
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => $failingUuid,
        ]);

        $this->assertSame(
            1,
            (int) DB::table('sync_merkle_roots')
                ->where('user_id', $user->id)
                ->where('library_id', $library->id)
                ->where('dimension', 'metadata')
                ->value('is_stale')
        );

        app(MaterializedMerkleService::class)->getLibraryRoots($user->id, (int) $library->id);

        $root = DB::table('sync_merkle_roots')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('dimension', 'metadata')
            ->value('root_hash');
        $this->assertNotEmpty($root);

        $uuids = DB::table('sync_merkle_leaves')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('dimension', 'metadata')
            ->pluck('uuids_json')
            ->map(function ($json) {
                return json_decode((string) $json, true) ?: [];
            })
            ->flatten()
            ->values()
            ->all();

        $this->assertSame(['ac000000-0000-4000-8000-00000000b503'], $uuids);
    }

    public function test_apply_sync_changes_can_return_internal_phase_profile_when_requested(): void
    {
        [$user, $library] = $this->makeContext();

        $service = $this->makeSyncService();

        $changes = [[
            'op' => 'upsert',
            'idempotency_key' => 'batch-profile-1',
            'client_change_id' => 'batch-profile-1',
            'item' => [
                'id' => 601,
                'uuid' => 'ae000000-0000-4000-8000-00000000b601',
                'title' => 'Profiled Book',
                'last_modified' => 1772200601,
            ],
        ]];

        $response = $service->applySyncChanges($user, $changes, null, $library->id, false, false, true);

        $this->assertSame('applied', data_get($response, 'results.0.status'));
        $this->assertIsArray($response['profile'] ?? null);
        $this->assertArrayHasKey('apply_sync_changes', $response['profile']);

        $profile = $response['profile']['apply_sync_changes'];
        $this->assertIsArray($profile);
        $this->assertArrayHasKey('loop_changes_ms', $profile);
        $this->assertArrayHasKey('lookup_or_create_ms', $profile);
        $this->assertArrayHasKey('update_book_ms', $profile);
        $this->assertArrayHasKey('metadata_apply_ms', $profile);
        $this->assertArrayHasKey('metadata_hash_refresh_ms', $profile);
        $this->assertArrayHasKey('idempotency_persist_ms', $profile);
        $this->assertArrayHasKey('metadata_authors_ms', $profile);
        $this->assertArrayHasKey('metadata_tags_ms', $profile);
        $this->assertArrayHasKey('metadata_tags_prefetch_ms', $profile);
        $this->assertArrayHasKey('metadata_tags_entity_ms', $profile);
        $this->assertArrayHasKey('metadata_tags_links_ms', $profile);
        $this->assertArrayHasKey('metadata_tags_mappings_ms', $profile);
        $this->assertArrayHasKey('metadata_series_ms', $profile);
        $this->assertArrayHasKey('metadata_publisher_ms', $profile);
        $this->assertArrayHasKey('metadata_languages_ms', $profile);
        $this->assertArrayHasKey('metadata_identifiers_ms', $profile);
        $this->assertArrayHasKey('metadata_rating_ms', $profile);
        $this->assertArrayHasKey('metadata_save_ms', $profile);
        $this->assertArrayHasKey('metadata_files_ms', $profile);
        $this->assertArrayHasKey('rebuild_merkle_ms', $profile);
        $this->assertArrayHasKey('rebuild_merkle_delete_touched_leaves_ms', $profile);
        $this->assertArrayHasKey('rebuild_merkle_metadata_source_select_ms', $profile);
        $this->assertArrayHasKey('rebuild_merkle_insert_touched_leaves_ms', $profile);
        $this->assertArrayHasKey('rebuild_merkle_leaves_ms', $profile);
        $this->assertArrayHasKey('rebuild_merkle_branches_ms', $profile);
        $this->assertArrayHasKey('rebuild_merkle_root_ms', $profile);
        $this->assertArrayHasKey('rebuild_merkle_ensure_ms', $profile);
        $this->assertArrayHasKey('total_ms', $profile);
        $this->assertIsNumeric($profile['loop_changes_ms']);
        $this->assertIsNumeric($profile['lookup_or_create_ms']);
        $this->assertIsNumeric($profile['update_book_ms']);
        $this->assertIsNumeric($profile['metadata_apply_ms']);
        $this->assertIsNumeric($profile['metadata_hash_refresh_ms']);
        $this->assertIsNumeric($profile['idempotency_persist_ms']);
        $this->assertIsNumeric($profile['metadata_authors_ms']);
        $this->assertIsNumeric($profile['metadata_tags_ms']);
        $this->assertIsNumeric($profile['metadata_tags_prefetch_ms']);
        $this->assertIsNumeric($profile['metadata_tags_entity_ms']);
        $this->assertIsNumeric($profile['metadata_tags_links_ms']);
        $this->assertIsNumeric($profile['metadata_tags_mappings_ms']);
        $this->assertIsNumeric($profile['metadata_series_ms']);
        $this->assertIsNumeric($profile['metadata_publisher_ms']);
        $this->assertIsNumeric($profile['metadata_languages_ms']);
        $this->assertIsNumeric($profile['metadata_identifiers_ms']);
        $this->assertIsNumeric($profile['metadata_rating_ms']);
        $this->assertIsNumeric($profile['metadata_save_ms']);
        $this->assertIsNumeric($profile['metadata_files_ms']);
        $this->assertIsNumeric($profile['rebuild_merkle_ms']);
        $this->assertIsNumeric($profile['rebuild_merkle_delete_touched_leaves_ms']);
        $this->assertIsNumeric($profile['rebuild_merkle_metadata_source_select_ms']);
        $this->assertIsNumeric($profile['rebuild_merkle_insert_touched_leaves_ms']);
        $this->assertIsNumeric($profile['rebuild_merkle_leaves_ms']);
        $this->assertIsNumeric($profile['rebuild_merkle_branches_ms']);
        $this->assertIsNumeric($profile['rebuild_merkle_root_ms']);
        $this->assertIsNumeric($profile['rebuild_merkle_ensure_ms']);
        $this->assertIsNumeric($profile['total_ms']);
    }

    public function test_apply_sync_changes_rebuilds_only_touched_metadata_leaves(): void
    {
        [$user, $library] = $this->makeContext();

        $bookAa = UserBook::query()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => 701,
            'uuid' => 'aa000000-0000-4000-8000-00000000b701',
            'title' => 'AA',
            'last_modified' => now(),
        ]);
        $bookAb = UserBook::query()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => 702,
            'uuid' => 'ab000000-0000-4000-8000-00000000b702',
            'title' => 'AB',
            'last_modified' => now(),
        ]);

        app(MaterializedMerkleService::class)->rebuildLibraryDimensions($user->id, (int) $library->id, ['metadata']);

        $untouchedLeafBefore = DB::table('sync_merkle_leaves')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAB)
            ->first();

        $this->assertNotNull($untouchedLeafBefore);

        $service = $this->makeSyncService();
        $changes = [[
            'op' => 'upsert',
            'idempotency_key' => 'batch-inc-leaf-1',
            'client_change_id' => 'batch-inc-leaf-1',
            'item' => [
                'id' => 701,
                'uuid' => $bookAa->uuid,
                'title' => 'AA updated',
                'last_modified' => 1772200701,
            ],
        ]];

        $response = $service->applySyncChanges($user, $changes, null, $library->id, false);

        $this->assertSame('applied', data_get($response, 'results.0.status'));

        $untouchedLeafAfter = DB::table('sync_merkle_leaves')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAB)
            ->first();

        $this->assertNotNull($untouchedLeafAfter);
        $this->assertSame((int) $untouchedLeafBefore->id, (int) $untouchedLeafAfter->id);
        $this->assertSame((string) $untouchedLeafBefore->leaf_hash, (string) $untouchedLeafAfter->leaf_hash);
    }

    public function test_apply_sync_changes_does_not_touch_other_library_merkle_rows_for_same_user(): void
    {
        [$user, $libraryA] = $this->makeContext();
        $libraryB = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Batch Tx Sync Lib B',
        ]);

        UserBook::query()->create([
            'user_id' => $user->id,
            'library_id' => $libraryA->id,
            'book_id' => 801,
            'uuid' => 'aa000000-0000-4000-8000-00000000b801',
            'title' => 'Lib A',
            'last_modified' => now(),
        ]);
        UserBook::query()->create([
            'user_id' => $user->id,
            'library_id' => $libraryB->id,
            'book_id' => 802,
            'uuid' => 'aa000000-0000-4000-8000-00000000b802',
            'title' => 'Lib B',
            'last_modified' => now(),
        ]);

        $merkle = app(MaterializedMerkleService::class);
        $merkle->rebuildLibraryDimensions($user->id, (int) $libraryA->id, ['metadata']);
        $merkle->rebuildLibraryDimensions($user->id, (int) $libraryB->id, ['metadata']);

        $leafBefore = DB::table('sync_merkle_leaves')
            ->where('user_id', $user->id)
            ->where('library_id', $libraryB->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAA)
            ->first();
        $rootBefore = DB::table('sync_merkle_roots')
            ->where('user_id', $user->id)
            ->where('library_id', $libraryB->id)
            ->where('dimension', 'metadata')
            ->first();

        $this->assertNotNull($leafBefore);
        $this->assertNotNull($rootBefore);

        $service = $this->makeSyncService();
        $response = $service->applySyncChanges($user, [[
            'op' => 'upsert',
            'idempotency_key' => 'batch-isolation-lib-a-1',
            'client_change_id' => 'batch-isolation-lib-a-1',
            'item' => [
                'id' => 801,
                'uuid' => 'aa000000-0000-4000-8000-00000000b801',
                'title' => 'Lib A updated',
                'last_modified' => 1772200801,
            ],
        ]], null, $libraryA->id, false);

        $this->assertSame('applied', data_get($response, 'results.0.status'));

        $leafAfter = DB::table('sync_merkle_leaves')
            ->where('user_id', $user->id)
            ->where('library_id', $libraryB->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAA)
            ->first();
        $rootAfter = DB::table('sync_merkle_roots')
            ->where('user_id', $user->id)
            ->where('library_id', $libraryB->id)
            ->where('dimension', 'metadata')
            ->first();

        $this->assertNotNull($leafAfter);
        $this->assertNotNull($rootAfter);
        $this->assertSame((int) $leafBefore->id, (int) $leafAfter->id);
        $this->assertSame((string) $leafBefore->leaf_hash, (string) $leafAfter->leaf_hash);
        $this->assertSame((int) $rootBefore->id, (int) $rootAfter->id);
        $this->assertSame((string) $rootBefore->root_hash, (string) $rootAfter->root_hash);
    }

    public function test_apply_sync_changes_does_not_touch_other_user_merkle_rows(): void
    {
        [$userA, $libraryA] = $this->makeContext();
        [$userB, $libraryB] = $this->makeContext();

        UserBook::query()->create([
            'user_id' => $userA->id,
            'library_id' => $libraryA->id,
            'book_id' => 901,
            'uuid' => 'aa000000-0000-4000-8000-00000000b901',
            'title' => 'User A',
            'last_modified' => now(),
        ]);
        UserBook::query()->create([
            'user_id' => $userB->id,
            'library_id' => $libraryB->id,
            'book_id' => 902,
            'uuid' => 'aa000000-0000-4000-8000-00000000b902',
            'title' => 'User B',
            'last_modified' => now(),
        ]);

        $merkle = app(MaterializedMerkleService::class);
        $merkle->rebuildLibraryDimensions($userA->id, (int) $libraryA->id, ['metadata']);
        $merkle->rebuildLibraryDimensions($userB->id, (int) $libraryB->id, ['metadata']);

        $leafBefore = DB::table('sync_merkle_leaves')
            ->where('user_id', $userB->id)
            ->where('library_id', $libraryB->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAA)
            ->first();
        $rootBefore = DB::table('sync_merkle_roots')
            ->where('user_id', $userB->id)
            ->where('library_id', $libraryB->id)
            ->where('dimension', 'metadata')
            ->first();

        $this->assertNotNull($leafBefore);
        $this->assertNotNull($rootBefore);

        $service = $this->makeSyncService();
        $response = $service->applySyncChanges($userA, [[
            'op' => 'upsert',
            'idempotency_key' => 'batch-isolation-user-a-1',
            'client_change_id' => 'batch-isolation-user-a-1',
            'item' => [
                'id' => 901,
                'uuid' => 'aa000000-0000-4000-8000-00000000b901',
                'title' => 'User A updated',
                'last_modified' => 1772200901,
            ],
        ]], null, $libraryA->id, false);

        $this->assertSame('applied', data_get($response, 'results.0.status'));

        $leafAfter = DB::table('sync_merkle_leaves')
            ->where('user_id', $userB->id)
            ->where('library_id', $libraryB->id)
            ->where('dimension', 'metadata')
            ->where('leaf_id', 0xAA)
            ->first();
        $rootAfter = DB::table('sync_merkle_roots')
            ->where('user_id', $userB->id)
            ->where('library_id', $libraryB->id)
            ->where('dimension', 'metadata')
            ->first();

        $this->assertNotNull($leafAfter);
        $this->assertNotNull($rootAfter);
        $this->assertSame((int) $leafBefore->id, (int) $leafAfter->id);
        $this->assertSame((string) $leafBefore->leaf_hash, (string) $leafAfter->leaf_hash);
        $this->assertSame((int) $rootBefore->id, (int) $rootAfter->id);
        $this->assertSame((string) $rootBefore->root_hash, (string) $rootAfter->root_hash);
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Batch Tx Sync Lib',
        ]);

        return [$user, $library];
    }

    private function makeSyncService(?MaterializedMerkleService $merkle = null): SyncService
    {
        return new SyncService(
            app(BookMetadataHandler::class),
            app(IdempotencyHandler::class),
            app(InventoryHandler::class),
            app(CoverHandler::class),
            app(CoreDelegate::class),
            app(ConflictHandler::class),
            $merkle ?? app(MaterializedMerkleService::class)
        );
    }

    private function makeSyncServiceWithFailingUuid(string $failingUuid): SyncService
    {
        return new class(
            app(BookMetadataHandler::class),
            app(IdempotencyHandler::class),
            app(InventoryHandler::class),
            app(CoverHandler::class),
            app(CoreDelegate::class),
            app(ConflictHandler::class),
            app(MaterializedMerkleService::class),
            $failingUuid
        ) extends SyncService {
            public function __construct(
                BookMetadataHandler $bookMetadataHandler,
                IdempotencyHandler $idempotencyHandler,
                InventoryHandler $inventoryHandler,
                CoverHandler $coverHandler,
                CoreDelegate $coreDelegate,
                ConflictHandler $conflictHandler,
                MaterializedMerkleService $materializedMerkleService,
                private string $failingUuid
            ) {
                parent::__construct(
                    $bookMetadataHandler,
                    $idempotencyHandler,
                    $inventoryHandler,
                    $coverHandler,
                    $coreDelegate,
                    $conflictHandler,
                    $materializedMerkleService
                );
            }

            protected function updateBookFromItem($item, $user, $libraryId, $userBook = null, ?array &$phaseTimings = null)
            {
                if (($item['uuid'] ?? null) === $this->failingUuid) {
                    throw new \RuntimeException('forced item failure');
                }

                return parent::updateBookFromItem($item, $user, $libraryId, $userBook, $phaseTimings);
            }
        };
    }
}
