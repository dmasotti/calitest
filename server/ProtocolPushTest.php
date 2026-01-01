<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class ProtocolPushTest extends TestCase
{
    use RefreshDatabase;

    private function setupUserAndLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);
        $calibreUuid = (string) Str::uuid();

        return [$user, $library, $calibreUuid];
    }

    public function test_client_change_id_equals_idempotency_key(): void
    {
        [, $library, $calibreUuid] = $this->setupUserAndLibrary();

        $uuid = (string) Str::uuid();
        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 101,
                        'uuid' => $uuid,
                        'title' => 'Protocol Test',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'idem-proto-1',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $payload);
        $response->assertStatus(200);
        $this->assertSame('idem-proto-1', $response->json('results.0.client_change_id'));
    }

    public function test_uuid_is_required(): void
    {
        [, $library, $calibreUuid] = $this->setupUserAndLibrary();

        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 102,
                        'title' => 'Missing UUID',
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'idem-proto-2',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $payload);
        $response->assertStatus(422);
    }

    public function test_delete_tombstone_is_not_resurrected_by_update(): void
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
                        'id' => 103,
                        'uuid' => $uuid,
                        'title' => 'To Delete',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'idem-proto-3',
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
                        'id' => 103,
                        'uuid' => $uuid,
                    ],
                    'idempotency_key' => 'idem-proto-4',
                ],
            ],
        ];

        $this->postJson('/api/sync', $deletePayload)->assertStatus(200);

        $updatePayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'changes' => [
                [
                    'op' => 'update',
                    'item' => [
                        'id' => 103,
                        'uuid' => $uuid,
                        'title' => 'Should Not Revive',
                        'last_modified' => now()->addSeconds(5)->timestamp,
                    ],
                    'idempotency_key' => 'idem-proto-5',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $updatePayload);
        $response->assertStatus(200);
        $this->assertSame('conflict', $response->json('results.0.status'));
        $this->assertSame('deleted', $response->json('results.0.reason'));
    }
}
