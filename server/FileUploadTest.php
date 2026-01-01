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
            'book' => $userBook->id,
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
            ->call('PUT', route('api.items.file.upload', ['id' => $userBook->id, 'format' => 'epub']), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'uploaded.epub',
            ], $content);

        $response->assertOk();
        $response->assertJsonFragment(['needs_file_upload' => false]);

        $file = BookFile::where('book', $userBook->id)
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
            'book' => $userBook->id,
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
            'book' => $userBook->id,
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
            ->call('PUT', route('api.items.file.upload', ['id' => $userBook->id, 'format' => 'epub']), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'uploaded.epub',
            ], $content);

        $response->assertOk();

        $file = BookFile::where('book', $userBook->id)
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
            'book' => $userBook->id,
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
            ->call('PUT', route('api.items.file.upload', ['id' => $userBook->id, 'format' => 'epub']), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'uploaded.epub',
            ], $content);

        $response->assertOk();

        $file = BookFile::where('book', $userBook->id)
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
            'book' => $userBook->id,
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

        $this->actingAs($user)->call('PUT', route('api.items.file.upload', ['id' => $userBook->id, 'format' => 'epub']), [], [], [], [
            'CONTENT_TYPE' => 'application/octet-stream',
            'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
            'HTTP_X_FILE_NAME' => 'uploaded.epub',
        ], $content)->assertOk();

        $first = BookFile::where('book', $userBook->id)->where('format', 'EPUB')->firstOrFail();
        $firstKey = $first->storage_key;

        $this->actingAs($user)->call('PUT', route('api.items.file.upload', ['id' => $userBook->id, 'format' => 'epub']), [], [], [], [
            'CONTENT_TYPE' => 'application/octet-stream',
            'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
            'HTTP_X_FILE_NAME' => 'uploaded.epub',
        ], $content)->assertOk();

        $second = BookFile::where('book', $userBook->id)->where('format', 'EPUB')->firstOrFail();
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
            ->call('PUT', route('api.items.file.upload', ['id' => $userBook->id, 'format' => 'epub']), [], [], [], [
                'CONTENT_TYPE' => 'application/octet-stream',
                'HTTP_X_FILE_HASH' => 'sha256:' . $hash,
                'HTTP_X_FILE_NAME' => 'uploaded.epub',
            ], $content);

        $response->assertStatus(404);
    }
}
