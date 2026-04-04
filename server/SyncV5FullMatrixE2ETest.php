<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use App\Services\Sync\MetadataHasher;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

/**
 * Full matrix E2E test — 15 books, each covering a specific edge case.
 * Uses real data patterns from CalibreLargeLocal fixture.
 *
 * This tests the COMPLETE flow: client sends hash → server compares →
 * server responds → verify response correctness.
 */
class SyncV5FullMatrixE2ETest extends TestCase
{
    use RefreshDatabase;

    private User $user;
    private Library $library;

    protected function setUp(): void
    {
        parent::setUp();
        $this->user = User::factory()->create();
        $this->library = Library::factory()->create(['user_id' => $this->user->id]);
        Sanctum::actingAs($this->user);
    }

    private function createBook(string $uuid, array $overrides = []): UserBook
    {
        return UserBook::create(array_merge([
            'id' => crc32($uuid) & 0x7FFFFFFF,
            'uuid' => $uuid,
            'user_id' => $this->user->id,
            'library_id' => (string) $this->library->id,
            'title' => 'Book ' . substr($uuid, 0, 8),
            'path' => 'book-' . substr($uuid, 0, 8),
            'pubdate' => '2020-06-15 00:00:00',
            'last_modified' => now(),
            'has_cover' => false,
        ], $overrides));
    }

    private function applyMeta(UserBook $book, array $item): void
    {
        app(BookMetadataHandler::class)->applyBookMetadata(
            $book, $item, $this->user, $this->library->id
        );
        $book->refresh();
    }

    private function getServerHash(string $uuid): ?string
    {
        $book = UserBook::where('uuid', $uuid)->first();
        return $book ? ($book->metadata_hash ?: null) : null;
    }

    private function sync(array $clientBooks, array $candidateUuids, array $deleted = []): array
    {
        $response = $this->postJson('/api/sync/v5', [
            'library_id' => (string) $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
            'cursor' => null,
            'batch_size' => 100,
            'client_books' => ['b' => $clientBooks, 'd' => $deleted],
            'options' => [
                'sync_files_enabled' => false,
                'sync_covers_enabled' => false,
                'metadata_candidate_uuids' => $candidateUuids,
            ],
        ]);
        $response->assertOk();
        return $response->json();
    }

    /**
     * Full matrix: 15 cases in a single test, all using real-pattern data.
     */
    public function test_full_15_case_matrix(): void
    {
        // ── Prepare 15 books, each for a specific case ──────────────

        // Case 1: All aligned — hash match, skip
        $b1 = $this->createBook('11111111-1111-1111-1111-111111111111');
        $this->applyMeta($b1, [
            'uuid' => $b1->uuid, 'title' => 'El Quijote',
            'authors' => [['name' => 'Miguel de Cervantes']],
            'tags' => [['name' => 'Clásicos'], ['name' => 'Novela']],
            'series' => null, 'identifiers' => ['isbn' => '9788420412146'],
            'publisher' => 'Cátedra', 'languages' => ['spa'],
            'comments' => '<p>La gran novela española</p>',
            'rating' => 10, 'pubdate' => '1605-01-16',
        ]);
        $hash1 = $b1->metadata_hash;

        // Case 2: Server modified — title changed on server, client has old hash
        $b2 = $this->createBook('22222222-2222-2222-2222-222222222222');
        $this->applyMeta($b2, [
            'uuid' => $b2->uuid, 'title' => 'Original Title',
            'authors' => [['name' => 'Author Two']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => ['eng'],
            'comments' => null, 'rating' => null, 'pubdate' => '2020-01-01',
        ]);
        $hash2_old = $b2->metadata_hash;
        // Now modify on server
        $this->applyMeta($b2, [
            'uuid' => $b2->uuid, 'title' => 'Server Modified Title',
            'authors' => [['name' => 'Author Two']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => ['eng'],
            'comments' => null, 'rating' => null, 'pubdate' => '2020-01-01',
        ]);
        $hash2_new = $b2->metadata_hash;
        $this->assertNotSame($hash2_old, $hash2_new);

        // Case 5: First sync (book on server, client sends wrong hash)
        $b5 = $this->createBook('55555555-5555-5555-5555-555555555555');
        $this->applyMeta($b5, [
            'uuid' => $b5->uuid, 'title' => 'First Sync Book',
            'authors' => [['name' => 'New Author']],
            'tags' => [['name' => 'Ciencia ficción']], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => ['spa'],
            'comments' => null, 'rating' => null, 'pubdate' => '2023-06-01',
        ]);

        // Case 6: Book only on client (not on server)
        $uuid6 = '66666666-6666-6666-6666-666666666666';

        // Case 7: Book only on server (client doesn't send it)
        $b7 = $this->createBook('77777777-7777-7777-7777-777777777777');
        $this->applyMeta($b7, [
            'uuid' => $b7->uuid, 'title' => 'Server Only Book',
            'authors' => [['name' => 'Server Author']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => [], 'comments' => null,
            'rating' => null, 'pubdate' => null,
        ]);

        // Case 8: Book deleted on server
        $b8 = $this->createBook('88888888-8888-8888-8888-888888888888');
        $this->applyMeta($b8, [
            'uuid' => $b8->uuid, 'title' => 'Deleted Book',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ]);
        $b8->delete(); // soft delete

        // Case 9: Pre-1970 pubdate
        $b9 = $this->createBook('99999999-9999-9999-9999-999999999999');
        $this->applyMeta($b9, [
            'uuid' => $b9->uuid, 'title' => 'Old Classic',
            'authors' => [['name' => 'Julio Verne']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => ['spa'],
            'comments' => null, 'rating' => null, 'pubdate' => '1865-11-01',
        ]);
        $hash9 = $b9->metadata_hash;

        // Case 10: Sentinel 0101 pubdate
        $b10 = $this->createBook('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa');
        $this->applyMeta($b10, [
            'uuid' => $b10->uuid, 'title' => 'No Date Book',
            'authors' => [['name' => 'Unknown']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => '0101-01-01',
        ]);
        $hash10 = $b10->metadata_hash;

        // Case 11: UTF-8 characters + HTML description
        $b11 = $this->createBook('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb');
        $this->applyMeta($b11, [
            'uuid' => $b11->uuid, 'title' => 'Crónicas del señor López',
            'authors' => [['name' => 'José María García-López']],
            'tags' => [['name' => 'Histórica'], ['name' => 'Acción']],
            'series' => ['name' => 'Série Épica', 'index' => 3.0],
            'identifiers' => ['isbn' => '9788401234567'],
            'publisher' => 'Éditions Gallimard', 'languages' => ['spa', 'fra'],
            'comments' => '<div><p>Una <em>extraordinaria</em> crónica con acentos: àèìòù äëïöü ñ ç</p></div>',
            'rating' => 8, 'pubdate' => '2019-03-15',
        ]);
        $hash11 = $b11->metadata_hash;

        // Case 12: Multiple authors (sort order matters)
        $b12 = $this->createBook('cccccccc-cccc-cccc-cccc-cccccccccccc');
        $this->applyMeta($b12, [
            'uuid' => $b12->uuid, 'title' => 'Collaborative Work',
            'authors' => [['name' => 'Zoe Adams'], ['name' => 'Alice Zeta'], ['name' => 'Maria Beta']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => ['eng'],
            'comments' => null, 'rating' => null, 'pubdate' => '2022-09-01',
        ]);
        $hash12 = $b12->metadata_hash;

        // Case 14: Hash match but server LM different (hash is truth → skip)
        $b14 = $this->createBook('eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee');
        $this->applyMeta($b14, [
            'uuid' => $b14->uuid, 'title' => 'Timestamp Diff',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => null,
        ]);
        $hash14 = $b14->metadata_hash;

        // Case 15: Hash mismatch, same server version → apply
        $b15 = $this->createBook('ffffffff-ffff-ffff-ffff-ffffffffffff');
        $this->applyMeta($b15, [
            'uuid' => $b15->uuid, 'title' => 'Mismatch Same Version',
            'authors' => [['name' => 'Final Author']],
            'tags' => [], 'series' => null, 'identifiers' => [],
            'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null, 'pubdate' => '2024-01-01',
        ]);

        // ── Sync request ────────────────────────────────────────────

        $allCandidates = [
            $b1->uuid, $b2->uuid, $b5->uuid, $uuid6, $b8->uuid,
            $b9->uuid, $b10->uuid, $b11->uuid, $b12->uuid,
            $b14->uuid, $b15->uuid,
            // NOT b7 — server only, not in candidates
        ];

        $clientBooks = [
            // Case 1: correct hash → skip
            $b1->uuid => ['m' => $hash1, 'c' => null, 'f' => null],
            // Case 2: old hash → server sends update
            $b2->uuid => ['m' => $hash2_old, 'c' => null, 'f' => null],
            // Case 5: wrong hash (first sync) → server sends update
            $b5->uuid => ['m' => str_repeat('0', 64), 'c' => null, 'f' => null],
            // Case 6: client-only book → missing_from_server
            $uuid6 => ['m' => str_repeat('a', 64), 'c' => null, 'f' => null],
            // Case 8: deleted on server → deleted_on_server
            $b8->uuid => ['m' => str_repeat('b', 64), 'c' => null, 'f' => null],
            // Case 9: pre-1970 pubdate, correct hash → skip
            $b9->uuid => ['m' => $hash9, 'c' => null, 'f' => null],
            // Case 10: sentinel pubdate, correct hash → skip
            $b10->uuid => ['m' => $hash10, 'c' => null, 'f' => null],
            // Case 11: UTF-8 + HTML, correct hash → skip
            $b11->uuid => ['m' => $hash11, 'c' => null, 'f' => null],
            // Case 12: multiple authors sorted, correct hash → skip
            $b12->uuid => ['m' => $hash12, 'c' => null, 'f' => null],
            // Case 14: hash match, different server LM → skip (hash is truth)
            $b14->uuid => ['m' => $hash14, 'c' => null, 'f' => null],
            // Case 15: hash mismatch → update
            $b15->uuid => ['m' => str_repeat('f', 64), 'c' => null, 'f' => null],
        ];

        $result = $this->sync($clientBooks, $allCandidates);

        // ── Verify all cases ────────────────────────────────────────

        $updates = collect($result['updates_for_client'] ?? []);
        $missing = collect($result['missing_from_server'] ?? []);
        $deleted = $result['deleted_on_server'] ?? [];
        $skipped = $result['skipped_hash'] ?? 0;

        // Case 1: skip (hash match)
        $this->assertNull($updates->firstWhere('uuid', $b1->uuid), 'Case 1: hash match must skip');

        // Case 2: server sends update with new title
        $upd2 = $updates->firstWhere('uuid', $b2->uuid);
        $this->assertNotNull($upd2, 'Case 2: server modified → must send update');
        $this->assertSame('Server Modified Title', $upd2['title']);

        // Case 5: first sync, wrong hash → update
        $upd5 = $updates->firstWhere('uuid', $b5->uuid);
        $this->assertNotNull($upd5, 'Case 5: first sync wrong hash → update');
        $this->assertSame('First Sync Book', $upd5['title']);

        // Case 6: client-only → missing_from_server
        $miss6 = $missing->firstWhere('uuid', $uuid6);
        $this->assertNotNull($miss6, 'Case 6: client-only → missing_from_server');
        $this->assertTrue((bool) ($miss6['needs_metadata'] ?? false));

        // Case 8: deleted → deleted_on_server
        $this->assertContains($b8->uuid, $deleted, 'Case 8: deleted → deleted_on_server');
        $this->assertNull($updates->firstWhere('uuid', $b8->uuid), 'Case 8: deleted must not be in updates');

        // Case 9: pre-1970 pubdate, hash match → skip
        $this->assertNull($updates->firstWhere('uuid', $b9->uuid), 'Case 9: pre-1970 hash match → skip');

        // Case 10: sentinel pubdate, hash match → skip
        $this->assertNull($updates->firstWhere('uuid', $b10->uuid), 'Case 10: sentinel hash match → skip');

        // Case 11: UTF-8 + HTML, hash match → skip
        $this->assertNull($updates->firstWhere('uuid', $b11->uuid), 'Case 11: UTF-8 hash match → skip');

        // Case 12: multiple authors, hash match → skip
        $this->assertNull($updates->firstWhere('uuid', $b12->uuid), 'Case 12: authors sorted hash match → skip');

        // Case 14: hash match even if LM differs → skip
        $this->assertNull($updates->firstWhere('uuid', $b14->uuid), 'Case 14: hash match → skip regardless of LM');

        // Case 15: hash mismatch → update
        $upd15 = $updates->firstWhere('uuid', $b15->uuid);
        $this->assertNotNull($upd15, 'Case 15: hash mismatch → update');

        // Verify has_more is false
        $this->assertFalse((bool) ($result['has_more'] ?? true));

        // Verify: exactly 3 updates (case 2, 5, 15)
        $expectedUpdateUuids = [$b2->uuid, $b5->uuid, $b15->uuid];
        $actualUpdateUuids = $updates->pluck('uuid')->sort()->values()->all();
        sort($expectedUpdateUuids);
        $this->assertSame($expectedUpdateUuids, $actualUpdateUuids, 'Exactly 3 updates expected');

        // Verify: exactly 1 missing (case 6)
        $this->assertCount(1, $missing->where('uuid', $uuid6));

        // Verify: exactly 1 deleted (case 8)
        $this->assertCount(1, array_filter($deleted, fn($u) => $u === $b8->uuid));
    }
}
