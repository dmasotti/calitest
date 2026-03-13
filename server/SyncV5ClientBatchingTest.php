<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncV5ClientBatchingTest extends TestCase
{
    use RefreshDatabase;

    public function test_sync_v5_slices_client_books_with_stable_order_and_cursor(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $payloadBase = [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 50,
            'client_batch_size' => 2,
            'client_books' => [
                'b' => [
                    'uuid-c' => ['m' => 'm3', 'c' => null, 'f' => null, 'lm' => 300],
                    'uuid-a' => ['m' => 'm1', 'c' => null, 'f' => null, 'lm' => 100],
                    'uuid-b' => ['m' => 'm2', 'c' => null, 'f' => null, 'lm' => 200],
                ],
                'd' => [],
            ],
        ];

        $first = $this->postJson('/api/sync/v5', array_merge($payloadBase, [
            'client_cursor' => 0,
        ]));
        $first->assertStatus(200);
        $first->assertJson([
            'client_cursor_next' => 2,
            'client_done' => false,
            'client_books_total' => 3,
            'client_books_processed' => 2,
        ]);
        $this->assertSame(['uuid-a', 'uuid-b'], array_column($first->json('missing_from_server'), 'uuid'));

        $second = $this->postJson('/api/sync/v5', array_merge($payloadBase, [
            'client_cursor' => 2,
        ]));
        $second->assertStatus(200);
        $second->assertJson([
            'client_cursor_next' => 3,
            'client_done' => true,
            'client_books_total' => 3,
            'client_books_processed' => 1,
        ]);
        $this->assertSame(['uuid-c'], array_column($second->json('missing_from_server'), 'uuid'));
    }

    public function test_sync_v5_accepts_pre_sliced_client_chunk_without_second_server_slice(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $book = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => (string) $library->id,
            'title' => 'Chunked Client Book',
            'path' => 'Chunked Client Book',
            'last_modified' => $lastModified,
            'metadata_hash_cache' => 'v2:abc123def456:' . $lastModified->timestamp,
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_cursor' => 500,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => [
                    $book->uuid => ['m' => 'abc123def456', 'lm' => 123],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $response->assertJson([
            'client_cursor_next' => null,
            'client_done' => null,
            'client_books_processed' => 1,
            'client_books_total' => null,
        ]);
    }

    public function test_sync_v5_does_not_mark_done_true_for_first_pre_sliced_chunk(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $books = [];
        for ($i = 1; $i <= 500; $i++) {
            $books['uuid-' . $i] = ['m' => 'h' . $i, 'lm' => $i];
        }

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 50,
            'client_cursor' => 0,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => $books,
                'd' => ['del-1'],
            ],
        ]);

        $response->assertStatus(200);
        $response->assertJson([
            'client_done' => null,
            'client_cursor_next' => null,
            'client_books_total' => null,
            'client_books_processed' => 500,
        ]);
    }

    public function test_sync_v5_keeps_legacy_server_side_slicing_for_full_inventory_payloads(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 50,
            'client_cursor' => 0,
            'client_batch_size' => 3,
            'client_books' => [
                'b' => [
                    'uuid-e' => ['m' => 'm5', 'lm' => 500],
                    'uuid-a' => ['m' => 'm1', 'lm' => 100],
                    'uuid-c' => ['m' => 'm3', 'lm' => 300],
                    'uuid-b' => ['m' => 'm2', 'lm' => 200],
                    'uuid-d' => ['m' => 'm4', 'lm' => 400],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $response->assertJson([
            'client_cursor_next' => 3,
            'client_done' => false,
            'client_books_total' => 5,
            'client_books_processed' => 3,
        ]);
        $this->assertSame(['uuid-a', 'uuid-b', 'uuid-c'], array_column($response->json('missing_from_server'), 'uuid'));
    }
}
