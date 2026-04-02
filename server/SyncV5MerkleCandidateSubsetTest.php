<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncV5MerkleCandidateSubsetTest extends TestCase
{
    use RefreshDatabase;

    public function test_sync_v5_respects_metadata_candidate_uuid_subset_for_missing_and_updates(): void
    {
        [$user, $library] = $this->setupUserLibrary();
        $bookA = $this->seedBook($library, 'aaaaaaaa-1111-4111-8111-111111111111', 'a');
        $bookB = $this->seedBook($library, 'bbbbbbbb-2222-4222-8222-222222222222', 'b');

        $payload = [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $bookA['uuid'] => [
                        'm' => str_repeat('f', 64), // mismatch
                        'c' => null,
                        'f' => null,
                    ],
                    $bookB['uuid'] => [
                        'm' => str_repeat('f', 64), // mismatch, but outside subset
                        'c' => null,
                        'f' => null,
                    ],
                ],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => [$bookA['uuid']],
            ],
        ];

        Sanctum::actingAs($user);
        $response = $this->postJson('/api/sync/v5', $payload);
        $response->assertOk();

        $missing = collect($response->json('missing_from_server') ?? []);
        $updates = collect($response->json('updates_for_client') ?? []);

        $this->assertNotNull($missing->firstWhere('uuid', $bookA['uuid']));
        $this->assertNull($missing->firstWhere('uuid', $bookB['uuid']));

        $this->assertNotNull($updates->firstWhere('uuid', $bookA['uuid']));
        $this->assertNull($updates->firstWhere('uuid', $bookB['uuid']));
    }

    public function test_sync_v5_ignores_unknown_candidate_uuids_without_error(): void
    {
        [$user, $library] = $this->setupUserLibrary();
        $book = $this->seedBook($library, 'cccccccc-3333-4333-8333-333333333333', 'c');

        $payload = [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $book['uuid'] => [
                        'm' => str_repeat('0', 64),
                        'c' => null,
                        'f' => null,
                    ],
                ],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => [
                    'dddddddd-4444-4444-8444-444444444444', // not existing
                ],
            ],
        ];

        Sanctum::actingAs($user);
        $response = $this->postJson('/api/sync/v5', $payload);
        $response->assertOk();
        $response->assertJsonPath('missing_from_server', []);
    }

    public function test_sync_v5_normalizes_candidate_subset_duplicates_and_whitespace(): void
    {
        [$user, $library] = $this->setupUserLibrary();
        $bookA = $this->seedBook($library, 'eeeeeeee-5555-4555-8555-555555555555', 'e');
        $bookB = $this->seedBook($library, 'ffffffff-6666-4666-8666-666666666666', 'f');

        Sanctum::actingAs($user);
        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $bookA['uuid'] => ['m' => str_repeat('1', 64), 'c' => null, 'f' => null],
                    $bookB['uuid'] => ['m' => str_repeat('2', 64), 'c' => null, 'f' => null],
                ],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => [
                    '  ' . $bookA['uuid'] . '  ',
                    $bookA['uuid'],
                    "\t" . $bookA['uuid'] . "\n",
                ],
            ],
        ]);

        $response->assertOk();
        $missing = collect($response->json('missing_from_server') ?? []);
        $updates = collect($response->json('updates_for_client') ?? []);
        $this->assertNotNull($missing->firstWhere('uuid', $bookA['uuid']));
        $this->assertNull($missing->firstWhere('uuid', $bookB['uuid']));
        $this->assertNotNull($updates->firstWhere('uuid', $bookA['uuid']));
        $this->assertNull($updates->firstWhere('uuid', $bookB['uuid']));
    }

    public function test_sync_v5_processes_client_deletions_even_with_candidate_subset(): void
    {
        [$user, $library] = $this->setupUserLibrary();
        $book = $this->seedBook($library, '99999999-7777-4777-8777-777777777777', 'g');

        Sanctum::actingAs($user);
        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [],
                'd' => [$book['uuid']],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => [
                    'aaaaaaaa-0000-4000-8000-000000000000',
                ],
            ],
        ]);

        $response->assertOk();
        $confirmed = collect($response->json('deleted_confirmed') ?? []);
        $this->assertTrue($confirmed->contains($book['uuid']));
    }

    public function test_sync_v5_invalid_candidate_subset_shape_returns_422(): void
    {
        [$user, $library] = $this->setupUserLibrary();
        Sanctum::actingAs($user);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => ['b' => [], 'd' => []],
            'options' => [
                'metadata_candidate_uuids' => 'not-an-array',
            ],
        ]);

        $response->assertStatus(422);
    }

    public function test_sync_v5_invalid_candidate_subset_entry_type_returns_422(): void
    {
        [$user, $library] = $this->setupUserLibrary();
        Sanctum::actingAs($user);

        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => ['b' => [], 'd' => []],
            'options' => [
                'metadata_candidate_uuids' => [
                    'aaaaaaaa-1111-4111-8111-111111111111',
                    12345,
                ],
            ],
        ]);

        $response->assertStatus(422);
    }

    public function test_sync_v5_empty_or_null_candidate_subset_does_not_filter(): void
    {
        [$user, $library] = $this->setupUserLibrary();
        $bookA = $this->seedBook($library, '0aaaaaaa-1111-4111-8111-111111111111', 'h');
        $bookB = $this->seedBook($library, '0bbbbbbb-2222-4222-8222-222222222222', 'i');

        Sanctum::actingAs($user);

        $basePayload = [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [
                    $bookA['uuid'] => ['m' => str_repeat('a', 64), 'c' => null, 'f' => null],
                    $bookB['uuid'] => ['m' => str_repeat('b', 64), 'c' => null, 'f' => null],
                ],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
            ],
        ];

        $payloadEmpty = $basePayload;
        $payloadEmpty['options']['metadata_candidate_uuids'] = [];
        $responseEmpty = $this->postJson('/api/sync/v5', $payloadEmpty);
        $responseEmpty->assertOk();
        $missingEmpty = collect($responseEmpty->json('missing_from_server') ?? []);
        $this->assertNotNull($missingEmpty->firstWhere('uuid', $bookA['uuid']));
        $this->assertNotNull($missingEmpty->firstWhere('uuid', $bookB['uuid']));

        $payloadNull = $basePayload;
        $payloadNull['options']['metadata_candidate_uuids'] = null;
        $responseNull = $this->postJson('/api/sync/v5', $payloadNull);
        $responseNull->assertOk();
        $missingNull = collect($responseNull->json('missing_from_server') ?? []);
        $this->assertNotNull($missingNull->firstWhere('uuid', $bookA['uuid']));
        $this->assertNotNull($missingNull->firstWhere('uuid', $bookB['uuid']));
    }

    public function test_sync_v5_does_not_report_deleted_on_server_outside_candidate_subset(): void
    {
        [$user, $library] = $this->setupUserLibrary();
        $deleted = $this->seedBook($library, '0ccccccc-3333-4333-8333-333333333333', 'j');
        DB::table('books')
            ->where('uuid', $deleted['uuid'])
            ->where('library_id', $library->id)
            ->where('user_id', $library->user_id)
            ->update([
                'deleted_at' => now(),
                'last_modified' => now(),
                'updated_at' => now(),
            ]);

        Sanctum::actingAs($user);
        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                // intentionally excludes deleted uuid
                'metadata_candidate_uuids' => ['00000000-0000-4000-8000-000000000000'],
            ],
        ]);

        $response->assertOk();
        $deletedOnServer = collect($response->json('deleted_on_server') ?? []);
        $this->assertFalse($deletedOnServer->contains($deleted['uuid']));
    }

    public function test_sync_v5_reports_deleted_on_server_when_uuid_is_in_candidate_subset(): void
    {
        [$user, $library] = $this->setupUserLibrary();
        $deleted = $this->seedBook($library, '0ddddddd-4444-4444-8444-444444444444', 'k');
        DB::table('books')
            ->where('uuid', $deleted['uuid'])
            ->where('library_id', $library->id)
            ->where('user_id', $library->user_id)
            ->update([
                'deleted_at' => now(),
                'last_modified' => now(),
                'updated_at' => now(),
            ]);

        Sanctum::actingAs($user);
        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $library->id,
            'calibre_library_uuid' => $library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => [
                'b' => [],
                'd' => [],
            ],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => [$deleted['uuid']],
            ],
        ]);

        $response->assertOk();
        $deletedOnServer = collect($response->json('deleted_on_server') ?? []);
        $this->assertTrue($deletedOnServer->contains($deleted['uuid']));
    }

    private function setupUserLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        return [$user, $library];
    }

    private function seedBook(Library $library, string $uuid, string $seed): array
    {
        $metadata = str_repeat($seed, 64);
        $cover = str_repeat('a', 64);
        $file = str_repeat('b', 64);
        $lastModified = Carbon::create(2026, 3, 3, 12, 0, 0, 'UTC');
        $bookId = 78000 + ord($seed);

        $bookRow = [
            'id' => $bookId,
            'uuid' => $uuid,
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'title' => 'Merkle Candidate Book ' . $seed,
            'path' => 'Merkle Candidate Book ' . $seed,
            'author_sort' => 'Author ' . strtoupper($seed),
            'series_index' => 1.0,
            'timestamp' => now(),
            'pubdate' => now(),
            'last_modified' => $lastModified,
            'has_cover' => false,
            'cover_missing' => false,
            'isbn' => '',
            'lccn' => '',
            'description' => null,
            'rating' => null,
            'flags' => 1,
            'created_at' => now(),
            'updated_at' => now(),
        ];
        if (Schema::hasColumn('books', 'cover_original_hash')) {
            $bookRow['cover_original_hash'] = 'sha256:' . $cover;
        }
        if (Schema::hasColumn('books', 'cover_optimized_hash')) {
            $bookRow['cover_optimized_hash'] = null;
        }
        if (Schema::hasColumn('books', 'cover_optimized_path')) {
            $bookRow['cover_optimized_path'] = null;
        }
        if (Schema::hasColumn('books', 'cover_url')) {
            $bookRow['cover_url'] = null;
        }
        // metadata_hash_cache column deprecated — VIEW is only source of truth
        DB::table('books')->insert($bookRow);

        DB::table('files_store')->updateOrInsert(
            ['sha256' => $file],
            [
                'storage_key' => 'ebooks/' . $seed . '.epub',
                'storage_provider' => 'r2',
                'storage_url' => 'https://example.test/' . $seed . '.epub',
                'ref_count' => 1,
                'created_at' => now(),
                'updated_at' => now(),
            ]
        );

        $bookFileRow = [
            'book' => $uuid,
            'user_id' => $library->user_id,
            'library_id' => (string) $library->id,
            'format' => 'EPUB',
            'name' => 'merkle-candidate-' . $seed . '.epub',
            'file_hash' => $file,
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
            $bookFileRow['uuid'] = $this->deterministicUuid($uuid . '|EPUB');
        }
        DB::table('books_files')->insert($bookFileRow);

        return [
            'uuid' => $uuid,
            'metadata' => $metadata,
        ];
    }

    private function deterministicUuid(string $seed): string
    {
        $hex = md5($seed);
        return sprintf(
            '%s-%s-%s-%s-%s',
            substr($hex, 0, 8),
            substr($hex, 8, 4),
            substr($hex, 12, 4),
            substr($hex, 16, 4),
            substr($hex, 20, 12)
        );
    }
}
