<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Services\Sync\MaterializedMerkleService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Tests\TestCase;

class PgsqlTouchedMetadataHashFunctionTest extends TestCase
{
    use RefreshDatabase;

    private int $nextId = 50000;

    public function test_pgsql_touched_metadata_hash_function_exists_after_migrations(): void
    {
        if (DB::getDriverName() !== 'pgsql') {
            $this->markTestSkipped('PGSQL-only touched metadata hash function existence check.');
        }

        $exists = DB::table('pg_proc as p')
            ->join('pg_namespace as n', 'n.oid', '=', 'p.pronamespace')
            ->where('n.nspname', 'public')
            ->where('p.proname', 'calimob_books_metadata_hash_v2_touched')
            ->exists();

        $this->assertTrue($exists, 'Touched metadata hash SQL function must be installed by migrations on PostgreSQL.');
    }

    public function test_pgsql_touched_metadata_hash_function_matches_books_hash_v2_edge_matrix(): void
    {
        if (DB::getDriverName() !== 'pgsql') {
            $this->markTestSkipped('PGSQL-only touched metadata hash function parity check.');
        }

        [$user, $library] = $this->makeContext();

        $cases = [
            [
                'case_id' => 'null-empty-rating-zero',
                'title' => 'Null Empty Rating Zero',
                'description' => '',
                'pubdate' => null,
                'authors' => ['Ada Null'],
                'tags' => [],
                'identifiers' => [],
                'languages' => [],
                'publisher' => null,
                'series' => null,
                'series_index' => 1.0,
                'rating' => 0,
            ],
            [
                'case_id' => 'unicode-spaces-rating-eight',
                'title' => 'Title  With  Internal  Spaces',
                'description' => 'Café  déjà vu  with  spacing',
                'pubdate' => '2024-01-02 03:04:05',
                'authors' => ['Zoë Éclair', 'Ada Lovelace'],
                'tags' => ['Science Fiction', 'alpha', 'Alpha'],
                'identifiers' => ['zISBN' => '9780000000001', 'asin' => 'B00TEST001'],
                'languages' => ['ita', 'eng', 'eng'],
                'publisher' => 'Éditions du Cœur',
                'series' => 'Saga  Prime',
                'series_index' => 2.5,
                'rating' => 8,
            ],
            [
                'case_id' => 'pre-1970-negative-pubdate',
                'title' => 'Before Epoch',
                'description' => 'Historical record',
                'pubdate' => '1956-12-31 18:30:00',
                'authors' => ['Historian Test'],
                'tags' => ['Archive'],
                'identifiers' => ['isbn' => '9780000000002'],
                'languages' => ['eng'],
                'publisher' => null,
                'series' => null,
                'series_index' => 1.0,
                'rating' => null,
            ],
            [
                'case_id' => 'canonical-order-relations',
                'title' => 'Ordering Case',
                'description' => 'Order must stay canonical',
                'pubdate' => '2025-05-06 07:08:09',
                'authors' => ['Bob Writer', 'Alice Writer'],
                'tags' => ['zeta', 'Alpha', 'alpha'],
                'identifiers' => ['ZTYPE' => 'z-value', 'atype' => 'a-value'],
                'languages' => ['fra', 'eng', 'fra'],
                'publisher' => 'Order Press',
                'series' => 'Case Series',
                'series_index' => 7.0,
                'rating' => 10,
            ],
        ];

        $uuids = [];
        foreach ($cases as $case) {
            $uuids[] = $this->seedBookCase($user->id, $library->id, $case);
        }

        // This call is part of the write-path contract: once the function exists,
        // refresh should use it for touched-only cache writes.
        app(MaterializedMerkleService::class)->refreshMetadataHashCacheForTouchedUuids(
            (int) $user->id,
            (int) $library->id,
            $uuids
        );

        $actualRows = $this->loadTouchedFunctionRows((int) $user->id, (int) $library->id, $uuids);
        $expectedRows = DB::table('books_hash_v2')
            ->where('user_id', (int) $user->id)
            ->where('library_id', (int) $library->id)
            ->whereIn('uuid', $uuids)
            ->orderBy('uuid')
            ->get(['uuid', 'hash_payload'])
            ->mapWithKeys(static fn ($row): array => [
                (string) $row->uuid => [
                    'hash_payload' => (string) $row->hash_payload,
                    'metadata_hash' => hash('sha256', (string) $row->hash_payload),
                ],
            ])
            ->all();

        $this->assertCount(count($uuids), $actualRows);

        foreach ($uuids as $uuid) {
            $this->assertArrayHasKey($uuid, $actualRows);
            $this->assertSame(
                $expectedRows[$uuid]['hash_payload'],
                $actualRows[$uuid]['hash_payload'],
                'Function payload mismatch for uuid=' . $uuid
            );
            $this->assertSame(
                $expectedRows[$uuid]['metadata_hash'],
                $actualRows[$uuid]['metadata_hash'],
                'Function hash mismatch for uuid=' . $uuid
            );
        }
    }

    public function test_pgsql_refresh_metadata_hash_cache_for_touched_uuids_avoids_books_hash_v2_view(): void
    {
        if (DB::getDriverName() !== 'pgsql') {
            $this->markTestSkipped('PGSQL-only touched metadata hash refresh source check.');
        }

        [$user, $library] = $this->makeContext();
        $uuid = $this->seedBookCase($user->id, $library->id, [
            'case_id' => 'refresh-source-check',
            'title' => 'Refresh Source Check',
            'description' => 'Refresh path should not read books_hash_v2',
            'pubdate' => '2024-03-04 05:06:07',
            'authors' => ['Refresh Tester'],
            'tags' => ['refresh'],
            'identifiers' => ['isbn' => '9780000000999'],
            'languages' => ['eng'],
            'publisher' => 'Refresh Press',
            'series' => null,
            'series_index' => 1.0,
            'rating' => 6,
        ]);

        DB::flushQueryLog();
        DB::enableQueryLog();

        try {
            app(MaterializedMerkleService::class)->refreshMetadataHashCacheForTouchedUuids(
                (int) $user->id,
                (int) $library->id,
                [$uuid]
            );
        } finally {
            $queries = DB::getQueryLog();
            DB::disableQueryLog();
        }

        $booksHashQueries = array_values(array_filter($queries, static function (array $entry): bool {
            $sql = strtolower((string) ($entry['query'] ?? ''));
            return str_contains($sql, 'books_hash_v2');
        }));

        $this->assertCount(
            0,
            $booksHashQueries,
            'Touched metadata cache refresh must not depend on books_hash_v2 on PostgreSQL'
        );
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'PG Touched Metadata Hash Function',
        ]);

        return [$user, $library];
    }

    private function seedBookCase(int $userId, int $libraryId, array $case): string
    {
        $uuid = (string) Str::uuid();
        $bookId = $this->nextNumericId();

        DB::table('books')->insert([
            'idx' => $bookId,
            'id' => $bookId,
            'uuid' => $uuid,
            'user_id' => $userId,
            'library_id' => $libraryId,
            'title' => $case['title'],
            'author_sort' => ($case['authors'][0] ?? 'Author, Test'),
            'series_index' => $case['series_index'] ?? 1.0,
            'description' => $case['description'],
            'pubdate' => $case['pubdate'],
            'path' => 'case-' . $case['case_id'],
            'flags' => 1,
            'has_cover' => 0,
            'last_modified' => now(),
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        foreach ($case['authors'] as $name) {
            $authorId = $this->nextNumericId();
            DB::table('books_authors')->insert([
                'idx' => $authorId,
                'id' => $authorId,
                'uuid' => (string) Str::uuid(),
                'user_id' => $userId,
                'library_id' => $libraryId,
                'name' => $name,
                'sort' => $name,
            ]);
            DB::table('books_authors_link')->insert([
                'idx' => $this->nextNumericId(),
                'id' => $this->nextNumericId(),
                'uuid' => (string) Str::uuid(),
                'book' => $uuid,
                'author' => $authorId,
                'user_id' => $userId,
                'library_id' => $libraryId,
            ]);
        }

        foreach ($case['tags'] as $name) {
            $existingTagId = DB::table('books_tags')
                ->where('user_id', $userId)
                ->where('library_id', $libraryId)
                ->where('name', $name)
                ->value('id');

            $tagId = $existingTagId !== null ? (int) $existingTagId : $this->nextNumericId();
            if ($existingTagId === null) {
                DB::table('books_tags')->insert([
                    'idx' => $tagId,
                    'id' => $tagId,
                    'uuid' => (string) Str::uuid(),
                    'user_id' => $userId,
                    'library_id' => $libraryId,
                    'name' => $name,
                ]);
            }
            DB::table('books_tags_link')->insert([
                'idx' => $this->nextNumericId(),
                'id' => $this->nextNumericId(),
                'uuid' => (string) Str::uuid(),
                'book' => $uuid,
                'tag' => $tagId,
                'user_id' => $userId,
                'library_id' => $libraryId,
            ]);
        }

        foreach ($case['identifiers'] as $type => $value) {
            $identifierId = $this->nextNumericId();
            DB::table('books_identifiers')->insert([
                'idx' => $identifierId,
                'id' => $identifierId,
                'book' => $uuid,
                'type' => $type,
                'val' => $value,
                'user_id' => $userId,
                'library_id' => $libraryId,
                'uuid' => (string) Str::uuid(),
            ]);
        }

        foreach (array_values(array_unique($case['languages'])) as $langCode) {
            $existingLanguageId = DB::table('books_languages')
                ->where('user_id', $userId)
                ->where('library_id', $libraryId)
                ->where('lang_code', $langCode)
                ->value('id');

            $languageId = $existingLanguageId !== null ? (int) $existingLanguageId : $this->nextNumericId();
            if ($existingLanguageId === null) {
                DB::table('books_languages')->insert([
                    'idx' => $languageId,
                    'id' => $languageId,
                    'uuid' => (string) Str::uuid(),
                    'user_id' => $userId,
                    'library_id' => $libraryId,
                    'lang_code' => $langCode,
                ]);
            }
            DB::table('books_languages_link')->insert([
                'idx' => $this->nextNumericId(),
                'id' => $this->nextNumericId(),
                'uuid' => (string) Str::uuid(),
                'book' => $uuid,
                'lang_code' => $languageId,
                'user_id' => $userId,
                'library_id' => $libraryId,
            ]);
        }

        if ($case['publisher'] !== null) {
            $publisherId = $this->nextNumericId();
            DB::table('books_publishers')->insert([
                'idx' => $publisherId,
                'id' => $publisherId,
                'uuid' => (string) Str::uuid(),
                'user_id' => $userId,
                'library_id' => $libraryId,
                'name' => $case['publisher'],
                'sort' => $case['publisher'],
                'link' => '',
                'created_at' => now(),
                'updated_at' => now(),
            ]);
            DB::table('books_publishers_link')->insert([
                'idx' => $this->nextNumericId(),
                'id' => $this->nextNumericId(),
                'uuid' => (string) Str::uuid(),
                'book' => $uuid,
                'publisher' => $publisherId,
                'user_id' => $userId,
                'library_id' => $libraryId,
                'created_at' => now(),
                'updated_at' => now(),
            ]);
        }

        if ($case['series'] !== null) {
            $seriesId = $this->nextNumericId();
            DB::table('books_series')->insert([
                'idx' => $seriesId,
                'id' => $seriesId,
                'uuid' => (string) Str::uuid(),
                'user_id' => $userId,
                'library_id' => $libraryId,
                'name' => $case['series'],
                'sort' => $case['series'],
                'link' => '',
            ]);
            DB::table('books_series_link')->insert([
                'idx' => $this->nextNumericId(),
                'id' => $this->nextNumericId(),
                'uuid' => (string) Str::uuid(),
                'book' => $uuid,
                'series' => $seriesId,
                'user_id' => $userId,
                'library_id' => $libraryId,
                'series_index' => $case['series_index'] ?? 1.0,
            ]);
        }

        if (array_key_exists('rating', $case) && $case['rating'] !== null) {
            $ratingId = $this->nextNumericId();
            DB::table('books_ratings')->insert([
                'idx' => $ratingId,
                'id' => $ratingId,
                'uuid' => (string) Str::uuid(),
                'user_id' => $userId,
                'library_id' => $libraryId,
                'rating' => $case['rating'],
                'link' => '',
                'created_at' => now(),
                'updated_at' => now(),
            ]);
            DB::table('books_ratings_links')->insert([
                'idx' => $this->nextNumericId(),
                'id' => $this->nextNumericId(),
                'uuid' => (string) Str::uuid(),
                'book' => $uuid,
                'rating' => $ratingId,
                'user_id' => $userId,
                'library_id' => $libraryId,
                'created_at' => now(),
                'updated_at' => now(),
            ]);
        }

        return $uuid;
    }

    private function loadTouchedFunctionRows(int $userId, int $libraryId, array $uuids): array
    {
        $arraySql = 'ARRAY[' . implode(',', array_fill(0, count($uuids), '?')) . ']::varchar[]';
        $rows = DB::select(
            <<<SQL
            SELECT uuid, hash_payload, metadata_hash
            FROM public.calimob_books_metadata_hash_v2_touched(?, ?, {$arraySql})
            ORDER BY uuid
            SQL,
            array_merge([$userId, $libraryId], $uuids)
        );

        $mapped = [];
        foreach ($rows as $row) {
            $mapped[(string) $row->uuid] = [
                'hash_payload' => (string) $row->hash_payload,
                'metadata_hash' => strtolower((string) $row->metadata_hash),
            ];
        }

        return $mapped;
    }

    private function nextNumericId(): int
    {
        return $this->nextId++;
    }
}
