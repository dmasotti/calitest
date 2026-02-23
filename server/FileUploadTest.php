<?php

namespace Tests\Server;

use App\Models\BookFile;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use Tests\TestCase;

class FileUploadTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        config(['filesystems.ebook_storage.enabled' => false]);
    }

    public function test_file_upload_endpoint_marks_file_uploaded()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        BookFile::factory()->create([
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'storage_provider' => 'local',
            'storage_key' => '',
            'file_path' => '',
            'file_hash' => '',
            'is_uploaded' => false,
            'needs_file_upload' => true,
            'file_missing' => true,
        ]);

        $content = 'ebook binary payload';
        $hash = hash('sha256', $content);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.file.upload.uuid', ['uuid' => $userBook->uuid, 'format' => 'epub', 'calibre_library_uuid' => $library->calibre_library_id]), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'uploaded.epub',
            ], $content);

        $response->assertOk();
        $response->assertJsonFragment(['needs_file_upload' => false]);

        $file = BookFile::where('book', $userBook->uuid)
            ->where('format', 'EPUB')
            ->firstOrFail();

        $this->assertTrue((bool) $file->is_uploaded);
        $this->assertFalse($file->needs_file_upload);
        $this->assertFalse($file->file_missing);
        $this->assertNotEmpty($file->storage_key);
        Storage::disk('local')->assertExists($file->storage_key);
    }

    public function test_file_upload_uuid_endpoint_marks_file_uploaded()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        BookFile::factory()->create([
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'storage_provider' => 'local',
            'storage_key' => '',
            'file_path' => '',
            'file_hash' => '',
            'is_uploaded' => false,
            'needs_file_upload' => true,
            'file_missing' => true,
        ]);

        $content = 'ebook uuid upload payload';
        $hash = hash('sha256', $content);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.file.upload.uuid', [
                'uuid' => $userBook->uuid,
                'format' => 'epub',
                'calibre_library_uuid' => $library->calibre_library_id,
            ]), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'uploaded.epub',
            ], $content);

        $response->assertOk();
        $response->assertJsonFragment(['needs_file_upload' => false]);
    }

    public function test_file_upload_clears_missing_flags_and_sets_provider()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        BookFile::factory()->create([
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'storage_provider' => 'local',
            'storage_key' => '',
            'file_path' => '',
            'file_hash' => '',
            'is_uploaded' => false,
            'needs_file_upload' => true,
            'file_missing' => true,
        ]);

        $content = 'ebook upload payload';
        $hash = hash('sha256', $content);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.file.upload.uuid', ['uuid' => $userBook->uuid, 'format' => 'epub', 'calibre_library_uuid' => $library->calibre_library_id]), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'uploaded.epub',
            ], $content);

        $response->assertOk();

        $file = BookFile::where('book', $userBook->uuid)
            ->where('format', 'EPUB')
            ->firstOrFail();

        $this->assertTrue((bool) $file->is_uploaded);
        $this->assertFalse($file->needs_file_upload);
        $this->assertFalse($file->file_missing);
        $this->assertSame('local', $file->storage_provider);
        $this->assertNotEmpty($file->storage_key);
    }

    public function test_file_upload_sets_provider_from_env_when_missing()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        BookFile::factory()->create([
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'storage_provider' => 'r2',
            'storage_key' => '',
            'file_path' => '',
            'file_hash' => '',
            'is_uploaded' => false,
            'needs_file_upload' => true,
            'file_missing' => true,
        ]);

        $content = 'ebook storage provider test';
        $hash = hash('sha256', $content);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.file.upload.uuid', ['uuid' => $userBook->uuid, 'format' => 'epub', 'calibre_library_uuid' => $library->calibre_library_id]), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'uploaded.epub',
            ], $content);

        $response->assertOk();

        $file = BookFile::where('book', $userBook->uuid)
            ->where('format', 'EPUB')
            ->firstOrFail();

        $this->assertNotEmpty($file->storage_provider);
    }

    public function test_repeat_upload_with_same_hash_is_idempotent()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        BookFile::factory()->create([
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'storage_provider' => 'local',
            'storage_key' => '',
            'file_path' => '',
            'file_hash' => '',
            'is_uploaded' => false,
            'needs_file_upload' => true,
            'file_missing' => true,
        ]);

        $content = 'repeat upload payload';
        $hash = hash('sha256', $content);

        $this->actingAs($user)->call('PUT', route('api.items.file.upload.uuid', ['uuid' => $userBook->uuid, 'format' => 'epub', 'calibre_library_uuid' => $library->calibre_library_id]), [], [], [], [
            'CONTENT_TYPE' => 'application/octet-stream',
            'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
            'HTTP_X_FILE_NAME' => 'uploaded.epub',
        ], $content)->assertOk();

        $first = BookFile::where('book', $userBook->uuid)->where('format', 'EPUB')->firstOrFail();
        $firstKey = $first->storage_key;

        $this->actingAs($user)->call('PUT', route('api.items.file.upload.uuid', ['uuid' => $userBook->uuid, 'format' => 'epub', 'calibre_library_uuid' => $library->calibre_library_id]), [], [], [], [
            'CONTENT_TYPE' => 'application/octet-stream',
            'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
            'HTTP_X_FILE_NAME' => 'uploaded.epub',
        ], $content)->assertOk();

        $second = BookFile::where('book', $userBook->uuid)->where('format', 'EPUB')->firstOrFail();
        $this->assertSame($firstKey, $second->storage_key);
    }

    public function test_file_upload_rejects_deleted_book()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'deleted_at' => now(),
        ]);

        $content = 'payload';
        $hash = hash('sha256', $content);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.file.upload.uuid', ['uuid' => $userBook->uuid, 'format' => 'epub', 'calibre_library_uuid' => $library->calibre_library_id]), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'uploaded.epub',
            ], $content);

        $response->assertStatus(404);
    }

    public function test_file_upload_creates_uuid_and_uses_book_uuid()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $content = 'uuid insert payload';
        $hash = hash('sha256', $content);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.file.upload.uuid', [
                'uuid' => $userBook->uuid,
                'format' => 'epub',
                'calibre_library_uuid' => $library->calibre_library_id,
            ]), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'uploaded.epub',
            ], $content);

        $response->assertOk();

        $file = BookFile::where('book', $userBook->uuid)
            ->where('format', 'EPUB')
            ->firstOrFail();

        $this->assertSame($userBook->uuid, $file->book);
        $this->assertNotEmpty($file->uuid);
    }

    public function test_file_upload_with_invalid_utf8_filename_does_not_500()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        // Intentionally invalid UTF-8 bytes in header value (ISO-8859-1 bytes)
        $badName = "Asesinato en el coraz\xF3n Jersusal\xE9n.epub";
        $content = 'utf8 header robustness payload';
        $hash = hash('sha256', $content);

        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.file.upload.uuid', [
                'uuid' => $userBook->uuid,
                'format' => 'epub',
                'calibre_library_uuid' => $library->calibre_library_id,
            ]), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => $badName,
            ], $content);

        // Server must not crash with "Malformed UTF-8" and should return JSON
        $response->assertStatus(200);
        $response->assertJsonStructure(['format', 'file_hash', 'storage_key']);
    }

    public function test_file_upload_preserves_client_last_modified()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        // Set a specific last_modified timestamp
        $clientTimestamp = strtotime('2025-02-20 14:45:00');
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'last_modified' => date('Y-m-d H:i:s', $clientTimestamp),
        ]);

        BookFile::factory()->create([
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'storage_provider' => 'local',
            'storage_key' => '',
            'file_path' => '',
            'file_hash' => '',
            'is_uploaded' => false,
            'needs_file_upload' => true,
            'file_missing' => true,
        ]);

        $content = 'test file content';
        $hash = hash('sha256', $content);

        // Upload file with X-Last-Modified header
        $response = $this->actingAs($user)
            ->call('PUT', route('api.items.file.upload.uuid', [
                'uuid' => $userBook->uuid,
                'format' => 'epub',
                'calibre_library_uuid' => $library->calibre_library_id,
            ]), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'test.epub',
                'HTTP_X_LAST_MODIFIED' => (string) $clientTimestamp,
            ], $content);

        $response->assertOk();

        // Verify last_modified was preserved (not updated to now())
        $userBook->refresh();
        $savedTimestamp = strtotime($userBook->last_modified);
        
        // Should match client timestamp (within 1 second tolerance)
        $this->assertEqualsWithDelta($clientTimestamp, $savedTimestamp, 1, 
            'Server should preserve client last_modified timestamp');
        
        // Should NOT be close to now()
        $now = time();
        $this->assertGreaterThan(10, abs($now - $savedTimestamp),
            'Server should not update last_modified to now()');
    }
}
