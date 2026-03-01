<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
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
            'stream' => false,
        ]);

        $pull->assertStatus(200);
        $item = $pull->json('changes.0.item');
        $this->assertIsArray($item);
        $this->assertArrayNotHasKey('client_ids', $item);
    }

    public function test_client_inventory_filters_tombstones(): void
    {
        [$user, $library, $calibreUuid] = $this->setupUserAndLibrary();

        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'To Delete',
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->subMinute()->timestamp,
        ]);
        $book->delete();
        $uuid = $book->uuid;

        $cursor = base64_encode(json_encode([
            'timestamp' => now()->addMinute()->timestamp,
            'last_id' => 0,
            'phase' => 'changes',
            'missing_offset' => 0,
        ]));

        $pullFiltered = $this->postJson('/api/sync/pull', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'cursor' => $cursor,
            'client_inventory' => [
                'uuids' => [],
            ],
            'stream' => false,
        ]);
        $pullFiltered->assertStatus(200);
        $this->assertEmpty($pullFiltered->json('changes'));

        $pullIncluded = $this->postJson('/api/sync/pull', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'cursor' => $cursor,
            'client_inventory' => [
                'uuids' => [$uuid],
            ],
            'stream' => false,
        ]);
        $pullIncluded->assertStatus(200);
        $this->assertNotEmpty($pullIncluded->json('changes'));
        $this->assertSame('delete', $pullIncluded->json('changes.0.op'));
    }
}
