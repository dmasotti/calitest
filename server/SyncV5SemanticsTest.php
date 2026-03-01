<?php

namespace Tests\Server;

use App\Models\BookFile;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use App\Services\Sync\MetadataHasher;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncV5SemanticsTest extends TestCase
{
    use RefreshDatabase;

    private function setupUserLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        return [$user, $library];
    }

    public function test_deleted_on_server_is_not_reported_as_missing_from_server(): void
    {
        [, $library] = $this->setupUserLibrary();

        $book = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => $library->id,
            'uuid' => '11111111-1111-1111-1111-111111111111',
            'title' => 'Deleted On Server',
        ]);
        $book->delete();

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $book->uuid => ['m' => 'm1', 'c' => null, 'f' => null, 'lm' => time()],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $deleted = $response->json('deleted_on_server');
        $missing = array_column($response->json('missing_from_server') ?? [], 'uuid');

        $this->assertContains($book->uuid, $deleted);
        $this->assertNotContains($book->uuid, $missing);
    }

    public function test_sync_v5_is_idempotent_for_same_request_payload(): void
    {
        [, $library] = $this->setupUserLibrary();

        $payload = [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' => ['m' => 'm1', 'c' => null, 'f' => null, 'lm' => 100],
                    'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb' => ['m' => 'm2', 'c' => null, 'f' => null, 'lm' => 200],
                ],
                'd' => [],
            ],
            'client_cursor' => 0,
            'client_batch_size' => 50,
        ];

        $first = $this->postJson('/api/sync/v5', $payload);
        $second = $this->postJson('/api/sync/v5', $payload);

        $first->assertStatus(200);
        $second->assertStatus(200);
        $this->assertSame(
            $first->json('missing_from_server'),
            $second->json('missing_from_server')
        );
        $this->assertSame(
            $first->json('client_cursor_next'),
            $second->json('client_cursor_next')
        );
        $this->assertSame(
            $first->json('client_done'),
            $second->json('client_done')
        );
    }

    public function test_cover_hash_mismatch_sets_needs_cover_on_missing_from_server(): void
    {
        [, $library] = $this->setupUserLibrary();

        $book = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => $library->id,
            'uuid' => '22222222-2222-2222-2222-222222222222',
            'cover_original_hash' => 'sha256:servercoverhash',
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $book->uuid => ['m' => 'client-meta', 'c' => 'differentcoverhash', 'f' => null, 'lm' => time()],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $missingByUuid = collect($response->json('missing_from_server') ?? [])->keyBy('uuid');
        $entry = $missingByUuid->get($book->uuid);
        $this->assertNotNull($entry);
        $this->assertTrue((bool) ($entry['needs_cover'] ?? false));
    }

    public function test_single_file_hash_mismatch_sets_needs_files_on_missing_from_server(): void
    {
        [, $library] = $this->setupUserLibrary();

        $book = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => $library->id,
            'uuid' => '33333333-3333-3333-3333-333333333333',
        ]);

        BookFile::factory()->create([
            'book' => $book->uuid,
            'format' => 'EPUB',
            'file_hash' => 'sha256:server-file-hash',
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    // One single format hash on client, intentionally different
                    $book->uuid => ['m' => 'client-meta', 'c' => null, 'f' => 'client-file-hash', 'lm' => time()],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $missingByUuid = collect($response->json('missing_from_server') ?? [])->keyBy('uuid');
        $entry = $missingByUuid->get($book->uuid);
        $this->assertNotNull($entry);
        $this->assertTrue((bool) ($entry['needs_files'] ?? false));
    }

    public function test_metadata_hasher_normalizes_pubdate_epoch_and_datetime_to_same_hash(): void
    {
        $base = [
            'uuid' => '44444444-4444-4444-4444-444444444444',
            'title' => 'Pubdate Normalization',
            'authors' => [],
            'series' => null,
            'tags' => [],
            'identifiers' => [],
            'publisher' => null,
            'languages' => [],
            'description' => null,
            'rating' => null,
        ];
        $hashEpoch = MetadataHasher::computeHash($base + [
            'pubdate' => Carbon::parse('2021-10-16 20:00:00', 'UTC')->timestamp,
        ]);
        $hashDatetime = MetadataHasher::computeHash($base + [
            'pubdate' => '2021-10-16 20:00:00',
        ]);

        $this->assertNotNull($hashEpoch);
        $this->assertSame($hashEpoch, $hashDatetime);
    }

    public function test_sync_v5_pubdate_epoch_client_hash_does_not_trigger_metadata_mismatch(): void
    {
        [, $library] = $this->setupUserLibrary();

        $book = UserBook::create([
            'id' => 4444,
            'user_id' => $library->user_id,
            'library_id' => $library->id,
            'uuid' => '44444444-4444-4444-4444-444444444444',
            'title' => 'Pubdate Normalization',
            'path' => 'Pubdate Normalization',
            'pubdate' => '2021-10-16 20:00:00',
        ]);

        $clientHash = MetadataHasher::computeHash([
            'uuid' => $book->uuid,
            'title' => $book->title,
            'authors' => [],
            'series' => null,
            'tags' => [],
            'identifiers' => [],
            'publisher' => null,
            'languages' => [],
            'pubdate' => Carbon::parse('2021-10-16 20:00:00', 'UTC')->timestamp,
            'description' => null,
            'rating' => null,
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $book->uuid => ['m' => $clientHash, 'c' => null, 'f' => null, 'lm' => time()],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $missingByUuid = collect($response->json('missing_from_server') ?? [])->keyBy('uuid');
        $entry = $missingByUuid->get($book->uuid);
        $this->assertTrue($entry === null || ($entry['needs_metadata'] ?? false) === false);
    }

    public function test_apply_book_metadata_clears_description_when_comments_is_explicit_null(): void
    {
        [$user, $library] = $this->setupUserLibrary();

        $book = UserBook::create([
            'id' => 5555,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => '55555555-5555-5555-5555-555555555555',
            'title' => 'Clear Description',
            'path' => 'Clear Description',
            'description' => '<div><p>stale description</p></div>',
        ]);

        app(BookMetadataHandler::class)->applyBookMetadata($book, [
            'uuid' => $book->uuid,
            'title' => $book->title,
            'comments' => null,
        ], $user, $library->id);

        $book->refresh();
        $this->assertNull($book->description);
    }

    public function test_repair_no_cache_recomputes_and_persists_metadata_hash_cache(): void
    {
        [, $library] = $this->setupUserLibrary();

        $book = UserBook::create([
            'id' => 6666,
            'user_id' => $library->user_id,
            'library_id' => $library->id,
            'uuid' => '66666666-6666-6666-6666-666666666666',
            'title' => 'Repair Cache Refresh',
            'path' => 'Repair Cache Refresh',
            'description' => null,
            'last_modified' => now(),
            'metadata_hash_cache' => 'v2:deadbeef:' . now()->timestamp,
        ]);

        $repair = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'no_cache' => true,
            'client_books' => [
                'b' => [
                    $book->uuid => ['m' => 'client-hash', 'c' => null, 'f' => null, 'lm' => time()],
                ],
                'd' => [],
            ],
        ]);

        $repair->assertStatus(200);
        $book->refresh();
        $cacheAfterRepair = (string) $book->metadata_hash_cache;
        $this->assertStringStartsWith('v2:', $cacheAfterRepair);
        $this->assertStringNotContainsString('deadbeef', $cacheAfterRepair);

        $normal = $this->postJson('/api/sync/v5', [
            'library_id' => $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'no_cache' => false,
            'client_books' => [
                'b' => [
                    $book->uuid => ['m' => 'another-client-hash', 'c' => null, 'f' => null, 'lm' => time()],
                ],
                'd' => [],
            ],
        ]);

        $normal->assertStatus(200);
        $book->refresh();
        $this->assertSame($cacheAfterRepair, (string) $book->metadata_hash_cache);
    }
}
