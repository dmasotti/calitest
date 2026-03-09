<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Services\Sync\MetadataHasher;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncV5HashMismatchMatrixTest extends TestCase
{
    use RefreshDatabase;

    /**
     * @dataProvider mismatchMatrix
     */
    public function test_sync_v5_sets_needs_flags_for_all_hash_mismatch_combinations(
        bool $metadataMatch,
        bool $coverMatch,
        bool $filesMatch
    ): void {
        [, $library] = $this->setupUserLibrary();
        $seed = $this->seedBookWithDeterministicHashes($library);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $seed['uuid'] => [
                        'm' => $metadataMatch ? $seed['metadata'] : str_repeat('d', 64),
                        'c' => $coverMatch ? $seed['cover'] : str_repeat('e', 64),
                        'f' => $filesMatch ? $seed['file'] : str_repeat('f', 64),
                    ],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $entry = collect($response->json('missing_from_server') ?? [])->firstWhere('uuid', $seed['uuid']);

        if ($metadataMatch && $coverMatch && $filesMatch) {
            $this->assertNull($entry, 'When all hashes match, missing_from_server must not include the book');
            return;
        }

        $this->assertNotNull($entry);
        $this->assertSame(!$metadataMatch, (bool) ($entry['needs_metadata'] ?? false));
        $this->assertSame(!$coverMatch, (bool) ($entry['needs_cover'] ?? false));
        $this->assertSame(!$filesMatch, (bool) ($entry['needs_files'] ?? false));
    }

    public function test_sync_v5_files_only_mismatch_must_not_send_metadata_payload_back_to_client(): void
    {
        [, $library] = $this->setupUserLibrary();
        $seed = $this->seedBookWithDeterministicHashes($library);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $seed['uuid'] => [
                        'm' => $seed['metadata'],
                        'c' => $seed['cover'],
                        'f' => str_repeat('9', 64), // files mismatch only
                    ],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $entry = collect($response->json('missing_from_server') ?? [])->firstWhere('uuid', $seed['uuid']);
        $this->assertNotNull($entry);
        $this->assertFalse((bool) ($entry['needs_metadata'] ?? true));
        $this->assertTrue((bool) ($entry['needs_files'] ?? false));

        $updates = collect($response->json('updates_for_client') ?? []);
        $sentBack = $updates->firstWhere('uuid', $seed['uuid']);

        $this->assertNull(
            $sentBack,
            'When only files mismatch, server should request files only and not send metadata payload back'
        );
    }

    public function test_sync_v5_files_hash_with_timestamp_suffix_is_normalized_for_comparison(): void
    {
        [, $library] = $this->setupUserLibrary();
        $seed = $this->seedBookWithDeterministicHashes($library);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $seed['uuid'] => [
                        'm' => $seed['metadata'],
                        'c' => $seed['cover'],
                        // Real plugin cache format can include ":<lm>" suffix.
                        'f' => 'sha256:' . $seed['file'] . ':1771845123',
                    ],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $entry = collect($response->json('missing_from_server') ?? [])->firstWhere('uuid', $seed['uuid']);
        $this->assertTrue(
            $entry === null || !((bool) ($entry['needs_files'] ?? false)),
            'files_hash with timestamp suffix should still match server file hash'
        );
    }

    public function test_sync_v5_omitted_cover_and_files_hashes_never_produce_noop_missing_entry(): void
    {
        [, $library] = $this->setupUserLibrary();
        $seed = $this->seedBookWithDeterministicHashes($library);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $seed['uuid'] => [
                        'm' => $seed['metadata'],
                        'c' => null,
                        'f' => null,
                    ],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $entry = collect($response->json('missing_from_server') ?? [])->firstWhere('uuid', $seed['uuid']);
        $this->assertNull(
            $entry,
            'When client omits cover/files hashes, missing_from_server must not include a no-op entry'
        );
    }

    public function test_sync_v5_with_files_and_covers_disabled_skips_updates_when_metadata_matches(): void
    {
        [, $library] = $this->setupUserLibrary();
        $seed = $this->seedBookWithDeterministicHashes($library);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $seed['uuid'] => [
                        'm' => $seed['metadata'],
                        'c' => null,
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
        $missing = collect($response->json('missing_from_server') ?? [])->firstWhere('uuid', $seed['uuid']);
        $update = collect($response->json('updates_for_client') ?? [])->firstWhere('uuid', $seed['uuid']);

        $this->assertNull($missing, 'No missing entry expected when metadata already matches');
        $this->assertNull($update, 'No update payload expected when file/cover sync is explicitly disabled');
    }

    public static function mismatchMatrix(): array
    {
        return [
            'all_match' => [true, true, true],
            'metadata_only_mismatch' => [false, true, true],
            'cover_only_mismatch' => [true, false, true],
            'files_only_mismatch' => [true, true, false],
            'metadata_cover_mismatch' => [false, false, true],
            'metadata_files_mismatch' => [false, true, false],
            'cover_files_mismatch' => [true, false, false],
            'all_mismatch' => [false, false, false],
        ];
    }

    private function setupUserLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        return [$user, $library];
    }

    private function seedBookWithDeterministicHashes(Library $library): array
    {
        $cover = str_repeat('a', 64);
        $file = str_repeat('b', 64);
        $lastModified = Carbon::create(2026, 3, 2, 12, 0, 0, 'UTC');
        $uuid = 'aaaaaaaa-2222-4333-8444-555555555555';

        $bookId = 72338;
        DB::table('books')->insert([
            'id' => $bookId,
            'uuid' => $uuid,
            'user_id' => $library->user_id,
            'library_id' => $library->id,
            'title' => 'Mismatch Matrix Book',
            'path' => 'Mismatch Matrix Book',
            'author_sort' => 'Mismatch Author',
            'series_index' => 1.0,
            'timestamp' => now(),
            'pubdate' => now(),
            'last_modified' => $lastModified,
            'has_cover' => false,
            'cover_missing' => false,
            'cover_original_hash' => 'sha256:' . $cover,
            'cover_optimized_hash' => null,
            'cover_optimized_path' => null,
            'cover_url' => null,
            'isbn' => '',
            'lccn' => '',
            'description' => null,
            'rating' => null,
            'flags' => 1,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        DB::table('files_store')->insert([
            'sha256' => $file,
            'storage_key' => 'ebooks/mismatch-matrix.epub',
            'storage_provider' => 'r2',
            'storage_url' => 'https://example.test/mismatch-matrix.epub',
            'ref_count' => 1,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        DB::table('books_files')->insert([
            'uuid' => 'bbbbbbbb-2222-4333-8444-555555555555',
            'book' => $uuid,
            'user_id' => $library->user_id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'name' => 'mismatch-matrix.epub',
            'file_hash' => $file,
            'storage_key' => 'ebooks/mismatch-matrix.epub',
            'storage_provider' => 'r2',
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'uncompressed_size' => 12345,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $metadata = $this->metadataHashForSeed($library, $uuid);

        return [
            'uuid' => $uuid,
            'metadata' => $metadata,
            'cover' => $cover,
            'file' => $file,
        ];
    }

    private function metadataHashForSeed(Library $library, string $uuid): string
    {
        if (Schema::hasTable('books_hash_v2')) {
            $hash = (string) DB::table('books_hash_v2')
                ->where('user_id', $library->user_id)
                ->where('library_id', $library->id)
                ->where('uuid', $uuid)
                ->selectRaw('SHA2(hash_payload, 256) as metadata_hash')
                ->value('metadata_hash');
            if ($hash !== '') {
                return $hash;
            }
        }

        $book = DB::table('books')
            ->where('user_id', $library->user_id)
            ->where('library_id', $library->id)
            ->where('uuid', $uuid)
            ->first();

        return (string) MetadataHasher::computeHash([
            'uuid' => $uuid,
            'title' => (string) ($book->title ?? ''),
            'author_sort' => (string) ($book->author_sort ?? ''),
            'authors' => [],
            'series' => null,
            'series_index' => isset($book->series_index) ? (float) $book->series_index : null,
            'tags' => [],
            'identifiers' => [],
            'publisher' => null,
            'languages' => [],
            'pubdate' => $book->pubdate ?? null,
            'description' => $book->description ?? null,
            'rating' => $book->rating ?? null,
            'files' => [],
        ]);
    }
}
