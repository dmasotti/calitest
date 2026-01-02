<?php

namespace Tests\Server;

use App\Models\BookFile;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\EbookStorageService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Config;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use Tests\TestCase;

class FileDownloadTest extends TestCase
{
    use RefreshDatabase;

    public function test_redirects_to_signed_url_when_storage_key_present()
    {
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
            'storage_key' => 'ebooks/test.epub',
            'storage_provider' => 'r2',
            'is_uploaded' => true,
            'name' => 'test.epub',
            'uuid' => Str::uuid()->toString(),
        ]);

        Config::set('filesystems.ebook_storage.enabled', true);
        Config::set('filesystems.ebook_storage.provider', 'r2');
        Config::set('filesystems.ebook_storage.bucket', 'test');
        Config::set('filesystems.ebook_storage.endpoint', 'https://example.test');
        Config::set('filesystems.ebook_storage.key', 'key');
        Config::set('filesystems.ebook_storage.secret', 'secret');
        Config::set('filesystems.ebook_storage.region', 'auto');

        $mockService = \Mockery::mock(EbookStorageService::class);
        $mockService->shouldReceive('getSignedUrl')
            ->once()
            ->with('ebooks/test.epub', \Mockery::any(), 'test.epub')
            ->andReturn('https://signed.example/test.epub');

        $this->app->instance(EbookStorageService::class, $mockService);

        $response = $this->actingAs($user)
            ->get(route('files.ebook.download', ['userBook' => $userBook->uuid]) . '?format=epub');

        $response->assertRedirect('https://signed.example/test.epub');
    }

    public function test_streams_local_file_when_no_storage_key()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $filePath = 'ebooks/local-test.epub';
        $fileContents = str_repeat('a', 1024);
        Storage::disk('local')->put($filePath, $fileContents);
        $fileHash = hash('sha256', $fileContents);

        BookFile::factory()->create([
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'file_path' => $filePath,
            'storage_key' => '',
            'is_uploaded' => false,
            'name' => 'local-test.epub',
            'file_hash' => $fileHash,
            'uuid' => Str::uuid()->toString(),
        ]);

        $response = $this->actingAs($user)
            ->get(route('files.ebook.download', ['userBook' => $userBook->uuid]) . '?format=epub');

        $response->assertOk();
        $response->assertHeader('content-disposition', 'attachment; filename=local-test.epub');
    }

    public function test_download_missing_file_marks_missing_flag()
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
            'file_path' => 'missing/book.epub',
            'storage_key' => '',
            'storage_provider' => 'local',
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
            'name' => 'missing.epub',
            'uuid' => Str::uuid()->toString(),
        ]);

        $response = $this->actingAs($user)
            ->get(route('files.ebook.download', ['userBook' => $userBook->uuid]) . '?format=epub');

        $response->assertStatus(404);

        $file = BookFile::where('book', $userBook->uuid)->where('format', 'EPUB')->firstOrFail();
        $this->assertTrue((bool) $file->file_missing);
    }

    public function test_download_rejects_deleted_book()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'deleted_at' => now(),
        ]);

        BookFile::factory()->create([
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'file_path' => 'ebooks/deleted.epub',
            'storage_key' => '',
            'storage_provider' => 'local',
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
            'name' => 'deleted.epub',
            'uuid' => Str::uuid()->toString(),
        ]);

        $response = $this->actingAs($user)
            ->get(route('files.ebook.download', ['userBook' => $userBook->uuid]) . '?format=epub');

        $response->assertStatus(404);
    }

    public function test_download_marks_missing_on_hash_mismatch()
    {
        Storage::fake('local');

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $filePath = 'ebooks/mismatch.epub';
        Storage::disk('local')->put($filePath, 'real content');

        BookFile::factory()->create([
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'file_path' => $filePath,
            'storage_key' => '',
            'storage_provider' => 'local',
            'file_hash' => str_repeat('0', 64),
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
            'name' => 'mismatch.epub',
            'uuid' => Str::uuid()->toString(),
        ]);

        $response = $this->actingAs($user)
            ->get(route('files.ebook.download', ['userBook' => $userBook->uuid]) . '?format=epub');

        $response->assertStatus(404);

        $file = BookFile::where('book', $userBook->uuid)->where('format', 'EPUB')->firstOrFail();
        $this->assertTrue((bool) $file->file_missing);
    }
}
