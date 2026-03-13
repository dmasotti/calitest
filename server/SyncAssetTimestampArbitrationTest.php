<?php

namespace Tests\Server;

use App\Models\BookFile;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\CoverHandler;
use App\Services\SyncService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Tests\TestCase;

class SyncAssetTimestampArbitrationTest extends TestCase
{
    use RefreshDatabase;

    public function test_cover_upload_is_not_requested_when_server_cover_is_newer_than_client_item(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'cover_url' => 'https://cdn.example.test/covers/server.jpg',
            'cover_missing' => false,
            'has_cover' => true,
        ]);

        $needsUpload = app(CoverHandler::class)->checkIfCoverUploadNeeded([
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
            'cover' => [
                'has_cover' => true,
                'cover_hash' => 'sha256:' . str_repeat('b', 64),
            ],
        ], $userBook->fresh());

        $this->assertFalse(
            $needsUpload,
            'Older client cover mismatch should not force upload over a newer server cover.'
        );
    }

    public function test_cover_upload_is_requested_when_client_cover_is_newer_than_server_cover(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(200),
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'cover_url' => 'https://cdn.example.test/covers/server.jpg',
            'cover_missing' => false,
            'has_cover' => true,
        ]);

        $needsUpload = app(CoverHandler::class)->checkIfCoverUploadNeeded([
            'uuid' => $userBook->uuid,
            'last_modified' => 300,
            'cover' => [
                'has_cover' => true,
                'cover_hash' => 'sha256:' . str_repeat('b', 64),
            ],
        ], $userBook->fresh());

        $this->assertTrue($needsUpload);
    }

    public function test_cover_upload_uses_nested_timestamp_when_top_level_is_missing(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'cover_url' => 'https://cdn.example.test/covers/server.jpg',
            'cover_missing' => false,
            'has_cover' => true,
        ]);

        $needsUpload = app(CoverHandler::class)->checkIfCoverUploadNeeded([
            'uuid' => $userBook->uuid,
            'timestamps' => [
                'last_modified' => 200,
            ],
            'cover' => [
                'has_cover' => true,
                'cover_hash' => 'sha256:' . str_repeat('b', 64),
            ],
        ], $userBook->fresh());

        $this->assertFalse($needsUpload);
    }

    public function test_cover_missing_flag_still_forces_upload_even_if_client_is_older(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'cover_url' => 'https://cdn.example.test/covers/server.jpg',
            'cover_missing' => true,
            'has_cover' => true,
        ]);

        $needsUpload = app(CoverHandler::class)->checkIfCoverUploadNeeded([
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
            'cover' => [
                'has_cover' => true,
                'cover_hash' => 'sha256:' . str_repeat('a', 64),
            ],
        ], $userBook->fresh());

        $this->assertTrue($needsUpload);
    }

    public function test_cover_upload_is_not_requested_when_client_has_no_cover_hash(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'cover_url' => 'https://cdn.example.test/covers/server.jpg',
            'cover_missing' => false,
            'has_cover' => true,
        ]);

        $needsUpload = app(CoverHandler::class)->checkIfCoverUploadNeeded([
            'uuid' => $userBook->uuid,
            'last_modified' => 400,
            'cover' => [
                'has_cover' => true,
                'cover_hash' => null,
            ],
        ], $userBook->fresh());

        $this->assertFalse($needsUpload);
    }

    public function test_cover_upload_is_not_requested_when_client_has_no_cover(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'cover_url' => 'https://cdn.example.test/covers/server.jpg',
            'cover_missing' => false,
            'has_cover' => true,
        ]);

        $needsUpload = app(CoverHandler::class)->checkIfCoverUploadNeeded([
            'uuid' => $userBook->uuid,
            'last_modified' => 400,
            'cover' => [
                'has_cover' => false,
            ],
        ], $userBook->fresh());

        $this->assertFalse($needsUpload);
    }

    public function test_cover_upload_clears_stale_cover_missing_when_hashes_match_and_server_cover_exists(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'cover_url' => 'https://cdn.example.test/covers/server.jpg',
            'cover_missing' => false,
            'has_cover' => true,
        ]);

        $needsUpload = app(CoverHandler::class)->checkIfCoverUploadNeeded([
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
            'cover' => [
                'has_cover' => true,
                'cover_hash' => 'sha256:' . str_repeat('a', 64),
            ],
        ], $userBook->fresh());

        $this->assertFalse($needsUpload);
        $this->assertFalse((bool) $userBook->fresh()->cover_missing);
    }

    public function test_cover_upload_is_requested_when_server_has_no_cover_hash_even_if_client_is_older(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'cover_original_hash' => null,
            'cover_url' => null,
            'cover_missing' => false,
            'has_cover' => false,
        ]);

        $needsUpload = app(CoverHandler::class)->checkIfCoverUploadNeeded([
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
            'cover' => [
                'has_cover' => true,
                'cover_hash' => 'sha256:' . str_repeat('a', 64),
            ],
        ], $userBook->fresh());

        $this->assertTrue($needsUpload);
    }

    public function test_cover_upload_is_not_requested_when_hashes_match_even_if_client_is_newer(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(200),
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'cover_url' => 'https://cdn.example.test/covers/server.jpg',
            'cover_missing' => false,
            'has_cover' => true,
        ]);

        $needsUpload = app(CoverHandler::class)->checkIfCoverUploadNeeded([
            'uuid' => $userBook->uuid,
            'last_modified' => 400,
            'cover' => [
                'has_cover' => true,
                'cover_hash' => 'sha256:' . str_repeat('a', 64),
            ],
        ], $userBook->fresh());

        $this->assertFalse($needsUpload);
    }

    public function test_file_upload_is_requested_when_client_file_is_newer_and_hash_differs(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(200),
        ]);

        BookFile::create([
            'book' => $userBook->uuid,
            'format' => 'EPUB',
            'name' => 'Server copy.epub',
            'uncompressed_size' => 1024,
            'file_path' => 'server-copy.epub',
            'file_hash' => str_repeat('a', 64),
            'storage_key' => 'ebooks/server-copy.epub',
            'storage_provider' => 'local',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 300,
            'files' => [
                [
                    'format' => 'EPUB',
                    'file_hash' => 'sha256:' . str_repeat('b', 64),
                ],
            ],
        ]);

        $this->assertTrue(
            (bool) ($status['ebook_missing'] ?? false),
            'Newer client file mismatch should request upload.'
        );
        $this->assertSame('file_missing_or_not_uploaded', $status['reason'] ?? null);
        $this->assertNotEmpty($status['uploads'] ?? []);
        $this->assertSame('EPUB', $status['uploads'][0]['format'] ?? null);
    }

    public function test_file_upload_is_requested_when_server_has_no_file_row_even_if_client_is_older(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
            'files' => [
                [
                    'format' => 'EPUB',
                    'file_hash' => 'sha256:' . str_repeat('b', 64),
                ],
            ],
        ]);

        $this->assertTrue((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('file_missing_or_not_uploaded', $status['reason'] ?? null);
        $this->assertCount(1, $status['uploads'] ?? []);
    }

    public function test_file_upload_is_not_requested_when_server_file_is_newer_than_client_item(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
        ]);

        BookFile::create([
            'book' => $userBook->uuid,
            'format' => 'EPUB',
            'name' => 'Server copy.epub',
            'uncompressed_size' => 1024,
            'file_path' => 'server-copy.epub',
            'file_hash' => str_repeat('a', 64),
            'storage_key' => 'ebooks/server-copy.epub',
            'storage_provider' => 'local',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
            'files' => [
                [
                    'format' => 'EPUB',
                    'file_hash' => 'sha256:' . str_repeat('b', 64),
                ],
            ],
        ]);

        $this->assertFalse((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('files_present', $status['reason'] ?? null);
        $this->assertSame([], $status['uploads'] ?? []);
    }

    public function test_file_upload_uses_nested_timestamp_when_top_level_is_missing(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
        ]);

        BookFile::create([
            'book' => $userBook->uuid,
            'format' => 'EPUB',
            'name' => 'Server copy.epub',
            'uncompressed_size' => 1024,
            'file_path' => 'server-copy.epub',
            'file_hash' => str_repeat('a', 64),
            'storage_key' => 'ebooks/server-copy.epub',
            'storage_provider' => 'local',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'timestamps' => [
                'last_modified' => 200,
            ],
            'files' => [
                [
                    'format' => 'EPUB',
                    'file_hash' => 'sha256:' . str_repeat('b', 64),
                ],
            ],
        ]);

        $this->assertFalse((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('files_present', $status['reason'] ?? null);
        $this->assertSame([], $status['uploads'] ?? []);
    }

    public function test_file_upload_is_not_requested_when_item_has_no_files_and_server_file_is_ready(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'ebook_missing' => false,
        ]);

        BookFile::create([
            'book' => $userBook->uuid,
            'format' => 'EPUB',
            'name' => 'Server copy.epub',
            'uncompressed_size' => 1024,
            'file_path' => 'server-copy.epub',
            'file_hash' => str_repeat('a', 64),
            'storage_key' => 'ebooks/server-copy.epub',
            'storage_provider' => 'local',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
        ]);

        $this->assertFalse((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('no_files_in_item', $status['reason'] ?? null);
        $this->assertSame([], $status['uploads'] ?? []);
    }

    public function test_file_upload_is_requested_when_item_has_no_files_but_server_file_needs_upload(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'ebook_missing' => false,
        ]);

        BookFile::create([
            'book' => $userBook->uuid,
            'format' => 'EPUB',
            'name' => 'Pending.epub',
            'uncompressed_size' => 1024,
            'file_path' => 'pending.epub',
            'file_hash' => str_repeat('a', 64),
            'storage_key' => '',
            'storage_provider' => 'local',
            'is_uploaded' => false,
            'file_missing' => true,
            'needs_file_upload' => true,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
        ]);

        $this->assertTrue((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('existing_files_need_upload', $status['reason'] ?? null);
        $this->assertCount(1, $status['uploads'] ?? []);
        $this->assertSame('EPUB', $status['uploads'][0]['format'] ?? null);
    }

    public function test_file_upload_treats_explicit_empty_files_array_like_no_files_payload(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'ebook_missing' => false,
        ]);

        BookFile::create([
            'book' => $userBook->uuid,
            'format' => 'EPUB',
            'name' => 'Server copy.epub',
            'uncompressed_size' => 1024,
            'file_path' => 'server-copy.epub',
            'file_hash' => str_repeat('a', 64),
            'storage_key' => 'ebooks/server-copy.epub',
            'storage_provider' => 'local',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
            'files' => [],
        ]);

        $this->assertFalse((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('no_files_in_item', $status['reason'] ?? null);
        $this->assertSame([], $status['uploads'] ?? []);
    }

    public function test_file_upload_clears_stale_ebook_missing_flag_when_server_files_are_ready_and_item_has_no_files(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'ebook_missing' => true,
        ]);

        BookFile::create([
            'book' => $userBook->uuid,
            'format' => 'EPUB',
            'name' => 'Server copy.epub',
            'uncompressed_size' => 1024,
            'file_path' => 'server-copy.epub',
            'file_hash' => str_repeat('a', 64),
            'storage_key' => 'ebooks/server-copy.epub',
            'storage_provider' => 'local',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
        ]);

        $this->assertFalse((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('no_files_in_item', $status['reason'] ?? null);
        $this->assertSame([], $status['uploads'] ?? []);
        $this->assertFalse((bool) $userBook->fresh()->ebook_missing);
    }

    public function test_file_upload_clears_stale_ebook_missing_flag_when_no_server_file_rows_exist(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
            'ebook_missing' => true,
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
        ]);

        $this->assertFalse((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('no_files_in_item', $status['reason'] ?? null);
        $this->assertSame([], $status['uploads'] ?? []);
        $this->assertFalse((bool) $userBook->fresh()->ebook_missing);
    }

    public function test_file_upload_matches_existing_file_when_payload_format_is_lowercase(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
        ]);

        BookFile::create([
            'book' => $userBook->uuid,
            'format' => 'EPUB',
            'name' => 'Server copy.epub',
            'uncompressed_size' => 1024,
            'file_path' => 'server-copy.epub',
            'file_hash' => str_repeat('a', 64),
            'storage_key' => 'ebooks/server-copy.epub',
            'storage_provider' => 'local',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
            'files' => [
                [
                    'format' => 'epub',
                    'file_hash' => 'sha256:' . str_repeat('b', 64),
                ],
            ],
        ]);

        $this->assertFalse((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('files_present', $status['reason'] ?? null);
        $this->assertSame([], $status['uploads'] ?? []);
    }

    public function test_file_upload_handles_mixed_formats_with_only_missing_one_requested(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
        ]);

        BookFile::create([
            'book' => $userBook->uuid,
            'format' => 'EPUB',
            'name' => 'Server copy.epub',
            'uncompressed_size' => 1024,
            'file_path' => 'server-copy.epub',
            'file_hash' => str_repeat('a', 64),
            'storage_key' => 'ebooks/server-copy.epub',
            'storage_provider' => 'local',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
            'files' => [
                ['format' => 'EPUB', 'file_hash' => 'sha256:' . str_repeat('b', 64)],
                ['format' => 'PDF', 'file_hash' => 'sha256:' . str_repeat('c', 64)],
            ],
        ]);

        $this->assertTrue((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('file_missing_or_not_uploaded', $status['reason'] ?? null);
        $this->assertCount(1, $status['uploads'] ?? []);
        $this->assertSame('PDF', $status['uploads'][0]['format'] ?? null);
    }

    public function test_file_upload_ignores_entries_with_empty_format(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'last_modified' => now()->setTimestamp(300),
        ]);

        $status = $this->evaluateFileUploadStatus($userBook->fresh(['library', 'files']), [
            'uuid' => $userBook->uuid,
            'last_modified' => 200,
            'files' => [
                ['format' => '', 'file_hash' => 'sha256:' . str_repeat('c', 64)],
            ],
        ]);

        $this->assertFalse((bool) ($status['ebook_missing'] ?? false));
        $this->assertSame('files_present', $status['reason'] ?? null);
        $this->assertSame([], $status['uploads'] ?? []);
    }

    private function evaluateFileUploadStatus(UserBook $userBook, array $item): array
    {
        $service = app(SyncService::class);
        $method = new \ReflectionMethod($service, 'evaluateFileUploadStatus');

        return $method->invoke($service, $userBook, $item);
    }
}
