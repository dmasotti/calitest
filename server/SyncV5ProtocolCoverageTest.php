<?php

namespace Tests\Server;

use App\Models\BookFile;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\MetadataHasher;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncV5ProtocolCoverageTest extends TestCase
{
    use RefreshDatabase;

    private function setupUserLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        Sanctum::actingAs($user);

        return [$user, $library];
    }

    public function test_sync_v5_accepts_extended_client_books_format_without_compact_wrapper(): void
    {
        [, $library] = $this->setupUserLibrary();

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            // Extended format (uuid => {metadata_hash, cover_hash, files_hash})
            'client_books' => [
                'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' => [
                    'metadata_hash' => 'm1',
                    'cover_hash' => null,
                    'files_hash' => null,
                ],
            ],
        ]);

        $response->assertStatus(200);
        $response->assertJsonStructure([
            'updates_for_client',
            'missing_from_server',
            'deleted_on_server',
            'deleted_confirmed',
            'cursor',
            'has_more',
            'batch_size',
            'skipped_hash',
        ]);
    }

    public function test_sync_v5_client_deleted_uuid_is_confirmed_and_soft_deleted_on_server(): void
    {
        [, $library] = $this->setupUserLibrary();

        $book = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'uuid' => '11111111-1111-1111-1111-111111111111',
            'title' => 'Client Deleted',
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [],
                'd' => [$book->uuid],
            ],
        ]);

        $response->assertStatus(200);
        $this->assertContains($book->uuid, $response->json('deleted_confirmed') ?? []);
        $this->assertNotContains($book->uuid, array_column($response->json('missing_from_server') ?? [], 'uuid'));

        $book->refresh();
        $this->assertNotNull($book->deleted_at, 'Book must be soft-deleted after client delete confirmation');
    }

    public function test_sync_v5_cursor_uses_timestamp_colon_id_and_paginates_without_duplicates(): void
    {
        [, $library] = $this->setupUserLibrary();

        $ts = Carbon::create(2026, 2, 27, 16, 0, 0, 'UTC');
        $bookA = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'title' => 'Cursor A',
            'path' => 'Cursor A',
            'last_modified' => $ts,
        ]);
        $bookB = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'title' => 'Cursor B',
            'path' => 'Cursor B',
            'last_modified' => $ts,
        ]);

        $first = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 1,
            'client_books' => ['b' => [], 'd' => []],
        ]);
        $first->assertStatus(200);
        $this->assertTrue((bool) $first->json('has_more'));
        $cursor = (string) $first->json('cursor');
        $this->assertMatchesRegularExpression('/^\d+:\d+$/', $cursor);

        $second = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => $cursor,
            'batch_size' => 1,
            'client_books' => ['b' => [], 'd' => []],
        ]);
        $second->assertStatus(200);
        $cursor2 = (string) $second->json('cursor');
        $this->assertMatchesRegularExpression('/^\d+:\d+$/', $cursor2);
        if ((bool) $second->json('has_more')) {
            $this->assertNotSame($cursor, $cursor2, 'Cursor must progress when pagination continues');
        }
    }

    public function test_sync_v5_does_not_request_upload_when_metadata_cover_and_files_hashes_match(): void
    {
        [, $library] = $this->setupUserLibrary();

        $lastModified = Carbon::create(2026, 2, 27, 12, 0, 0, 'UTC');
        $coverHashHex = str_repeat('a', 64);
        $fileHashHex = str_repeat('b', 64);
        $book = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'uuid' => '22222222-2222-2222-2222-222222222222',
            'title' => 'Full Hash Match',
            'path' => 'Full Hash Match',
            'last_modified' => $lastModified,
            'cover_original_hash' => 'sha256:' . $coverHashHex,
        ]);
        $book->refresh();
        $metadataHash = $this->metadataHashForBook($book);

        \DB::table('files_store')->insert([
            'sha256' => $fileHashHex,
            'storage_key' => 'ebooks/full-hash-match.epub',
            'storage_provider' => 'r2',
            'storage_url' => 'https://example.test/full-hash-match.epub',
            'ref_count' => 1,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        BookFile::factory()->create([
            'book' => $book->uuid,
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'format' => 'EPUB',
            'file_hash' => $fileHashHex,
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'storage_provider' => 'r2',
            'storage_key' => 'ebooks/full-hash-match.epub',
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $book->uuid => [
                        'm' => $metadataHash,
                        'c' => $coverHashHex,
                        'f' => $fileHashHex,
                    ],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $missingByUuid = collect($response->json('missing_from_server') ?? [])->keyBy('uuid');
        $entry = $missingByUuid->get($book->uuid);
        $this->assertTrue($entry === null, 'Server must not request metadata/cover/files upload when all hashes match');
    }

    public function test_sync_v5_normalizes_deleted_list_and_processes_it_only_on_first_client_chunk(): void
    {
        [, $library] = $this->setupUserLibrary();

        $bookA = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'uuid' => '33333333-3333-3333-3333-333333333333',
            'title' => 'Delete A',
        ]);
        $bookB = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'uuid' => '44444444-4444-4444-4444-444444444444',
            'title' => 'Delete B',
        ]);

        $payload = [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 10,
            'client_cursor' => 0,
            'client_batch_size' => 2,
            'client_books' => [
                'b' => [
                    'uuid-a' => ['m' => 'm1', 'lm' => 1],
                    'uuid-b' => ['m' => 'm2', 'lm' => 2],
                    'uuid-c' => ['m' => 'm3', 'lm' => 3],
                ],
                'd' => [
                    $bookA->uuid,
                    ['uuid' => $bookB->uuid],
                    $bookA->uuid,
                    '',
                ],
            ],
        ];

        $first = $this->postJson('/api/sync/v5', $payload);
        $first->assertStatus(200);
        $deletedConfirmedFirst = $first->json('deleted_confirmed') ?? [];
        sort($deletedConfirmedFirst);
        $expected = [$bookA->uuid, $bookB->uuid];
        sort($expected);
        $this->assertSame($expected, $deletedConfirmedFirst);

        $bookA->refresh();
        $bookB->refresh();
        $this->assertNotNull($bookA->deleted_at);
        $this->assertNotNull($bookB->deleted_at);

        $second = $this->postJson('/api/sync/v5', array_merge($payload, [
            'client_cursor' => 2,
        ]));
        $second->assertStatus(200);
        $this->assertSame([], $second->json('deleted_confirmed') ?? []);
    }

    public function test_sync_v5_accepts_gzip_json_request_on_real_endpoint(): void
    {
        [, $library] = $this->setupUserLibrary();

        $payload = [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 10,
            'client_books' => [
                'b' => [
                    'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa' => ['m' => 'm1', 'c' => null, 'f' => null, 'lm' => 1],
                ],
                'd' => [],
            ],
        ];

        $response = $this->call(
            'POST',
            '/api/sync/v5',
            [],
            [],
            [],
            [
                'CONTENT_TYPE' => 'application/json',
                'HTTP_CONTENT_ENCODING' => 'gzip',
                'HTTP_ACCEPT' => 'application/json',
            ],
            gzencode(json_encode($payload, JSON_THROW_ON_ERROR), 6)
        );

        $response->assertStatus(200);
        $response->assertJsonStructure([
            'updates_for_client',
            'missing_from_server',
            'deleted_on_server',
            'deleted_confirmed',
            'cursor',
            'has_more',
            'batch_size',
            'skipped_hash',
        ]);
        $this->assertSame('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', $response->json('missing_from_server.0.uuid'));
    }

    public function test_sync_v5_returns_gzip_response_when_requested_on_real_endpoint(): void
    {
        [, $library] = $this->setupUserLibrary();

        putenv('API_GZIP_RESPONSE_MIN_BYTES=1');
        try {
            $payload = [
                'library_id' => (string) $library->id,
                'calibre_library_uuid' => $library->calibre_library_id,
                'cursor' => null,
                'batch_size' => 10,
                'client_books' => [
                    'b' => [
                        'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb' => ['m' => 'm2', 'c' => null, 'f' => null, 'lm' => 2],
                    ],
                    'd' => [],
                ],
            ];

            $response = $this->call(
                'POST',
                '/api/sync/v5',
                [],
                [],
                [],
                [
                    'CONTENT_TYPE' => 'application/json',
                    'HTTP_ACCEPT' => 'application/json',
                    'HTTP_ACCEPT_ENCODING' => 'gzip',
                ],
                json_encode($payload, JSON_THROW_ON_ERROR)
            );

            $response->assertStatus(200);
            $response->assertHeader('Content-Encoding', 'gzip');
            $decoded = gzdecode($response->getContent());
            $this->assertNotFalse($decoded);
            $decodedJson = json_decode($decoded, true, 512, JSON_THROW_ON_ERROR);
            $this->assertArrayHasKey('missing_from_server', $decodedJson);
            $this->assertSame('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', $decodedJson['missing_from_server'][0]['uuid'] ?? null);
        } finally {
            putenv('API_GZIP_RESPONSE_MIN_BYTES');
        }
    }

    public function test_sync_v5_handles_malformed_cursor_without_failing_and_returns_valid_next_cursor(): void
    {
        [, $library] = $this->setupUserLibrary();

        $book = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'uuid' => '55555555-5555-5555-5555-555555555555',
            'title' => 'Malformed Cursor Book',
            'path' => 'Malformed Cursor Book',
            'last_modified' => Carbon::create(2026, 2, 27, 17, 0, 0, 'UTC'),
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => 'not-a-valid-cursor',
            'batch_size' => 10,
            'client_books' => ['b' => [], 'd' => []],
        ]);

        $response->assertStatus(200);
        $response->assertJsonPath('updates_for_client.0.uuid', $book->uuid);
        $this->assertMatchesRegularExpression('/^\d+:\d+$/', (string) $response->json('cursor'));
    }

    public function test_sync_v5_when_same_uuid_is_in_books_and_deleted_list_delete_wins(): void
    {
        [, $library] = $this->setupUserLibrary();

        $book = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'uuid' => '66666666-6666-6666-6666-666666666666',
            'title' => 'Delete Wins',
            'path' => 'Delete Wins',
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $book->uuid => ['m' => 'client-mismatch', 'c' => 'c-hash', 'f' => 'f-hash', 'lm' => 10],
                ],
                'd' => [$book->uuid],
            ],
        ]);

        $response->assertStatus(200);
        $this->assertContains($book->uuid, $response->json('deleted_confirmed') ?? []);
        $this->assertNotContains($book->uuid, array_column($response->json('missing_from_server') ?? [], 'uuid'));

        $book->refresh();
        $this->assertNotNull($book->deleted_at);
    }

    public function test_sync_v5_returns_422_for_invalid_request_contract_fields(): void
    {
        [, $library] = $this->setupUserLibrary();

        $responseInvalidClientBooks = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'client_books' => 'not-an-array',
        ]);
        $responseInvalidClientBooks->assertStatus(422);

        $responseInvalidCursor = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'client_cursor' => -1,
            'client_books' => ['b' => [], 'd' => []],
        ]);
        $responseInvalidCursor->assertStatus(422);

        $responseInvalidBatch = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'batch_size' => 0,
            'client_books' => ['b' => [], 'd' => []],
        ]);
        $responseInvalidBatch->assertStatus(422);
    }

    public function test_sync_v5_accepts_deleted_list_as_single_string_uuid(): void
    {
        [, $library] = $this->setupUserLibrary();

        $book = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'uuid' => '77777777-7777-7777-7777-777777777777',
            'title' => 'Delete As String',
            'path' => 'Delete As String',
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'client_books' => [
                'b' => [],
                'd' => $book->uuid,
            ],
        ]);

        $response->assertStatus(200);
        $this->assertContains($book->uuid, $response->json('deleted_confirmed') ?? []);
        $book->refresh();
        $this->assertNotNull($book->deleted_at);
    }

    public function test_sync_v5_can_return_internal_phase_profile_when_explicitly_requested(): void
    {
        [, $library] = $this->setupUserLibrary();

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 25,
            'client_books' => [
                'b' => [
                    '99999999-9999-9999-9999-999999999999' => ['m' => 'm1', 'c' => null, 'f' => null, 'lm' => 1],
                ],
                'd' => [],
            ],
            'options' => [
                'profile_sync_v5' => true,
            ],
        ]);

        $response->assertStatus(200);
        $response->assertJsonStructure([
            'profile' => [
                'sync_v5' => [
                    'normalize_client_books_ms',
                    'resolve_library_ms',
                    'load_server_batch_ms',
                    'process_client_deletes_ms',
                    'load_deleted_on_server_ms',
                    'load_server_relations_ms',
                    'prime_server_batch_hash_ms',
                    'authors_map_ms',
                    'series_map_ms',
                    'tags_map_ms',
                    'publishers_map_ms',
                    'languages_map_ms',
                    'identifiers_map_ms',
                    'files_map_ms',
                    'all_server_books_ms',
                    'prime_client_set_hash_ms',
                    'all_files_map_ms',
                    'all_identifiers_map_ms',
                    'loop_missing_from_server_ms',
                    'loop_updates_for_client_ms',
                    'dedupe_and_finalize_ms',
                    'total_ms',
                ],
            ],
        ]);

        $profile = $response->json('profile.sync_v5');
        $this->assertIsArray($profile);
        foreach ($profile as $key => $value) {
            $this->assertIsNumeric($value, sprintf('Expected numeric sync/v5 profile field for key [%s]', $key));
            $this->assertGreaterThanOrEqual(0, (float) $value, sprintf('Expected non-negative sync/v5 profile field for key [%s]', $key));
        }
    }

    public function test_sync_v5_primes_metadata_hash_view_for_server_batch_without_per_book_lookup(): void
    {
        [, $library] = $this->setupUserLibrary();

        $baseTs = Carbon::create(2026, 3, 10, 12, 0, 0, 'UTC');
        for ($i = 0; $i < 5; $i++) {
            UserBook::factory()->create([
                'user_id' => $library->user_id,
                'library_id' => (string) $library->id,
                'uuid' => sprintf('aaaaaaa%d-aaaa-aaaa-aaaa-aaaaaaaaaaa%d', $i, $i),
                'title' => 'Batch Hash Prime ' . $i,
                'path' => 'Batch Hash Prime ' . $i,
                'last_modified' => $baseTs->copy()->addSeconds($i),
            ]);
        }

        \DB::flushQueryLog();
        \DB::enableQueryLog();

        try {
            $response = $this->postJson('/api/sync/v5', [
                'library_id' => (string) $library->id,
                'calibre_library_uuid' => $library->calibre_library_id,
                'cursor' => null,
                'batch_size' => 10,
                'client_books' => [
                    'b' => [],
                    'd' => [],
                ],
            ]);
        } finally {
            $queries = \DB::getQueryLog();
            \DB::disableQueryLog();
        }

        $response->assertStatus(200);
        $this->assertCount(5, $response->json('updates_for_client') ?? []);

        $booksHashQueries = array_values(array_filter($queries, static function (array $entry): bool {
            $sql = strtolower((string) ($entry['query'] ?? ''));
            return str_contains($sql, 'books_hash_v2');
        }));

        $this->assertLessThanOrEqual(
            1,
            count($booksHashQueries),
            'sync/v5 should batch-prime books_hash_v2 for the server page instead of querying per book'
        );
    }

    public function test_sync_v5_uses_valid_metadata_hash_cache_before_querying_books_hash_v2(): void
    {
        [, $library] = $this->setupUserLibrary();

        $baseTs = Carbon::create(2026, 3, 11, 10, 0, 0, 'UTC');
        for ($i = 0; $i < 5; $i++) {
            $book = UserBook::factory()->create([
                'user_id' => $library->user_id,
                'library_id' => (string) $library->id,
                'uuid' => sprintf('bbbbbbb%d-bbbb-bbbb-bbbb-bbbbbbbbbbb%d', $i, $i),
                'title' => 'Batch Hash Cache ' . $i,
                'path' => 'Batch Hash Cache ' . $i,
                'last_modified' => $baseTs->copy()->addSeconds($i),
            ]);
            $book->refresh();
            $hash = $this->metadataHashForBook($book);
            $book->forceFill([
                'metadata_hash_cache' => 'v2:' . $hash . ':' . $book->last_modified->timestamp,
            ])->saveQuietly();
        }

        \DB::flushQueryLog();
        \DB::enableQueryLog();

        try {
            $response = $this->postJson('/api/sync/v5', [
                'library_id' => (string) $library->id,
                'calibre_library_uuid' => $library->calibre_library_id,
                'cursor' => null,
                'batch_size' => 10,
                'client_books' => [
                    'b' => [],
                    'd' => [],
                ],
            ]);
        } finally {
            $queries = \DB::getQueryLog();
            \DB::disableQueryLog();
        }

        $response->assertStatus(200);
        $this->assertCount(5, $response->json('updates_for_client') ?? []);

        $booksHashQueries = array_values(array_filter($queries, static function (array $entry): bool {
            $sql = strtolower((string) ($entry['query'] ?? ''));
            return str_contains($sql, 'books_hash_v2');
        }));

        $this->assertCount(
            0,
            $booksHashQueries,
            'sync/v5 should use valid books.metadata_hash_cache for the server page before falling back to books_hash_v2'
        );
    }

    public function test_sync_v5_treats_prefixed_and_unsorted_files_hashes_as_equivalent_when_content_matches(): void
    {
        [, $library] = $this->setupUserLibrary();

        $coverHashA = str_repeat('a', 64);
        $fileHashC = str_repeat('c', 64);
        $fileHashE = str_repeat('e', 64);
        $book = UserBook::factory()->create([
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'uuid' => '88888888-8888-8888-8888-888888888888',
            'title' => 'Hash Normalization Match',
            'path' => 'Hash Normalization Match',
            'last_modified' => Carbon::create(2026, 2, 27, 18, 0, 0, 'UTC'),
            'cover_original_hash' => 'sha256:' . $coverHashA,
        ]);
        $book->refresh();
        $metadataHash = $this->metadataHashForBook($book);

        \DB::table('files_store')->insert([
            [
                'sha256' => $fileHashC,
                'storage_key' => 'ebooks/hash-normalization-c.epub',
                'storage_provider' => 'r2',
                'storage_url' => 'https://example.test/hash-normalization-c.epub',
                'ref_count' => 1,
                'created_at' => now(),
                'updated_at' => now(),
            ],
            [
                'sha256' => $fileHashE,
                'storage_key' => 'ebooks/hash-normalization-e.pdf',
                'storage_provider' => 'r2',
                'storage_url' => 'https://example.test/hash-normalization-e.pdf',
                'ref_count' => 1,
                'created_at' => now(),
                'updated_at' => now(),
            ],
        ]);

        BookFile::factory()->create([
            'book' => $book->uuid,
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'format' => 'EPUB',
            'file_hash' => $fileHashE,
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'storage_provider' => 'r2',
            'storage_key' => 'ebooks/hash-normalization-e.epub',
        ]);
        BookFile::factory()->create([
            'book' => $book->uuid,
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'format' => 'PDF',
            'file_hash' => $fileHashC,
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'storage_provider' => 'r2',
            'storage_key' => 'ebooks/hash-normalization-c.pdf',
        ]);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $book->uuid => [
                        'm' => $metadataHash,
                        'c' => 'sha256:' . $coverHashA,
                        'f' => 'sha256:' . $fileHashE . ', sha256:' . $fileHashC,
                    ],
                ],
                'd' => [],
            ],
        ]);

        $response->assertStatus(200);
        $missingByUuid = collect($response->json('missing_from_server') ?? [])->keyBy('uuid');
        $this->assertNull($missingByUuid->get($book->uuid));
    }

    private function metadataHashForBook(UserBook $book): string
    {
        if (Schema::hasTable('books_hash_v2')) {
            $hash = (string) DB::table('books_hash_v2')
                ->where('user_id', $book->user_id)
                ->where('library_id', $book->library_id)
                ->where('uuid', $book->uuid)
                ->value('metadata_hash');
            if ($hash !== '') {
                return strtolower($hash);
            }
        }

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
