<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\SyncConflict;
use App\Models\SyncMapping;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncPushTest extends TestCase
{
    use RefreshDatabase;

    public function test_idempotency_reuse_same_payload(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuid = (string) Str::uuid();
        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 123,
                        'uuid' => $uuid,
                        'title' => 'Idempotent',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                        'client_ids' => [
                            'calibre:' . $library->calibre_library_id . ':123' => '123',
                        ],
                    ],
                    'idempotency_key' => 'idem-1',
                ],
            ],
        ];

        $first = $this->postJson('/api/sync', $payload);
        $first->assertStatus(200);
        $this->assertNotEmpty($first->json('results.0.status'));

        $second = $this->postJson('/api/sync', $payload);
        $second->assertStatus(200);
        $this->assertNotEmpty($second->json('results.0.status'));
        $this->assertNotSame('error', $second->json('results.0.status'));
    }

    public function test_idempotency_reuse_different_payload_returns_error(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuid = (string) Str::uuid();
        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 124,
                        'uuid' => $uuid,
                        'title' => 'First',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'idem-2',
                ],
            ],
        ];

        $this->postJson('/api/sync', $payload)
            ->assertStatus(200);

        $payload['changes'][0]['item']['title'] = 'Different';
        $response = $this->postJson('/api/sync', $payload);
        $response->assertStatus(200);
        $this->assertSame('error', $response->json('results.0.status'));
    }

    public function test_sync_mappings_created_for_books(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $clientKey = 'calibre:' . $library->calibre_library_id . ':200';
        $uuid = (string) Str::uuid();
        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 200,
                        'uuid' => $uuid,
                        'title' => 'Mapping Book',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'client_ids' => [$clientKey => '200'],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'idem-map-1',
                ],
            ],
        ];

        $this->postJson('/api/sync', $payload)
            ->assertStatus(200);

        $this->assertDatabaseHas('sync_mappings', [
            'user_id' => $user->id,
            'library_id' => $library->id,
            'entity_type' => 'books',
            'client_key' => $clientKey,
        ]);
    }

    public function test_conflict_creates_record_and_api_lists_it(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $book = UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'id' => 300,
            'title' => 'Server Title',
            'last_modified' => now(),
        ]);

        $olderVersion = $book->last_modified->timestamp - 10;
        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'update',
                    'item' => [
                        'id' => 300,
                        'uuid' => $book->uuid,
                        'version' => $olderVersion,
                        'title' => 'Client Older',
                        'timestamps' => [
                            'last_modified' => now()->timestamp,
                        ],
                    ],
                    'idempotency_key' => 'idem-conflict-1',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $payload);
        $response->assertStatus(200);
        $this->assertSame('conflict', $response->json('results.0.status'));

        $conflict = SyncConflict::first();
        $this->assertNotNull($conflict);

        $list = $this->getJson('/api/sync/conflicts?library_id=' . $library->id);
        $list->assertStatus(200);
        $this->assertCount(1, $list->json('conflicts'));

        $resolve = $this->postJson('/api/sync/conflicts/' . $conflict->id . '/resolve', [
            'resolution' => 'keep_server',
        ]);
        $resolve->assertStatus(200);

        $conflict->refresh();
        $this->assertSame('resolved', $conflict->status);
    }
}
