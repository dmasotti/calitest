<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class ProtocolPullTest extends TestCase
{
    use RefreshDatabase;

    private function setupUserAndLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);
        $calibreUuid = $library->calibre_library_id;

        return [$user, $library, $calibreUuid];
    }

    public function test_pull_does_not_return_client_ids(): void
    {
        [, $library, $calibreUuid] = $this->setupUserAndLibrary();

        $uuid = (string) Str::uuid();
        $createPayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 201,
                        'uuid' => $uuid,
                        'title' => 'Pull Test',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'idem-pull-1',
                ],
            ],
        ];

        $this->postJson('/api/sync', $createPayload)->assertStatus(200);

        $pull = $this->postJson('/api/sync/pull', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'cursor' => null,
            'limit' => 200,
        ]);

        $pull->assertStatus(200);
        $item = $pull->json('changes.0.item');
        $this->assertIsArray($item);
        $this->assertArrayNotHasKey('client_ids', $item);
    }

    public function test_client_inventory_filters_tombstones(): void
    {
        [, $library, $calibreUuid] = $this->setupUserAndLibrary();

        $uuid = (string) Str::uuid();
        $createPayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 202,
                        'uuid' => $uuid,
                        'title' => 'To Delete',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'idem-pull-2',
                ],
            ],
        ];
        $this->postJson('/api/sync', $createPayload)->assertStatus(200);

        $deletePayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'changes' => [
                [
                    'op' => 'delete',
                    'item' => [
                        'id' => 202,
                        'uuid' => $uuid,
                    ],
                    'idempotency_key' => 'idem-pull-3',
                ],
            ],
        ];
        $this->postJson('/api/sync', $deletePayload)->assertStatus(200);

        $pullFiltered = $this->postJson('/api/sync/pull', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'cursor' => null,
            'client_inventory' => [
                'uuids' => [],
            ],
        ]);
        $pullFiltered->assertStatus(200);
        $this->assertEmpty($pullFiltered->json('changes'));

        $pullIncluded = $this->postJson('/api/sync/pull', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'cursor' => null,
            'client_inventory' => [
                'uuids' => [$uuid],
            ],
        ]);
        $pullIncluded->assertStatus(200);
        $this->assertNotEmpty($pullIncluded->json('changes'));
        $this->assertSame('delete', $pullIncluded->json('changes.0.op'));
    }
}
