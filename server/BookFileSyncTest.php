<?php

namespace Tests\Server;

use App\Models\BookFile;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
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
            'book' => $userBook->id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'file_hash' => 'abcdef1234567890',
            'storage_key' => 'ebooks/test-book.epub',
            'is_uploaded' => true,
        ]);
    }
}
