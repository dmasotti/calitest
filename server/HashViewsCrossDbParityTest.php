<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Services\Sync\MetadataHasherV2;
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
        $driver = DB::getDriverName();
        $this->rebuildParityViews($driver);

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

        $expected = MetadataHasherV2::computeHash([
            'uuid' => $uuid,
            'title' => 'Parity Book',
            'author_sort' => 'Rossi, Mario',
            'series' => ['name' => 'Saga', 'index' => 2.0],
            'tags' => ['zeta', 'alpha'],
            'identifiers' => ['isbn' => '9780000000001', 'amazon' => 'A-01'],
            'languages' => ['it', 'en'],
            'pubdate' => '2024-01-01 00:00:00',
            'rating' => 4,
        ]);

        $this->assertSame($hash1, $hash2, 'Hash must be invariant to relation insert order');
        $this->assertSame($expected, $hash1, 'View hash must match canonical MetadataHasherV2 hash');

        if ($driver === 'mysql') {
            $rowProd = DB::table('books_hash_v2')
                ->where('user_id', $user->id)
                ->where('library_id', $library->id)
                ->where('uuid', $uuid)
                ->first();
            $this->assertNotNull($rowProd);
            $this->assertSame($hash1, hash('sha256', (string) $rowProd->hash_payload));
        }
    }

    public function test_library_hash_matches_manual_concat_hash(): void
    {
        [$user, $library] = $this->seedUserLibrary();
        $driver = DB::getDriverName();
        $this->rebuildParityViews($driver);

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

        $payloads = DB::table('test_books_hash_v2')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->orderBy('uuid')
            ->pluck('hash_payload')
            ->all();

        $manualHash = hash('sha256', implode('', $payloads));

        if ($driver === 'mysql') {
            $row = DB::table('test_library_hash')
                ->where('user_id', $user->id)
                ->where('library_id', $library->id)
                ->first();
            $this->assertNotNull($row);
            $this->assertSame($manualHash, strtolower((string) $row->library_hash));
            $this->assertSame(2, (int) $row->total_books);
        } else {
            $row = DB::table('test_library_hash_payload')
                ->where('user_id', $user->id)
                ->where('library_id', $library->id)
                ->first();
            $this->assertNotNull($row);
            $this->assertSame($manualHash, hash('sha256', (string) $row->library_payload));
            $this->assertSame(2, (int) $row->total_books);
        }
    }

    private function seedUserLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);

        return [$user, $library];
    }

    private function bookMetadataHash(int $userId, int $libraryId, string $uuid): string
    {
        $row = DB::table('test_books_hash_v2')
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

    private function rebuildParityViews(string $driver): void
    {
        DB::statement('DROP VIEW IF EXISTS test_library_hash');
        DB::statement('DROP VIEW IF EXISTS test_library_hash_payload');
        DB::statement('DROP VIEW IF EXISTS test_books_hash_v2');

        if ($driver === 'mysql') {
            DB::statement("
                CREATE VIEW test_books_hash_v2 AS
                SELECT
                    b.id as book_id,
                    b.uuid,
                    b.user_id,
                    b.library_id,
                    b.last_modified,
                    CONCAT_WS('|',
                        COALESCE(b.uuid, ''),
                        COALESCE(b.title, ''),
                        COALESCE(b.author_sort, ''),
                        COALESCE(series_agg.series_name, ''),
                        COALESCE(FORMAT(b.series_index, 1), ''),
                        COALESCE(tags_agg.tags_csv, ''),
                        COALESCE(ident_agg.identifiers_csv, ''),
                        '',
                        COALESCE(lang_agg.languages_csv, ''),
                        COALESCE(b.pubdate, ''),
                        COALESCE(CAST(b.rating AS CHAR), ''),
                        ''
                    ) as hash_payload
                FROM books b
                LEFT JOIN (
                    SELECT bsl.book, bsl.user_id, bsl.library_id, MAX(bs.name) AS series_name
                    FROM books_series_link bsl
                    JOIN books_series bs
                        ON bs.id = bsl.series
                        AND bs.user_id = bsl.user_id
                        AND bs.library_id = bsl.library_id
                    WHERE bsl.deleted_at IS NULL AND bs.deleted_at IS NULL
                    GROUP BY bsl.book, bsl.user_id, bsl.library_id
                ) series_agg
                    ON series_agg.book = b.uuid
                    AND series_agg.user_id = b.user_id
                    AND series_agg.library_id = b.library_id
                LEFT JOIN (
                    SELECT btl.book, btl.user_id, btl.library_id,
                           GROUP_CONCAT(bt.name ORDER BY bt.name SEPARATOR ',') AS tags_csv
                    FROM books_tags_link btl
                    JOIN books_tags bt
                        ON bt.id = btl.tag
                        AND bt.user_id = btl.user_id
                        AND bt.library_id = btl.library_id
                    WHERE btl.deleted_at IS NULL AND bt.deleted_at IS NULL
                    GROUP BY btl.book, btl.user_id, btl.library_id
                ) tags_agg
                    ON tags_agg.book = b.uuid
                    AND tags_agg.user_id = b.user_id
                    AND tags_agg.library_id = b.library_id
                LEFT JOIN (
                    SELECT bi.book, bi.user_id, bi.library_id,
                           GROUP_CONCAT(CONCAT(bi.type, ':', bi.val) ORDER BY bi.type SEPARATOR ',') AS identifiers_csv
                    FROM books_identifiers bi
                    WHERE bi.deleted_at IS NULL
                    GROUP BY bi.book, bi.user_id, bi.library_id
                ) ident_agg
                    ON ident_agg.book = b.uuid
                    AND ident_agg.user_id = b.user_id
                    AND ident_agg.library_id = b.library_id
                LEFT JOIN (
                    SELECT bll.book, bll.user_id, bll.library_id,
                           GROUP_CONCAT(bl.lang_code ORDER BY bl.lang_code SEPARATOR ',') AS languages_csv
                    FROM books_languages_link bll
                    JOIN books_languages bl
                        ON bl.id = bll.lang_code
                        AND bl.user_id = bll.user_id
                        AND bl.library_id = bll.library_id
                    WHERE bll.deleted_at IS NULL AND bl.deleted_at IS NULL
                    GROUP BY bll.book, bll.user_id, bll.library_id
                ) lang_agg
                    ON lang_agg.book = b.uuid
                    AND lang_agg.user_id = b.user_id
                    AND lang_agg.library_id = b.library_id
                WHERE b.uuid IS NOT NULL
            ");

            DB::statement("
                CREATE VIEW test_library_hash AS
                SELECT
                    user_id,
                    library_id,
                    SHA2(GROUP_CONCAT(hash_payload ORDER BY uuid SEPARATOR ''), 256) as library_hash,
                    COUNT(*) as total_books,
                    MAX(last_modified) as last_modified
                FROM test_books_hash_v2
                GROUP BY user_id, library_id
            ");

            return;
        }

        DB::statement("
            CREATE VIEW test_books_hash_v2 AS
            SELECT
                b.id as book_id,
                b.uuid,
                b.user_id,
                b.library_id,
                b.last_modified,
                (
                    COALESCE(b.uuid, '') || '|' ||
                    COALESCE(b.title, '') || '|' ||
                    COALESCE(b.author_sort, '') || '|' ||
                    COALESCE(series_agg.series_name, '') || '|' ||
                    CASE WHEN b.series_index IS NULL THEN '' ELSE printf('%.1f', CAST(b.series_index AS REAL)) END || '|' ||
                    COALESCE(tags_agg.tags_csv, '') || '|' ||
                    COALESCE(ident_agg.identifiers_csv, '') || '|' ||
                    '' || '|' ||
                    COALESCE(lang_agg.languages_csv, '') || '|' ||
                    COALESCE(CAST(b.pubdate AS TEXT), '') || '|' ||
                    COALESCE(CAST(b.rating AS TEXT), '') || '|' ||
                    ''
                ) as hash_payload
            FROM books b
            LEFT JOIN (
                SELECT bsl.book, bsl.user_id, bsl.library_id, MAX(bs.name) AS series_name
                FROM books_series_link bsl
                JOIN books_series bs
                    ON bs.id = bsl.series
                    AND bs.user_id = bsl.user_id
                    AND bs.library_id = bsl.library_id
                WHERE bsl.deleted_at IS NULL AND bs.deleted_at IS NULL
                GROUP BY bsl.book, bsl.user_id, bsl.library_id
            ) series_agg
                ON series_agg.book = b.uuid
                AND series_agg.user_id = b.user_id
                AND series_agg.library_id = b.library_id
            LEFT JOIN (
                SELECT t.book, t.user_id, t.library_id, group_concat(t.name, ',') AS tags_csv
                FROM (
                    SELECT btl.book, btl.user_id, btl.library_id, bt.name
                    FROM books_tags_link btl
                    JOIN books_tags bt
                        ON bt.id = btl.tag
                        AND bt.user_id = btl.user_id
                        AND bt.library_id = btl.library_id
                    WHERE btl.deleted_at IS NULL AND bt.deleted_at IS NULL
                    ORDER BY bt.name
                ) t
                GROUP BY t.book, t.user_id, t.library_id
            ) tags_agg
                ON tags_agg.book = b.uuid
                AND tags_agg.user_id = b.user_id
                AND tags_agg.library_id = b.library_id
            LEFT JOIN (
                SELECT i.book, i.user_id, i.library_id, group_concat(i.pair, ',') AS identifiers_csv
                FROM (
                    SELECT bi.book, bi.user_id, bi.library_id, (bi.type || ':' || bi.val) AS pair
                    FROM books_identifiers bi
                    WHERE bi.deleted_at IS NULL
                    ORDER BY bi.type
                ) i
                GROUP BY i.book, i.user_id, i.library_id
            ) ident_agg
                ON ident_agg.book = b.uuid
                AND ident_agg.user_id = b.user_id
                AND ident_agg.library_id = b.library_id
            LEFT JOIN (
                SELECT l.book, l.user_id, l.library_id, group_concat(l.lang_code, ',') AS languages_csv
                FROM (
                    SELECT bll.book, bll.user_id, bll.library_id, bl.lang_code
                    FROM books_languages_link bll
                    JOIN books_languages bl
                        ON bl.id = bll.lang_code
                        AND bl.user_id = bll.user_id
                        AND bl.library_id = bll.library_id
                    WHERE bll.deleted_at IS NULL AND bl.deleted_at IS NULL
                    ORDER BY bl.lang_code
                ) l
                GROUP BY l.book, l.user_id, l.library_id
            ) lang_agg
                ON lang_agg.book = b.uuid
                AND lang_agg.user_id = b.user_id
                AND lang_agg.library_id = b.library_id
            WHERE b.uuid IS NOT NULL
        ");

        DB::statement("
            CREATE VIEW test_library_hash_payload AS
            SELECT
                x.user_id,
                x.library_id,
                group_concat(x.hash_payload, '') AS library_payload,
                COUNT(*) as total_books,
                MAX(x.last_modified) as last_modified
            FROM (
                SELECT user_id, library_id, hash_payload, last_modified
                FROM test_books_hash_v2
                ORDER BY uuid
            ) x
            GROUP BY x.user_id, x.library_id
        ");
    }
}

