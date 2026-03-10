<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class MerkleViewsCrossEngineParityTest extends TestCase
{
    use RefreshDatabase;

    public function test_metadata_merkle_views_match_sqlite_baseline_for_small_seed(): void
    {
        $driver = DB::getDriverName();
        $this->dropMerkleSeedObjects();
        $this->createMerkleSeedTable();

        $rows = [
            [
                'user_id' => 101,
                'library_id' => 201,
                'uuid' => 'aa000000-0000-4000-8000-000000000201',
                'metadata_hash' => hash('sha256', 'payload-aa'),
                'last_modified' => '2026-01-01 00:00:01',
            ],
            [
                'user_id' => 101,
                'library_id' => 201,
                'uuid' => 'ab000000-0000-4000-8000-000000000202',
                'metadata_hash' => hash('sha256', 'payload-ab'),
                'last_modified' => '2026-01-01 00:00:02',
            ],
            [
                'user_id' => 101,
                'library_id' => 201,
                'uuid' => 'ba000000-0000-4000-8000-000000000203',
                'metadata_hash' => hash('sha256', 'payload-ba'),
                'last_modified' => '2026-01-01 00:00:03',
            ],
        ];

        DB::table('test_merkle_seed')->insert($rows);
        $this->createDriverSpecificMerkleViews($driver);

        $expected = $this->computeSqliteExpected($rows);

        $actualLeaves = DB::table('test_merkle_leaves')
            ->where('user_id', 101)
            ->where('library_id', 201)
            ->orderBy('leaf_id')
            ->get(['branch_id', 'leaf_id', 'leaf_hash', 'book_count', 'uuids_json'])
            ->map(function ($row) {
                return [
                    'branch_id' => (int) $row->branch_id,
                    'leaf_id' => (int) $row->leaf_id,
                    'leaf_hash' => strtolower((string) $row->leaf_hash),
                    'book_count' => (int) $row->book_count,
                    'uuids' => json_decode((string) $row->uuids_json, true, 512, JSON_THROW_ON_ERROR),
                ];
            })
            ->all();

        $actualBranches = DB::table('test_merkle_branches')
            ->where('user_id', 101)
            ->where('library_id', 201)
            ->orderBy('branch_id')
            ->get(['branch_id', 'branch_hash', 'book_count'])
            ->map(function ($row) {
                return [
                    'branch_id' => (int) $row->branch_id,
                    'branch_hash' => strtolower((string) $row->branch_hash),
                    'book_count' => (int) $row->book_count,
                ];
            })
            ->all();

        $actualRoot = DB::table('test_merkle_root')
            ->where('user_id', 101)
            ->where('library_id', 201)
            ->first(['root_hash', 'total_books']);

        $this->assertNotNull($actualRoot);
        $this->assertSame($expected['leaves'], $actualLeaves);
        $this->assertSame($expected['branches'], $actualBranches);
        $this->assertSame($expected['root_hash'], strtolower((string) $actualRoot->root_hash));
        $this->assertSame($expected['total_books'], (int) $actualRoot->total_books);
    }

    private function createMerkleSeedTable(): void
    {
        DB::statement('
            CREATE TABLE test_merkle_seed (
                user_id BIGINT NOT NULL,
                library_id BIGINT NOT NULL,
                uuid CHAR(36) NOT NULL,
                metadata_hash CHAR(64) NOT NULL,
                last_modified TIMESTAMP NULL
            )
        ');
    }

    private function createDriverSpecificMerkleViews(string $driver): void
    {
        if (in_array($driver, ['mysql', 'mariadb'], true)) {
            DB::statement(<<<'SQL'
                CREATE VIEW test_merkle_leaves AS
                SELECT
                    s.user_id,
                    s.library_id,
                    CAST(CONV(SUBSTRING(s.leaf_hex, 1, 1), 16, 10) AS UNSIGNED) AS branch_id,
                    CAST(CONV(s.leaf_hex, 16, 10) AS UNSIGNED) AS leaf_id,
                    SHA2(GROUP_CONCAT(s.metadata_hash ORDER BY s.uuid_norm SEPARATOR ''), 256) AS leaf_hash,
                    COUNT(*) AS book_count,
                    MAX(s.last_modified) AS last_modified,
                    CONCAT('[', GROUP_CONCAT(JSON_QUOTE(s.uuid) ORDER BY s.uuid_norm SEPARATOR ','), ']') AS uuids_json
                FROM (
                    SELECT
                        user_id,
                        library_id,
                        uuid,
                        LOWER(REPLACE(uuid, '-', '')) AS uuid_norm,
                        SUBSTRING(LOWER(REPLACE(uuid, '-', '')), 1, 2) AS leaf_hex,
                        metadata_hash,
                        last_modified
                    FROM test_merkle_seed
                ) s
                GROUP BY s.user_id, s.library_id, s.leaf_hex
            SQL);

            DB::statement(<<<'SQL'
                CREATE VIEW test_merkle_branches AS
                SELECT
                    ml.user_id,
                    ml.library_id,
                    ml.branch_id,
                    SHA2(GROUP_CONCAT(ml.leaf_hash ORDER BY ml.leaf_id SEPARATOR ''), 256) AS branch_hash,
                    SUM(ml.book_count) AS book_count,
                    MAX(ml.last_modified) AS last_modified
                FROM test_merkle_leaves ml
                GROUP BY ml.user_id, ml.library_id, ml.branch_id
            SQL);

            DB::statement(<<<'SQL'
                CREATE VIEW test_merkle_root AS
                SELECT
                    mb.user_id,
                    mb.library_id,
                    SHA2(GROUP_CONCAT(mb.branch_hash ORDER BY mb.branch_id SEPARATOR ''), 256) AS root_hash,
                    SUM(mb.book_count) AS total_books,
                    MAX(mb.last_modified) AS last_modified
                FROM test_merkle_branches mb
                GROUP BY mb.user_id, mb.library_id
            SQL);

            return;
        }

        DB::statement(<<<'SQL'
            CREATE VIEW test_merkle_leaves AS
            SELECT
                s.user_id,
                s.library_id,
                floor(get_byte(decode(s.leaf_hex, 'hex'), 0) / 16.0)::integer AS branch_id,
                get_byte(decode(s.leaf_hex, 'hex'), 0)::integer AS leaf_id,
                encode(digest(string_agg(s.metadata_hash, '' ORDER BY s.uuid_norm), 'sha256'), 'hex') AS leaf_hash,
                COUNT(*)::integer AS book_count,
                MAX(s.last_modified) AS last_modified,
                CONCAT('[', string_agg(to_json(s.uuid)::text, ',' ORDER BY s.uuid_norm), ']') AS uuids_json
            FROM (
                SELECT
                    user_id,
                    library_id,
                    uuid,
                    lower(replace(uuid, '-', '')) AS uuid_norm,
                    substr(lower(replace(uuid, '-', '')), 1, 2) AS leaf_hex,
                    metadata_hash,
                    last_modified
                FROM test_merkle_seed
            ) s
            GROUP BY s.user_id, s.library_id, s.leaf_hex
        SQL);

        DB::statement(<<<'SQL'
            CREATE VIEW test_merkle_branches AS
            SELECT
                ml.user_id,
                ml.library_id,
                ml.branch_id,
                encode(digest(string_agg(ml.leaf_hash, '' ORDER BY ml.leaf_id), 'sha256'), 'hex') AS branch_hash,
                SUM(ml.book_count)::integer AS book_count,
                MAX(ml.last_modified) AS last_modified
            FROM test_merkle_leaves ml
            GROUP BY ml.user_id, ml.library_id, ml.branch_id
        SQL);

        DB::statement(<<<'SQL'
            CREATE VIEW test_merkle_root AS
            SELECT
                mb.user_id,
                mb.library_id,
                encode(digest(string_agg(mb.branch_hash, '' ORDER BY mb.branch_id), 'sha256'), 'hex') AS root_hash,
                SUM(mb.book_count)::integer AS total_books,
                MAX(mb.last_modified) AS last_modified
            FROM test_merkle_branches mb
            GROUP BY mb.user_id, mb.library_id
        SQL);
    }

    private function computeSqliteExpected(array $rows): array
    {
        $pdo = new \PDO('sqlite::memory:');
        $pdo->setAttribute(\PDO::ATTR_ERRMODE, \PDO::ERRMODE_EXCEPTION);
        $pdo->sqliteCreateFunction('sha256', static fn ($v) => hash('sha256', (string) ($v ?? '')), 1);
        $pdo->sqliteCreateFunction('hex_to_int', static fn ($v) => hexdec((string) ($v ?? '0')), 1);

        $pdo->exec('
            CREATE TABLE seed (
                user_id INTEGER NOT NULL,
                library_id INTEGER NOT NULL,
                uuid TEXT NOT NULL,
                metadata_hash TEXT NOT NULL,
                last_modified TEXT NULL
            )
        ');

        $stmt = $pdo->prepare('
            INSERT INTO seed(user_id, library_id, uuid, metadata_hash, last_modified)
            VALUES (:user_id, :library_id, :uuid, :metadata_hash, :last_modified)
        ');
        foreach ($rows as $row) {
            $stmt->execute($row);
        }

        $pdo->exec(<<<'SQL'
            CREATE VIEW tri_merkle_leaves AS
            SELECT
                user_id,
                library_id,
                hex_to_int(substr(leaf_hex, 1, 1)) AS branch_id,
                hex_to_int(leaf_hex) AS leaf_id,
                sha256(group_concat(metadata_hash, '')) AS leaf_hash,
                COUNT(*) AS book_count,
                MAX(last_modified) AS last_modified,
                '[' || group_concat(json_quote(uuid), ',') || ']' AS uuids_json
            FROM (
                SELECT
                    user_id,
                    library_id,
                    uuid,
                    lower(replace(uuid, '-', '')) AS uuid_norm,
                    substr(lower(replace(uuid, '-', '')), 1, 2) AS leaf_hex,
                    metadata_hash,
                    last_modified
                FROM seed
                ORDER BY user_id, library_id, leaf_hex, uuid_norm
            )
            GROUP BY user_id, library_id, leaf_hex
        SQL);

        $pdo->exec(<<<'SQL'
            CREATE VIEW tri_merkle_branches AS
            SELECT
                user_id,
                library_id,
                branch_id,
                sha256(group_concat(leaf_hash, '')) AS branch_hash,
                SUM(book_count) AS book_count,
                MAX(last_modified) AS last_modified
            FROM (
                SELECT
                    user_id,
                    library_id,
                    branch_id,
                    leaf_id,
                    leaf_hash,
                    book_count,
                    last_modified
                FROM tri_merkle_leaves
                ORDER BY user_id, library_id, branch_id, leaf_id
            )
            GROUP BY user_id, library_id, branch_id
        SQL);

        $pdo->exec(<<<'SQL'
            CREATE VIEW tri_merkle_root AS
            SELECT
                user_id,
                library_id,
                sha256(group_concat(branch_hash, '')) AS root_hash,
                SUM(book_count) AS total_books,
                MAX(last_modified) AS last_modified
            FROM (
                SELECT
                    user_id,
                    library_id,
                    branch_id,
                    branch_hash,
                    book_count,
                    last_modified
                FROM tri_merkle_branches
                ORDER BY user_id, library_id, branch_id
            )
            GROUP BY user_id, library_id
        SQL);

        $leaves = $pdo->query('
            SELECT branch_id, leaf_id, leaf_hash, book_count, uuids_json
            FROM tri_merkle_leaves
            WHERE user_id = 101 AND library_id = 201
            ORDER BY leaf_id
        ')->fetchAll(\PDO::FETCH_ASSOC);

        $branches = $pdo->query('
            SELECT branch_id, branch_hash, book_count
            FROM tri_merkle_branches
            WHERE user_id = 101 AND library_id = 201
            ORDER BY branch_id
        ')->fetchAll(\PDO::FETCH_ASSOC);

        $root = $pdo->query('
            SELECT root_hash, total_books
            FROM tri_merkle_root
            WHERE user_id = 101 AND library_id = 201
        ')->fetch(\PDO::FETCH_ASSOC);

        return [
            'leaves' => array_map(static function (array $row) {
                return [
                    'branch_id' => (int) $row['branch_id'],
                    'leaf_id' => (int) $row['leaf_id'],
                    'leaf_hash' => strtolower((string) $row['leaf_hash']),
                    'book_count' => (int) $row['book_count'],
                    'uuids' => json_decode((string) $row['uuids_json'], true, 512, JSON_THROW_ON_ERROR),
                ];
            }, $leaves),
            'branches' => array_map(static function (array $row) {
                return [
                    'branch_id' => (int) $row['branch_id'],
                    'branch_hash' => strtolower((string) $row['branch_hash']),
                    'book_count' => (int) $row['book_count'],
                ];
            }, $branches),
            'root_hash' => strtolower((string) $root['root_hash']),
            'total_books' => (int) $root['total_books'],
        ];
    }

    private function dropMerkleSeedObjects(): void
    {
        DB::statement('DROP VIEW IF EXISTS test_merkle_root');
        DB::statement('DROP VIEW IF EXISTS test_merkle_branches');
        DB::statement('DROP VIEW IF EXISTS test_merkle_leaves');
        DB::statement('DROP TABLE IF EXISTS test_merkle_seed');
    }
}
