<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Illuminate\Support\Facades\Storage;
use Tests\TestCase;

class CoverUploadTest extends TestCase
{
    use RefreshDatabase;

    public function test_cover_upload_sets_cover_path_and_file_exists()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        // Force local storage path for covers
        config([
            'filesystems.cover_storage.enabled' => false,
            'filesystems.paths.covers.directory' => 'tmp/test-covers',
        ]);

        $coverData = str_repeat('x', 2048);
        $coverHash = 'sha256:' . hash('sha256', $coverData);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.cover.upload', ['id' => $userBook->id]), [
                'library_id' => $library->id,
            ], [], [], [
                'CONTENT_TYPE' => 'image/jpeg',
                'HTTP_X_COVER_HASH' => $coverHash,
            ], $coverData);

        $response->assertOk();
        $response->assertJsonFragment(['cover_hash' => $coverHash]);

        $userBook->refresh();
        $this->assertTrue((bool) $userBook->has_cover);
        $this->assertNotEmpty($userBook->cover_optimized_path ?? $userBook->cover_url);

        $relativePath = $userBook->cover_optimized_path ?? null;
        if ($relativePath) {
            $fullPath = base_path($relativePath);
            $this->assertFileExists($fullPath);
        }
    }

    public function test_cover_upload_uuid_endpoint_uses_calibre_library_uuid()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        config([
            'filesystems.cover_storage.enabled' => false,
            'filesystems.paths.covers.directory' => 'tmp/test-covers',
        ]);

        $coverData = str_repeat('u', 2048);
        $coverHash = 'sha256:' . hash('sha256', $coverData);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.cover.upload.uuid', [
                'uuid' => $userBook->uuid,
                'calibre_library_uuid' => $library->calibre_library_id,
            ]), [], [], [], [
                'CONTENT_TYPE' => 'image/jpeg',
                'HTTP_X_COVER_HASH' => $coverHash,
            ], $coverData);

        $response->assertOk();
        $response->assertJsonFragment(['cover_hash' => $coverHash]);
    }

    public function test_cover_upload_sets_cover_url_when_r2_enabled()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        config([
            'filesystems.cover_storage.enabled' => true,
            'filesystems.cover_storage.provider' => 'r2',
            'filesystems.cover_storage.public_url' => 'https://cdn.example.test',
        ]);

        // Inject StorageCoverService mock used by CoverHandler
        $mock = \Mockery::mock(\App\Services\StorageCoverService::class);
        $mock->shouldReceive('coverExists')->andReturn(false);
        $mock->shouldReceive('uploadCover')->andReturn('https://cdn.example.test/covers/test.jpg');
        $this->app->instance(\App\Services\StorageCoverService::class, $mock);

        $coverData = str_repeat('y', 2048);
        $coverHash = 'sha256:' . hash('sha256', $coverData);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.cover.upload', ['id' => $userBook->id]), [
                'library_id' => $library->id,
            ], [], [], [
                'CONTENT_TYPE' => 'image/jpeg',
                'HTTP_X_COVER_HASH' => $coverHash,
            ], $coverData);

        $response->assertOk();
        $response->assertJsonFragment(['cover_url' => 'https://cdn.example.test/covers/test.jpg']);

        $userBook->refresh();
        $this->assertEquals('https://cdn.example.test/covers/test.jpg', $userBook->cover_url);
        $this->assertTrue((bool) $userBook->has_cover);
    }

    public function test_cover_upload_clears_missing_flag_after_hash_only()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'cover_original_hash' => 'sha256:' . str_repeat('c', 64),
            'cover_missing' => true,
        ]);

        config([
            'filesystems.cover_storage.enabled' => false,
            'filesystems.paths.covers.directory' => 'tmp/test-covers',
        ]);

        $coverData = str_repeat('z', 2048);
        $coverHash = 'sha256:' . hash('sha256', $coverData);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.cover.upload', ['id' => $userBook->id]), [
                'library_id' => $library->id,
            ], [], [], [
                'CONTENT_TYPE' => 'image/jpeg',
                'HTTP_X_COVER_HASH' => $coverHash,
            ], $coverData);

        $response->assertOk();

        $userBook->refresh();
        $this->assertFalse((bool) $userBook->cover_missing);
        $this->assertTrue((bool) $userBook->has_cover);
    }

    public function test_cover_get_marks_missing_when_file_absent()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'cover_optimized_path' => 'images/covers/missing.jpg',
            'cover_missing' => false,
        ]);

        $response = $this->actingAs($user)->get('/api/items/' . $userBook->id . '/cover?library_id=' . $library->id);
        $response->assertStatus(200);
        $response->assertJsonFragment(['cover_missing' => true]);

        $userBook->refresh();
        $this->assertTrue((bool) $userBook->cover_missing);
    }

    public function test_cover_get_uuid_endpoint_marks_missing_when_file_absent()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'cover_optimized_path' => 'images/covers/missing.jpg',
            'cover_missing' => false,
        ]);

        $response = $this->actingAs($user)->get(
            '/api/items/uuid/' . $userBook->uuid . '/cover?calibre_library_uuid=' . $library->calibre_library_id
        );
        $response->assertStatus(200);
        $response->assertJsonFragment(['cover_missing' => true]);

        $userBook->refresh();
        $this->assertTrue((bool) $userBook->cover_missing);
    }

    public function test_cover_get_rejects_deleted_book()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'deleted_at' => now(),
            'cover_optimized_path' => 'images/covers/deleted.jpg',
        ]);

        $response = $this->actingAs($user)->get('/api/items/' . $userBook->id . '/cover?library_id=' . $library->id);
        $response->assertStatus(404);
    }

    public function test_cover_get_marks_missing_on_hash_url_mismatch()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'cover_original_hash' => 'sha256:' . str_repeat('f', 64),
            'cover_optimized_path' => null,
            'cover_url' => 'https://cdn.example.test/covers/bad.jpg',
            'cover_missing' => false,
        ]);

        $response = $this->actingAs($user)->get('/api/items/' . $userBook->id . '/cover?library_id=' . $library->id);
        $response->assertStatus(200);

        $userBook->refresh();
        $this->assertTrue((bool) $userBook->cover_missing);
    }

    public function test_cover_upload_rejects_deleted_book()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'deleted_at' => now(),
        ]);

        $coverData = str_repeat('x', 1024);
        $coverHash = 'sha256:' . hash('sha256', $coverData);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.cover.upload', ['id' => $userBook->id]), [
                'library_id' => $library->id,
            ], [], [], [
                'CONTENT_TYPE' => 'image/jpeg',
                'HTTP_X_COVER_HASH' => $coverHash,
            ], $coverData);

        $response->assertStatus(404);
    }

    public function test_repeat_cover_upload_is_idempotent()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        config([
            'filesystems.cover_storage.enabled' => false,
            'filesystems.paths.covers.directory' => 'tmp/test-covers',
        ]);

        $coverData = str_repeat('k', 2048);
        $coverHash = 'sha256:' . hash('sha256', $coverData);

        $this->actingAs($user)->call('PUT', route('api.items.cover.upload', ['id' => $userBook->id]), [
            'library_id' => $library->id,
        ], [], [], [
            'CONTENT_TYPE' => 'image/jpeg',
            'HTTP_X_COVER_HASH' => $coverHash,
        ], $coverData)->assertOk();

        $first = $userBook->fresh();
        $firstPath = $first->cover_optimized_path;

        $this->actingAs($user)->call('PUT', route('api.items.cover.upload', ['id' => $userBook->id]), [
            'library_id' => $library->id,
        ], [], [], [
            'CONTENT_TYPE' => 'image/jpeg',
            'HTTP_X_COVER_HASH' => $coverHash,
        ], $coverData)->assertOk();

        $second = $userBook->fresh();
        $this->assertSame($firstPath, $second->cover_optimized_path);
    }
}
