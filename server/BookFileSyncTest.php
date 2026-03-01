<?php

namespace Tests\Server;

use App\Models\BookFile;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Tests\TestCase;

class BookFileSyncTest extends TestCase
{
    use RefreshDatabase;

    public function test_registers_files_from_sync_payload()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $handler = app(BookMetadataHandler::class);
        $handler->applyBookMetadata($userBook, [
            'files' => [
                [
                    'format' => 'epub',
                    'name' => 'Test Book.epub',
                    'file_path' => 'ebooks/test-book.epub',
                    'uncompressed_size' => 1024 * 1024,
                    'file_hash' => 'sha256:abcdef1234567890',
                    'storage_key' => 'ebooks/test-book.epub',
                    'storage_provider' => 'r2',
                ],
            ],
        ], $user, $library->id);

        $this->assertDatabaseHas('books_files', [
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'file_hash' => 'abcdef1234567890',
            'storage_key' => 'ebooks/test-book.epub',
            'is_uploaded' => true,
        ]);
    }

    public function test_registers_files_when_name_matches_temp_path_uses_friendly_filename()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Temp Path Book',
        ]);

        $handler = app(BookMetadataHandler::class);
        $handler->applyBookMetadata($userBook, [
            'files' => [
                [
                    'format' => 'epub',
                    'name' => 'tmp12345.epub',
                    'file_path' => '/tmp/calibre/tmp12345.epub',
                    'file_hash' => 'sha256:abcdef1234567890',
                    'storage_key' => 'ebooks/calibre/tmp12345.epub',
                    'storage_provider' => 'r2',
                ],
            ],
        ], $user, $library->id);

        $file = BookFile::where('book', $userBook->uuid)
            ->where('format', 'EPUB')
            ->firstOrFail();

        $this->assertSame('Temp Path Book.epub', $file->name);
    }

    public function test_registers_files_without_name_derives_friendly_filename()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Derived Title',
        ]);

        $handler = app(BookMetadataHandler::class);
        $handler->applyBookMetadata($userBook, [
            'files' => [
                [
                    'format' => 'epub',
                    'file_hash' => 'sha256:abcdef1234567890',
                    'storage_key' => 'ebooks/derived-title.epub',
                    'storage_provider' => 'r2',
                ],
            ],
        ], $user, $library->id);

        $file = BookFile::where('book', $userBook->uuid)
            ->where('format', 'EPUB')
            ->firstOrFail();

        $this->assertSame('Derived Title.epub', $file->name);
    }

    public function test_registers_files_without_storage_key_sets_provider_and_flags_missing()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        config(['filesystems.ebook_storage.provider' => 'r2']);

        $handler = app(BookMetadataHandler::class);
        $handler->applyBookMetadata($userBook, [
            'files' => [
                [
                    'format' => 'epub',
                    'name' => 'Missing File.epub',
                    'file_hash' => 'sha256:1234abcd',
                    // No storage_key yet (pre-upload registration)
                ],
            ],
        ], $user, $library->id);

        $this->assertDatabaseHas('books_files', [
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'storage_provider' => 'r2',
            'is_uploaded' => false,
            'needs_file_upload' => true,
            'file_missing' => true,
        ]);
    }

    public function test_registers_files_without_storage_key_uses_configured_provider()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        config(['filesystems.ebook_storage.provider' => 'local']);

        $handler = app(BookMetadataHandler::class);
        $handler->applyBookMetadata($userBook, [
            'files' => [
                [
                    'format' => 'pdf',
                    'name' => 'Test File.pdf',
                    // No storage_key yet
                ],
            ],
        ], $user, $library->id);

        $this->assertDatabaseHas('books_files', [
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'PDF',
            'storage_provider' => 'local',
            'is_uploaded' => false,
            'needs_file_upload' => true,
            'file_missing' => true,
        ]);
    }

    public function test_preserves_full_format_string_for_unknown_formats()
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $handler = app(BookMetadataHandler::class);
        $handler->applyBookMetadata($userBook, [
            'files' => [
                [
                    'format' => 'AZW3',
                    'name' => 'Test.azw3',
                ],
            ],
        ], $user, $library->id);

        $this->assertDatabaseHas('books_files', [
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'AZW3',
        ]);
    }

    public function test_updates_existing_file_without_storage_key_preserves_existing_upload_state(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        BookFile::create([
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'name' => 'Existing.epub',
            'uncompressed_size' => 1234,
            'file_path' => 'ebooks/existing.epub',
            'file_hash' => 'sha256:existinghash',
            'storage_key' => 'ebooks/existing.epub',
            'storage_provider' => 'r2',
            'uuid' => (string) Str::uuid(),
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
        ]);

        $handler = app(BookMetadataHandler::class);
        $handler->applyBookMetadata($userBook, [
            'files' => [
                [
                    'format' => 'epub',
                    'name' => 'Existing.epub',
                    // Missing storage_key on update should not downgrade an already uploaded file.
                ],
            ],
        ], $user, $library->id);

        $this->assertDatabaseHas('books_files', [
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
        ]);
    }
}
