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

    public function test_metadata_batch_rebuild_runs_inside_outer_batch_transaction(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Batch transaction semantics are validated on MySQL/PostgreSQL.');
        }

        [$user, $library] = $this->makeContext();

        $merkle = Mockery::mock(MaterializedMerkleService::class)->makePartial();
        $merkle->shouldReceive('rebuildLibraryDimensions')
            ->once()
            ->withArgs(function (int $userId, int $libraryId, array $dimensions) use ($user, $library): bool {
                $this->assertSame((int) $user->id, $userId);
                $this->assertSame((int) $library->id, $libraryId);
                $this->assertContains('metadata', $dimensions);
                $this->assertGreaterThan(
                    0,
                    DB::transactionLevel(),
                    'Merkle rebuild must run before the outer batch transaction is committed'
                );
                return true;
            });

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
    }

    public function test_rebuild_failure_rolls_back_successful_metadata_batch_changes(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Batch transaction semantics are validated on MySQL/PostgreSQL.');
        }

        [$user, $library] = $this->makeContext();

        $merkle = Mockery::mock(MaterializedMerkleService::class)->makePartial();
        $merkle->shouldReceive('rebuildLibraryDimensions')
            ->once()
            ->andThrow(new \RuntimeException('forced merkle rebuild failure'));

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

        try {
            $service->applySyncChanges($user, $changes, null, $library->id, false);
            $this->fail('Expected merkle rebuild failure to bubble up');
        } catch (\RuntimeException $e) {
            $this->assertSame('forced merkle rebuild failure', $e->getMessage());
        }

        $this->assertDatabaseMissing('books', [
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => 'ab000000-0000-4000-8000-00000000b502',
        ]);
    }

    public function test_batch_item_failure_rolls_back_only_failed_item_and_materializes_successes(): void
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
        $this->assertArrayHasKey('rebuild_merkle_ms', $profile);
        $this->assertArrayHasKey('total_ms', $profile);
        $this->assertIsNumeric($profile['loop_changes_ms']);
        $this->assertIsNumeric($profile['rebuild_merkle_ms']);
        $this->assertIsNumeric($profile['total_ms']);
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

            protected function updateBookFromItem($item, $user, $libraryId, $userBook = null)
            {
                if (($item['uuid'] ?? null) === $this->failingUuid) {
                    throw new \RuntimeException('forced item failure');
                }

                return parent::updateBookFromItem($item, $user, $libraryId, $userBook);
            }
        };
    }
}
