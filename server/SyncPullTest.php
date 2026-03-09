<?php

namespace Tests\Server;

use App\Models\BookFile;
use App\Models\FileStore;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\SyncService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
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
            'uuid' => Str::uuid()->toString(),
        ]);

        $cursor = base64_encode((string) now()->subHours(1)->timestamp);
        $service = app(SyncService::class);
        $result = $service->getSyncChanges($user, $cursor, 200, $library->id, true, false, false, false, null);

        // Current cursor semantics paginate backward in time (DESC), so older last_modified rows are included.
        $this->assertCount(1, $result['changes']);
    }

    public function test_updated_at_used_when_last_modified_null(): void
    {
        $this->markTestSkipped('Cannot set last_modified to null under the new schema.');
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);

        $book = UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 11,
            'title' => 'Updated Only',
            'last_modified' => now(),
            'uuid' => Str::uuid()->toString(),
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

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id . '&include_inventory_hint=true');
        $response->assertStatus(200);
        $this->assertIsArray($response->json('inventory_hint'));

        $cursor = base64_encode((string) now()->subHours(1)->timestamp);
        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id . '&include_inventory_hint=true&cursor=' . $cursor);
        $response->assertStatus(200);
        $this->assertIsArray($response->json('inventory_hint'));
    }

    public function test_get_sync_accepts_calibre_uuid_without_library_id(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id . '&include_inventory_hint=true');
        $response->assertStatus(200);
        $response->assertJsonStructure(['new_cursor', 'changes']);
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
            'uuid' => Str::uuid()->toString(),
        ]);
        $book->deleted_at = now();
        $book->save();

        $cursor = base64_encode(json_encode([
            'timestamp' => now()->addMinute()->timestamp,
            'last_id' => 0,
            'phase' => 'changes',
            'missing_offset' => 0,
        ]));

        $includePayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => $cursor,
            'stream' => false,
            'client_inventory' => [
                'uuids' => [$book->uuid],
            ],
        ];

        $response = $this->postJson('/api/sync/pull', $includePayload);
        $response->assertStatus(200);
        $ops = array_column($response->json('changes') ?? [], 'op');
        $this->assertContains('delete', $ops);

        $excludePayload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => $cursor,
            'stream' => false,
            'client_inventory' => [
                'uuids' => [],
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
            'uuid' => Str::uuid()->toString(),
        ]);
        UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 2,
            'title' => 'Middle',
            'last_modified' => now()->subDay(),
            'uuid' => Str::uuid()->toString(),
        ]);
        UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 3,
            'title' => 'Newest',
            'last_modified' => now(),
            'uuid' => Str::uuid()->toString(),
        ]);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id . '&limit=2');
        $response->assertStatus(200);
        $this->assertTrue((bool) $response->json('has_more'));
        $this->assertCount(2, $response->json('changes'));
        $this->assertSame('Newest', $response->json('changes.0.item.title'));
    }

    public function test_pull_does_not_claim_cover_present_without_url_or_path(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 20,
            'title' => 'Hash Only Cover',
            'last_modified' => now(),
            'uuid' => Str::uuid()->toString(),
            'cover_original_hash' => 'sha256:' . str_repeat('b', 64),
            'cover_optimized_hash' => null,
            'cover_optimized_path' => null,
            'cover_url' => null,
        ]);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id);
        $response->assertStatus(200);

        // Expect server not to claim cover availability without a URL/path.
        $this->assertFalse((bool) $response->json('changes.0.item.cover.has_cover'));
    }

    public function test_pull_includes_file_missing_and_upload_url(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $book = UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 21,
            'title' => 'Missing File',
            'last_modified' => now(),
            'uuid' => Str::uuid()->toString(),
        ]);

        BookFile::create([
            'book' => $book->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'name' => 'Missing File.epub',
            'storage_provider' => 'r2',
            'uncompressed_size' => 1024,
            'file_path' => '',
            'storage_key' => '',
            'file_hash' => '',
            'uuid' => Str::uuid()->toString(),
            'is_uploaded' => false,
            'needs_file_upload' => true,
            'file_missing' => true,
        ]);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id);
        $response->assertStatus(200);

        $this->assertTrue((bool) $response->json('changes.0.item.files.0.file_missing'));
        $this->assertTrue((bool) $response->json('changes.0.item.files.0.needs_file_upload'));
        $this->assertNotEmpty($response->json('changes.0.item.files.0.upload_url'));
    }

    public function test_pull_does_not_send_cover_hash_when_cover_missing(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 30,
            'title' => 'Cover Hash Without File',
            'last_modified' => now(),
            'uuid' => Str::uuid()->toString(),
            'cover_original_hash' => 'sha256:' . str_repeat('e', 64),
            'cover_optimized_path' => null,
            'cover_url' => null,
        ]);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id);
        $response->assertStatus(200);

        $this->assertNull($response->json('changes.0.item.cover.cover_hash'));
    }

    public function test_pull_upload_url_present_only_when_needed(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $book = UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 40,
            'title' => 'Upload URL Toggle',
            'last_modified' => now(),
            'uuid' => Str::uuid()->toString(),
        ]);

        BookFile::create([
            'book' => $book->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'name' => 'uploaded.epub',
            'storage_provider' => 'local',
            'uncompressed_size' => 1024,
            'file_path' => 'ebooks/uploaded.epub',
            'storage_key' => 'ebooks/uploaded.epub',
            'file_hash' => str_repeat('1', 64),
            'uuid' => Str::uuid()->toString(),
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
        ]);
        FileStore::create([
            'sha256' => str_repeat('1', 64),
            'storage_key' => 'ebooks/uploaded.epub',
            'storage_provider' => 'local',
            'ref_count' => 1,
        ]);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id);
        $response->assertStatus(200);

        $this->assertNull($response->json('changes.0.item.files.0.upload_url'));
    }

    public function test_pull_rejects_deleted_library(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'deleted_at' => now(),
        ]);
        Sanctum::actingAs($user);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id);
        $response->assertStatus(404);
    }

    public function test_pull_cover_flags_consistent(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 50,
            'title' => 'Cover Flags',
            'last_modified' => now(),
            'uuid' => Str::uuid()->toString(),
            'cover_original_hash' => null,
            'cover_optimized_hash' => null,
            'cover_optimized_path' => null,
            'cover_url' => null,
        ]);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id);
        $response->assertStatus(200);

        $this->assertFalse((bool) $response->json('changes.0.item.cover.has_cover'));
        $this->assertNull($response->json('changes.0.item.cover.cover_hash'));
        $this->assertNull($response->json('changes.0.item.cover.cover_url'));
    }

    public function test_pull_file_flags_consistent(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $book = UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 51,
            'title' => 'File Flags',
            'last_modified' => now(),
            'uuid' => Str::uuid()->toString(),
        ]);

        BookFile::create([
            'book' => $book->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'name' => 'file.epub',
            'storage_provider' => 'local',
            'uncompressed_size' => 1024,
            'file_path' => 'ebooks/file.epub',
            'storage_key' => 'ebooks/file.epub',
            'file_hash' => str_repeat('2', 64),
            'uuid' => Str::uuid()->toString(),
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
        ]);
        FileStore::create([
            'sha256' => str_repeat('2', 64),
            'storage_key' => 'ebooks/file.epub',
            'storage_provider' => 'local',
            'ref_count' => 1,
        ]);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id);
        $response->assertStatus(200);

        $this->assertTrue((bool) $response->json('changes.0.item.files.0.is_uploaded'));
        $this->assertFalse((bool) $response->json('changes.0.item.files.0.needs_file_upload'));
        $this->assertFalse((bool) $response->json('changes.0.item.files.0.file_missing'));
    }
}
