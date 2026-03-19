<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\BookFile;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\MetadataHasher;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncV5HashSkipServerUpdatesTest extends TestCase
{
    use RefreshDatabase;

    public function test_sync_v5_skips_updates_for_matching_client_hash_even_with_chunk_cursor(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $book = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Hash Match Book',
            'path' => 'Hash Match Book',
            'last_modified' => $lastModified,
        ]);
        $metadataHash = $this->metadataHashForBook($book);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_cursor' => 500,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => [
                    $book->uuid => [
                        'm' => $metadataHash,
                    ],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $this->assertGreaterThanOrEqual(1, (int) $response->json('skipped_hash'));
        $response->assertJsonCount(0, 'updates_for_client');
    }

    public function test_sync_v5_does_not_skip_when_cover_hash_mismatches(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $book = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Cover Mismatch Book',
            'path' => 'Cover Mismatch Book',
            'last_modified' => $lastModified,
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
        ]);
        $metadataHash = $this->metadataHashForBook($book);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_cursor' => 100,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => [
                    $book->uuid => [
                        'm' => $metadataHash,
                        'c' => str_repeat('b', 64),
                    ],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $response->assertJsonPath('skipped_hash', 0);
        $response->assertJsonCount(1, 'updates_for_client');
        $response->assertJsonPath('updates_for_client.0.uuid', $book->uuid);
    }

    public function test_sync_v5_normalize_hash_token_supports_sha256_prefix_for_cover_and_files(): void
    {
        $controller = app(\App\Http\Controllers\Api\SyncV5Controller::class);
        $method = new \ReflectionMethod($controller, 'normalizeHashToken');
        $method->setAccessible(true);

        $cover = $method->invoke($controller, 'sha256:' . str_repeat('a', 64), false);
        $files = $method->invoke(
            $controller,
            'sha256:' . str_repeat('e', 64) . ',sha256:' . str_repeat('c', 64),
            true
        );

        $this->assertSame(str_repeat('a', 64), $cover);
        $this->assertSame(str_repeat('c', 64) . ',' . str_repeat('e', 64), $files);
    }

    public function test_sync_v5_only_skips_books_present_in_client_books(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $bookMatched = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Matched',
            'path' => 'Matched',
            'last_modified' => $lastModified,
        ]);
        $bookMissingClientState = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'No Client Hash',
            'path' => 'No Client Hash',
            'last_modified' => $lastModified,
        ]);
        $matchedHash = $this->metadataHashForBook($bookMatched);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_cursor' => 10,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => [
                    $bookMatched->uuid => ['m' => $matchedHash],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $this->assertGreaterThanOrEqual(1, (int) $response->json('skipped_hash'));
        $response->assertJsonCount(1, 'updates_for_client');
        $response->assertJsonPath('updates_for_client.0.uuid', $bookMissingClientState->uuid);
    }

    public function test_sync_v5_does_not_skip_when_client_files_hash_exists_but_server_file_is_unavailable(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $book = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Unavailable File Book',
            'path' => 'Unavailable File Book',
            'last_modified' => $lastModified,
        ]);
        $metadataHash = $this->metadataHashForBook($book);

        BookFile::factory()->create([
            'book' => $book->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'file_hash' => str_repeat('d', 64),
            'storage_key' => '',
            'storage_provider' => 'r2',
            'is_uploaded' => false,
            'needs_file_upload' => true,
            'file_missing' => true,
            'uuid' => (string) Str::uuid(),
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_cursor' => 10,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => [
                    $book->uuid => [
                        'm' => $metadataHash,
                        'f' => str_repeat('d', 64),
                    ],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $response->assertJsonPath('skipped_hash', 0);
        $response->assertJsonCount(0, 'updates_for_client');
        $response->assertJsonCount(1, 'missing_from_server');
        $response->assertJsonPath('missing_from_server.0.uuid', $book->uuid);
        $response->assertJsonPath('missing_from_server.0.needs_metadata', false);
        $response->assertJsonPath('missing_from_server.0.needs_cover', false);
        $response->assertJsonPath('missing_from_server.0.needs_files', true);
    }

    public function test_sync_v5_emits_file_only_update_when_server_has_available_file_and_metadata_matches(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $book = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Server File Only Book',
            'path' => 'Server File Only Book',
            'last_modified' => $lastModified,
        ]);
        $metadataHash = $this->metadataHashForBook($book);

        DB::table('files_store')->insert([
            'sha256' => str_repeat('d', 64),
            'storage_key' => 'bench/server-file.epub',
            'storage_provider' => 'bench',
            'storage_url' => null,
            'ref_count' => 1,
            'size' => 1234,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        BookFile::factory()->create([
            'book' => $book->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'file_hash' => str_repeat('d', 64),
            'storage_key' => 'bench/server-file.epub',
            'storage_provider' => 'bench',
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
            'uuid' => (string) Str::uuid(),
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_cursor' => 10,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => [
                    $book->uuid => [
                        'm' => $metadataHash,
                        'f' => null,
                    ],
                ],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => true,
                'sync_covers_enabled' => false,
            ],
        ]);

        $response->assertStatus(200);
        $response->assertJsonPath('skipped_hash', 0);
        $response->assertJsonCount(1, 'updates_for_client');
        $response->assertJsonPath('updates_for_client.0.uuid', $book->uuid);
        $this->assertSame('EPUB', $response->json('updates_for_client.0.formats.0.format'));
    }

    public function test_sync_v5_emits_cover_only_update_when_server_has_cover_and_metadata_matches(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $book = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Server Cover Only Book',
            'path' => 'Server Cover Only Book',
            'last_modified' => $lastModified,
            'has_cover' => true,
            'cover_original_hash' => 'sha256:' . str_repeat('c', 64),
            'cover_url' => 'https://bench.example.test/covers/server-cover.jpg',
        ]);
        $metadataHash = $this->metadataHashForBook($book);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_cursor' => 10,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => [
                    $book->uuid => [
                        'm' => $metadataHash,
                        'c' => null,
                    ],
                ],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => true,
            ],
        ]);

        $response->assertStatus(200);
        $response->assertJsonPath('skipped_hash', 0);
        $response->assertJsonCount(1, 'updates_for_client');
        $response->assertJsonPath('updates_for_client.0.uuid', $book->uuid);
        $this->assertSame('sha256:' . str_repeat('c', 64), $response->json('updates_for_client.0.cover_hash'));
    }

    public function test_sync_v5_skips_file_only_update_when_sync_files_is_disabled(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $book = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Server File Disabled Book',
            'path' => 'Server File Disabled Book',
            'last_modified' => $lastModified,
        ]);
        $metadataHash = $this->metadataHashForBook($book);

        DB::table('files_store')->insert([
            'sha256' => str_repeat('d', 64),
            'storage_key' => 'bench/server-disabled-file.epub',
            'storage_provider' => 'bench',
            'storage_url' => null,
            'ref_count' => 1,
            'size' => 1234,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        BookFile::factory()->create([
            'book' => $book->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'file_hash' => str_repeat('d', 64),
            'storage_key' => 'bench/server-disabled-file.epub',
            'storage_provider' => 'bench',
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
            'uuid' => (string) Str::uuid(),
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_cursor' => 10,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => [
                    $book->uuid => [
                        'm' => $metadataHash,
                        'f' => null,
                    ],
                ],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
            ],
        ]);

        $response->assertStatus(200);
        $this->assertGreaterThanOrEqual(1, (int) $response->json('skipped_hash'));
        $response->assertJsonCount(0, 'updates_for_client');
    }

    public function test_sync_v5_skips_cover_only_update_when_sync_covers_is_disabled(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $book = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Server Cover Disabled Book',
            'path' => 'Server Cover Disabled Book',
            'last_modified' => $lastModified,
            'has_cover' => true,
            'cover_original_hash' => 'sha256:' . str_repeat('c', 64),
            'cover_url' => 'https://bench.example.test/covers/server-disabled-cover.jpg',
        ]);
        $metadataHash = $this->metadataHashForBook($book);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_cursor' => 10,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => [
                    $book->uuid => [
                        'm' => $metadataHash,
                        'c' => null,
                    ],
                ],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
            ],
        ]);

        $response->assertStatus(200);
        $this->assertGreaterThanOrEqual(1, (int) $response->json('skipped_hash'));
        $response->assertJsonCount(0, 'updates_for_client');
    }

    public function test_sync_v5_profile_skips_all_file_work_when_sync_files_is_disabled(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $book = UserBook::create([
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Profile Metadata Only Book',
            'path' => 'Profile Metadata Only Book',
            'last_modified' => $lastModified,
        ]);
        $metadataHash = $this->metadataHashForBook($book);

        DB::table('files_store')->insert([
            'sha256' => str_repeat('d', 64),
            'storage_key' => 'bench/profile-file.epub',
            'storage_provider' => 'bench',
            'storage_url' => null,
            'ref_count' => 1,
            'size' => 1234,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        BookFile::factory()->create([
            'book' => $book->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'file_hash' => str_repeat('d', 64),
            'storage_key' => 'bench/profile-file.epub',
            'storage_provider' => 'bench',
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
            'uuid' => (string) Str::uuid(),
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_cursor' => 10,
            'client_batch_size' => 500,
            'client_books' => [
                'b' => [
                    $book->uuid => [
                        'm' => $metadataHash,
                        'f' => null,
                    ],
                ],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'profile_sync_v5' => true,
            ],
        ]);

        $response->assertStatus(200);
        $profile = $response->json('profile.sync_v5');
        $this->assertIsArray($profile);
        $this->assertSame(0.0, (float) ($profile['files_map_ms'] ?? -1));
        $this->assertSame(0.0, (float) ($profile['all_files_map_ms'] ?? -1));
        $this->assertSame(0.0, (float) ($profile['loop_missing_files_ms'] ?? -1));
        $this->assertSame(0.0, (float) ($profile['loop_updates_files_payload_ms'] ?? -1));
    }

    private function metadataHashForBook(UserBook $book): string
    {
        return (string) MetadataHasher::computeHash([
            'uuid' => $book->uuid,
            'title' => $book->title,
            'author_sort' => $book->author_sort,
            'authors' => [],
            'series' => null,
            'series_index' => $book->series_index,
            'tags' => [],
            'identifiers' => [],
            'publisher' => null,
            'languages' => [],
            'pubdate' => $book->pubdate,
            'description' => $book->description,
            'rating' => $book->rating,
            'files' => [],
        ]);
    }
}
