<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Tests\TestCase;

class HashViewsCrossDbParityTest extends TestCase
{
    use RefreshDatabase;

    public function test_book_metadata_hash_is_stable_across_relation_ordering(): void
    {
        [$user, $library] = $this->seedUserLibrary();

        $uuid = (string) Str::uuid();
        $now = now();

        DB::table('books')->insert([
            'id' => 3101,
            'uuid' => $uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Parity Book',
            'author_sort' => 'Rossi, Mario',
            'series_index' => 2.0,
            'pubdate' => '2024-01-01 00:00:00',
            'rating' => 4,
            'path' => 'parity-book',
            'flags' => 1,
            'has_cover' => 0,
            'last_modified' => $now,
            'created_at' => $now,
            'updated_at' => $now,
        ]);

        DB::table('books_series')->insert([
            'id' => 7001,
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => 'Saga',
            'sort' => 'Saga',
            'created_at' => $now,
            'updated_at' => $now,
        ]);
        DB::table('books_series_link')->insert([
            'id' => 7101,
            'uuid' => (string) Str::uuid(),
            'book' => $uuid,
            'series' => 7001,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => $now,
            'updated_at' => $now,
        ]);

        DB::table('books_tags')->insert([
            [
                'id' => 7201,
                'uuid' => (string) Str::uuid(),
                'user_id' => $user->id,
                'library_id' => $library->id,
                'name' => 'zeta',
                'created_at' => $now,
                'updated_at' => $now,
            ],
            [
                'id' => 7202,
                'uuid' => (string) Str::uuid(),
                'user_id' => $user->id,
                'library_id' => $library->id,
                'name' => 'alpha',
                'created_at' => $now,
                'updated_at' => $now,
            ],
        ]);

        DB::table('books_languages')->insert([
            [
                'id' => 7301,
                'uuid' => (string) Str::uuid(),
                'user_id' => $user->id,
                'library_id' => $library->id,
                'lang_code' => 'it',
                'created_at' => $now,
                'updated_at' => $now,
            ],
            [
                'id' => 7302,
                'uuid' => (string) Str::uuid(),
                'user_id' => $user->id,
                'library_id' => $library->id,
                'lang_code' => 'en',
                'created_at' => $now,
                'updated_at' => $now,
            ],
        ]);

        $this->insertTagLinks($user->id, $library->id, $uuid, [7201, 7202], $now);
        $this->insertLanguageLinks($user->id, $library->id, $uuid, [7301, 7302], $now);
        $this->insertIdentifiers($user->id, $library->id, $uuid, [
            ['type' => 'isbn', 'val' => '9780000000001'],
            ['type' => 'amazon', 'val' => 'A-01'],
        ], $now);

        $hash1 = $this->bookMetadataHash($user->id, $library->id, $uuid);

        DB::table('books_tags_link')->where('user_id', $user->id)->where('library_id', $library->id)->where('book', $uuid)->delete();
        DB::table('books_languages_link')->where('user_id', $user->id)->where('library_id', $library->id)->where('book', $uuid)->delete();
        DB::table('books_identifiers')->where('user_id', $user->id)->where('library_id', $library->id)->where('book', $uuid)->delete();

        $this->insertTagLinks($user->id, $library->id, $uuid, [7202, 7201], $now);
        $this->insertLanguageLinks($user->id, $library->id, $uuid, [7302, 7301], $now);
        $this->insertIdentifiers($user->id, $library->id, $uuid, [
            ['type' => 'amazon', 'val' => 'A-01'],
            ['type' => 'isbn', 'val' => '9780000000001'],
        ], $now);

        $hash2 = $this->bookMetadataHash($user->id, $library->id, $uuid);
        $payloadHash = $this->bookPayloadHash($user->id, $library->id, $uuid);

        $this->assertSame($hash1, $hash2, 'Hash must be invariant to relation insert order');
        $this->assertSame($payloadHash, $hash1, 'View metadata_hash must equal SHA256(hash_payload)');
    }

    public function test_library_hash_matches_manual_concat_hash(): void
    {
        [$user, $library] = $this->seedUserLibrary();

        $now = now();
        $uuidA = (string) Str::uuid();
        $uuidB = (string) Str::uuid();

        DB::table('books')->insert([
            [
                'id' => 3201,
                'uuid' => $uuidA,
                'user_id' => $user->id,
                'library_id' => $library->id,
                'title' => 'Book A',
                'author_sort' => 'Author, A',
                'series_index' => 1.0,
                'path' => 'book-a',
                'flags' => 1,
                'has_cover' => 0,
                'last_modified' => $now,
                'created_at' => $now,
                'updated_at' => $now,
            ],
            [
                'id' => 3202,
                'uuid' => $uuidB,
                'user_id' => $user->id,
                'library_id' => $library->id,
                'title' => 'Book B',
                'author_sort' => 'Author, B',
                'series_index' => 1.0,
                'path' => 'book-b',
                'flags' => 1,
                'has_cover' => 0,
                'last_modified' => $now->copy()->addSecond(),
                'created_at' => $now,
                'updated_at' => $now,
            ],
        ]);

        $payloads = DB::table('books_hash_v2')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->orderByRaw("replace(lower(uuid), '-', '')")
            ->get()
            ->map(function ($row) {
                $metadataHash = (string) ($row->metadata_hash ?? '');
                return $metadataHash !== ''
                    ? strtolower($metadataHash)
                    : hash('sha256', (string) ($row->hash_payload ?? ''));
            })
            ->all();

        $manualHash = hash('sha256', implode('', $payloads));
        $row = DB::table('library_hash')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->first();
        $this->assertNotNull($row);
        $this->assertSame($manualHash, strtolower((string) $row->library_metadata_hash));
        $this->assertSame(2, (int) $row->total_books);
    }

    private function seedUserLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);

        return [$user, $library];
    }

    private function bookMetadataHash(int $userId, int $libraryId, string $uuid): string
    {
        $row = DB::table('books_hash_v2')
            ->where('user_id', $userId)
            ->where('library_id', $libraryId)
            ->where('uuid', $uuid)
            ->first();

        $this->assertNotNull($row);
        $metadataHash = (string) ($row->metadata_hash ?? '');
        if ($metadataHash !== '') {
            return strtolower($metadataHash);
        }

        return hash('sha256', (string) ($row->hash_payload ?? ''));
    }

    private function bookPayloadHash(int $userId, int $libraryId, string $uuid): string
    {
        $row = DB::table('books_hash_v2')
            ->where('user_id', $userId)
            ->where('library_id', $libraryId)
            ->where('uuid', $uuid)
            ->first();

        $this->assertNotNull($row);
        return hash('sha256', (string) $row->hash_payload);
    }

    private function insertTagLinks(int $userId, int $libraryId, string $uuid, array $tagIds, $now): void
    {
        $rows = [];
        $seed = 7400;
        foreach ($tagIds as $tagId) {
            $seed++;
            $rows[] = [
                'id' => $seed,
                'uuid' => (string) Str::uuid(),
                'book' => $uuid,
                'tag' => $tagId,
                'user_id' => $userId,
                'library_id' => $libraryId,
                'created_at' => $now,
                'updated_at' => $now,
            ];
        }
        DB::table('books_tags_link')->insert($rows);
    }

    private function insertLanguageLinks(int $userId, int $libraryId, string $uuid, array $languageIds, $now): void
    {
        $rows = [];
        $seed = 7500;
        foreach ($languageIds as $languageId) {
            $seed++;
            $rows[] = [
                'id' => $seed,
                'uuid' => (string) Str::uuid(),
                'book' => $uuid,
                'lang_code' => $languageId,
                'user_id' => $userId,
                'library_id' => $libraryId,
                'created_at' => $now,
                'updated_at' => $now,
            ];
        }
        DB::table('books_languages_link')->insert($rows);
    }

    private function insertIdentifiers(int $userId, int $libraryId, string $uuid, array $identifiers, $now): void
    {
        $rows = [];
        $seed = 7600;
        foreach ($identifiers as $identifier) {
            $seed++;
            $rows[] = [
                'id' => $seed,
                'uuid' => (string) Str::uuid(),
                'book' => $uuid,
                'type' => $identifier['type'],
                'val' => $identifier['val'],
                'user_id' => $userId,
                'library_id' => $libraryId,
                'created_at' => $now,
                'updated_at' => $now,
            ];
        }
        DB::table('books_identifiers')->insert($rows);
    }

}
