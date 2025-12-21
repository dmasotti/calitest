<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\SyncService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncPullTest extends TestCase
{
    use RefreshDatabase;

    public function test_last_modified_takes_precedence_over_updated_at(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);

        UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 10,
            'title' => 'Old Last Modified',
            'last_modified' => now()->subDay(),
            'updated_at' => now(),
        ]);

        $cursor = base64_encode((string) now()->subHours(1)->timestamp);
        $service = app(SyncService::class);
        $result = $service->getSyncChanges($user, $cursor, 200, $library->id, true, false, false, false, null);

        $this->assertCount(0, $result['changes']);
    }

    public function test_updated_at_used_when_last_modified_null(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);

        $book = UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 11,
            'title' => 'Updated Only',
            'last_modified' => now(),
        ]);

        $book->last_modified = null;
        $book->updated_at = now();
        $book->save();

        $cursor = base64_encode((string) now()->subHours(1)->timestamp);
        $service = app(SyncService::class);
        $result = $service->getSyncChanges($user, $cursor, 200, $library->id, true, false, false, false, null);

        $this->assertCount(1, $result['changes']);
    }

    public function test_inventory_hint_only_on_delta_pages(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $response = $this->getJson('/api/sync?library_id=' . $library->id . '&calibre_library_id=' . $library->calibre_library_id . '&include_inventory_hint=true');
        $response->assertStatus(200);
        $this->assertNull($response->json('inventory_hint'));

        $cursor = base64_encode((string) now()->subHours(1)->timestamp);
        $response = $this->getJson('/api/sync?library_id=' . $library->id . '&calibre_library_id=' . $library->calibre_library_id . '&include_inventory_hint=true&cursor=' . $cursor);
        $response->assertStatus(200);
        $this->assertIsArray($response->json('inventory_hint'));
    }

    public function test_post_pull_filters_tombstones_with_client_inventory(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $book = UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 42,
            'title' => 'Deleted Book',
            'last_modified' => now()->subHour(),
        ]);
        $book->deleted_at = now();
        $book->save();

        $cursor = base64_encode((string) now()->subDay()->timestamp);

        $includePayload = [
            'library_id' => $library->id,
            'calibre_library_id' => $library->calibre_library_id,
            'cursor' => $cursor,
            'client_inventory' => [
                'min' => 42,
                'max' => 42,
                'active' => [42],
                'missing' => [],
            ],
        ];

        $response = $this->postJson('/api/sync/pull', $includePayload);
        $response->assertStatus(200);
        $this->assertSame('delete', $response->json('changes.0.op'));

        $excludePayload = [
            'library_id' => $library->id,
            'calibre_library_id' => $library->calibre_library_id,
            'cursor' => $cursor,
            'client_inventory' => [
                'min' => 42,
                'max' => 42,
                'active' => [],
                'missing' => [42],
            ],
        ];

        $response = $this->postJson('/api/sync/pull', $excludePayload);
        $response->assertStatus(200);
        $this->assertEmpty($response->json('changes'));
    }

    public function test_pagination_and_has_more(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 1,
            'title' => 'Old',
            'last_modified' => now()->subDays(2),
        ]);
        UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 2,
            'title' => 'Middle',
            'last_modified' => now()->subDay(),
        ]);
        UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 3,
            'title' => 'Newest',
            'last_modified' => now(),
        ]);

        $response = $this->getJson('/api/sync?library_id=' . $library->id . '&calibre_library_id=' . $library->calibre_library_id . '&limit=2');
        $response->assertStatus(200);
        $this->assertTrue((bool) $response->json('has_more'));
        $this->assertCount(2, $response->json('changes'));
        $this->assertSame('Newest', $response->json('changes.0.item.title'));
    }
}
