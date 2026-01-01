<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class ProtocolCursorTest extends TestCase
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

    public function test_cursor_monotonicity(): void
    {
        [, $library, $calibreUuid] = $this->setupUserAndLibrary();

        $uuid = (string) Str::uuid();
        $ts1 = now()->timestamp;
        $payload1 = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'id' => 301,
                        'uuid' => $uuid,
                        'title' => 'Cursor Test',
                        'authors' => [['name' => 'Tester', 'role' => 'author']],
                        'last_modified' => $ts1,
                    ],
                    'idempotency_key' => 'idem-cursor-1',
                ],
            ],
        ];

        $response1 = $this->postJson('/api/sync', $payload1);
        $response1->assertStatus(200);
        $cursor1 = $response1->json('new_cursor');
        $this->assertNotEmpty($cursor1);

        $ts2 = $ts1 + 10;
        $payload2 = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $calibreUuid,
            'changes' => [
                [
                    'op' => 'update',
                    'item' => [
                        'id' => 301,
                        'uuid' => $uuid,
                        'title' => 'Cursor Test Updated',
                        'last_modified' => $ts2,
                    ],
                    'idempotency_key' => 'idem-cursor-2',
                ],
            ],
        ];

        $response2 = $this->postJson('/api/sync', $payload2);
        $response2->assertStatus(200);
        $cursor2 = $response2->json('new_cursor');
        $this->assertNotEmpty($cursor2);

        $decoded1 = (int) base64_decode($cursor1);
        $decoded2 = (int) base64_decode($cursor2);
        $this->assertGreaterThan($decoded1, $decoded2);
    }
}
