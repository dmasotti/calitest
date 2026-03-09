<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncV5CurrentBugsTest extends TestCase
{
    use RefreshDatabase;

    public function test_current_bug_seeded_books_do_not_populate_metadata_merkle_branches(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $this->seedBook($library, (int) $user->id, 'aa000000-0000-4000-8000-000000000201', 'A1');
        $this->seedBook($library, (int) $user->id, 'ba000000-0000-4000-8000-000000000202', 'B1');

        $response = $this->getJson('/api/sync/v5/merkle/branches?library_id=' . $library->id . '&dimension=metadata');
        $response->assertOk();

        $this->assertGreaterThan(
            0,
            (int) ($response->json('branch_count') ?? 0),
            'Current bug: metadata merkle branches stay empty after valid seed'
        );
    }

    private function seedBook(Library $library, int $userId, string $uuid, string $title): string
    {
        $seed = substr(str_replace('-', '', $uuid), 0, 2);
        $fileHash = hash('sha256', 'file-' . $uuid);

        DB::table('books')->insert([
            'id' => random_int(50000, 99000),
            'uuid' => $uuid,
            'user_id' => $userId,
            'library_id' => $library->id,
            'title' => $title,
            'author_sort' => 'Author',
            'path' => $title,
            'flags' => 1,
            'has_cover' => 0,
            'cover_missing' => 0,
            'series_index' => 1.0,
            'timestamp' => now(),
            'pubdate' => now(),
            'last_modified' => now(),
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        DB::table('files_store')->updateOrInsert(
            ['sha256' => $fileHash],
            [
                'storage_key' => 'ebooks/' . $seed . '.epub',
                'storage_provider' => 'r2',
                'storage_url' => 'https://example.test/ebooks/' . $seed . '.epub',
                'ref_count' => 1,
                'created_at' => now(),
                'updated_at' => now(),
            ]
        );

        $bookFileRow = [
            'book' => $uuid,
            'user_id' => $userId,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'name' => $seed . '.epub',
            'file_hash' => $fileHash,
            'storage_key' => 'ebooks/' . $seed . '.epub',
            'storage_provider' => 'r2',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'uncompressed_size' => 12345,
            'created_at' => now(),
            'updated_at' => now(),
        ];
        if (Schema::hasColumn('books_files', 'file_path')) {
            $bookFileRow['file_path'] = 'ebooks/' . $seed . '.epub';
        }
        if (Schema::hasColumn('books_files', 'uuid')) {
            $bookFileRow['uuid'] = sprintf(
                '%s-%s-%s-%s-%s',
                substr(md5($uuid . '|EPUB'), 0, 8),
                substr(md5($uuid . '|EPUB'), 8, 4),
                substr(md5($uuid . '|EPUB'), 12, 4),
                substr(md5($uuid . '|EPUB'), 16, 4),
                substr(md5($uuid . '|EPUB'), 20, 12),
            );
        }
        DB::table('books_files')->insert($bookFileRow);

        return $uuid;
    }
}
