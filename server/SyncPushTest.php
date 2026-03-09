<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\SyncConflict;
use App\Models\SyncMapping;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Schema;
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

    public function test_sync_does_not_persist_client_ids_mappings(): void
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
                        'id' => 200,
                        'uuid' => $uuid,
                        'title' => 'Mapping Book',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'client_ids' => ['calibre:' . $library->calibre_library_id . ':200' => '200'],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'idem-map-1',
                ],
            ],
        ];

        $this->postJson('/api/sync', $payload)
            ->assertStatus(200);

        $this->assertDatabaseHas('books', [
            'uuid' => $uuid,
        ]);
        if (Schema::hasTable('sync_mappings')) {
            $this->assertSame(0, SyncMapping::query()->count());
        }
    }

    public function test_sync_can_update_and_clear_status(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuid = (string) Str::uuid();
        $createPayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 321,
                        'uuid' => $uuid,
                        'title' => 'Status Book',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'status-1',
                ],
            ],
        ];

        $this->postJson('/api/sync', $createPayload)->assertStatus(200);

        $book = UserBook::where('uuid', $uuid)->firstOrFail();
        $this->assertNull($book->status);

        $updatePayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'update',
                    'item' => [
                        'id' => 321,
                        'uuid' => $uuid,
                        'title' => 'Status Book',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                        'status' => 'reading',
                    ],
                    'idempotency_key' => 'status-2',
                ],
            ],
        ];

        $this->postJson('/api/sync', $updatePayload)->assertStatus(200);
        $book->refresh();
        $this->assertSame('reading', $book->status);

        $clearPayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'update',
                    'item' => [
                        'id' => 321,
                        'uuid' => $uuid,
                        'title' => 'Status Book',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                        'status' => null,
                    ],
                    'idempotency_key' => 'status-3',
                ],
            ],
        ];

        $this->postJson('/api/sync', $clearPayload)->assertStatus(200);
        $book->refresh();
        $this->assertNull($book->status);
    }

    public function test_sync_preserves_client_last_modified_on_update(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $book = UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'id' => 500,
            'title' => 'Client Timestamp Book',
            'last_modified' => now()->subDay(),
        ]);

        $clientTs = now()->subHours(2)->timestamp;

        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'update',
                    'item' => [
                        'id' => $book->id,
                        'uuid' => $book->uuid,
                        'title' => 'Client Timestamp Book',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => $clientTs,
                    ],
                    'idempotency_key' => 'client-last-modified',
                ],
            ],
        ];

        $this->postJson('/api/sync', $payload)
            ->assertStatus(200);

        $book->refresh();
        $this->assertSame($clientTs, $book->last_modified->timestamp);
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

        if (!SyncConflict::isStorageAvailable()) {
            $list = $this->getJson('/api/sync/conflicts?library_id=' . $library->id);
            $list->assertStatus(200);
            $this->assertCount(0, $list->json('conflicts'));
            return;
        }

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

    public function test_update_fails_when_uuid_unknown(): void
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
                    'op' => 'update',
                    'item' => [
                        'id' => 500,
                        'uuid' => $uuid,
                        'title' => 'Unknown UUID',
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'uuid-update-1',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $payload);
        $response->assertStatus(200);
        $this->assertSame('error', $response->json('results.0.status'));
        $this->assertSame('uuid_not_found', $response->json('results.0.error'));
        $this->assertSame($uuid, $response->json('results.0.uuid'));
        $this->assertDatabaseMissing('books', ['uuid' => $uuid]);
    }

    public function test_create_conflict_when_uuid_already_exists(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuid = (string) Str::uuid();
        UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => $uuid,
            'id' => 600,
            'title' => 'Existing Book',
            'last_modified' => now(),
        ]);

        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 601,
                        'uuid' => $uuid,
                        'title' => 'Duplicate UUID',
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'uuid-create-1',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $payload);
        $response->assertStatus(200);
        $this->assertSame('conflict', $response->json('results.0.status'));
        $this->assertSame('uuid_collision', $response->json('results.0.reason'));
        $this->assertSame($uuid, $response->json('results.0.server_item.uuid'));
    }

    public function test_sync_marks_cover_missing_when_only_hash_provided(): void
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
                        'id' => 400,
                        'uuid' => $uuid,
                        'title' => 'Cover Hash Only',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                        'cover' => [
                            'has_cover' => true,
                            'cover_hash' => 'sha256:' . str_repeat('a', 64),
                            'cover_url' => null,
                        ],
                    ],
                    'idempotency_key' => 'cover-hash-only-1',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $payload);
        $response->assertStatus(200);

        // Expect server to request a cover upload when only hash is provided.
        $this->assertTrue((bool) $response->json('results.0.needs_cover_upload'));
    }

    public function test_sync_marks_ebook_missing_when_files_have_no_storage_key(): void
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
                        'id' => 401,
                        'uuid' => $uuid,
                        'title' => 'File Missing',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                        'files' => [
                            [
                                'format' => 'epub',
                                'name' => 'File Missing.epub',
                                // No storage_key or upload data yet
                            ],
                        ],
                    ],
                    'idempotency_key' => 'file-missing-1',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $payload);
        $response->assertStatus(200);

        // Expect server to flag ebook missing when file metadata is present but not uploaded.
        $this->assertTrue((bool) $response->json('results.0.ebook_missing'));
    }

    public function test_sync_rejects_upload_for_deleted_library(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'deleted_at' => now(),
        ]);
        Sanctum::actingAs($user);

        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 500,
                        'uuid' => (string) Str::uuid(),
                        'title' => 'Deleted Library',
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'deleted-library-1',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $payload);
        $this->assertSame(404, $response->status());
    }

    public function test_sync_does_not_mark_conflict_when_only_missing_flags_change(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $uuid = (string) Str::uuid();
        $createPayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 700,
                        'uuid' => $uuid,
                        'title' => 'Missing Flags',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                        'files' => [
                            ['format' => 'epub', 'name' => 'Missing.epub'],
                        ],
                        'cover' => [
                            'has_cover' => true,
                            'cover_hash' => 'sha256:' . str_repeat('a', 64),
                        ],
                    ],
                    'idempotency_key' => 'missing-flags-1',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $createPayload);
        $response->assertStatus(200);
        $this->assertNotSame('conflict', $response->json('results.0.status'));
    }

    public function test_sync_response_includes_progress_cursor(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 9000,
                        'uuid' => (string) Str::uuid(),
                        'title' => 'Progress Cursor',
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'progress-1',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $payload);
        $response->assertStatus(200);
        $this->assertNotEmpty($response->json('progress_cursor'));
    }

    public function test_sync_accepts_upsert_operation(): void
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
                    'op' => 'upsert',
                    'item' => [
                        'id' => 400,
                        'uuid' => $uuid,
                        'title' => 'Upsert Book',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'upsert-1',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $payload);
        $response->assertStatus(200);
        $this->assertSame('applied', $response->json('results.0.status'));
        $this->assertDatabaseHas('books', [
            'uuid' => $uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
    }

    public function test_sync_detects_uuid_collision_conflict(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $existingUuid = (string) Str::uuid();
        $createPayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 500,
                        'uuid' => $existingUuid,
                        'title' => 'Original',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'collision-1',
                ],
            ],
        ];

        $this->postJson('/api/sync', $createPayload)->assertStatus(200);

        $collisionPayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'changes' => [
                [
                    'op' => 'update',
                    'item' => [
                        'id' => 500,
                        'uuid' => (string) Str::uuid(),
                        'title' => 'Collision',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => now()->timestamp,
                    ],
                    'idempotency_key' => 'collision-2',
                ],
            ],
        ];

        $response = $this->postJson('/api/sync', $collisionPayload);
        $response->assertStatus(200);
        $this->assertSame('error', $response->json('results.0.status'));
        $this->assertNotNull($response->json('results.0.error'));
    }
}
