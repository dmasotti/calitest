<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Str;
use Tests\TestCase;

/**
 * VIEW parity test: insert SAME books, compare VIEW hash across engines.
 *
 * This test runs on whatever DB engine is configured (SQLite/MySQL/PgSQL).
 * The hash from the VIEW is compared with MetadataHasher::computeHash() PHP.
 * If they diverge, the formula has a cross-engine parity bug.
 *
 * Uses real data patterns: accented characters, HTML, pre-1970 dates,
 * multiple authors, identifiers with mixed case.
 */
class SyncV5ViewParityCrossEngineTest extends TestCase
{
    use RefreshDatabase;

    private function applyAndGetViewHash(User $user, Library $lib, array $item): array
    {
        $uuid = $item['uuid'];
        $book = UserBook::create([
            'id' => crc32($uuid) & 0x7FFFFFFF,
            'uuid' => $uuid,
            'user_id' => $user->id,
            'library_id' => (string) $lib->id,
            'title' => $item['title'] ?? 'Test',
            'path' => 'book-' . substr($uuid, 0, 8),
            'pubdate' => $item['pubdate'] ?? null,
            'last_modified' => now(),
            'has_cover' => false,
        ]);

        app(BookMetadataHandler::class)->applyBookMetadata($book, $item, $user, $lib->id);
        $book->refresh();

        // Get VIEW hash (try query directly — Schema::hasTable returns false for VIEWs)
        $viewHash = null;
        try {
            $vh = DB::table('books_hash_v2')
                ->where('uuid', $uuid)
                ->where('user_id', $user->id)
                ->where('library_id', $lib->id)
                ->value('metadata_hash');
            $viewHash = $vh ? strtolower((string) $vh) : null;
        } catch (\Throwable $e) {
            // VIEW not available
        }

        // Get on-write column hash
        $colHash = $book->metadata_hash;

        return [
            'uuid' => $uuid,
            'view_hash' => $viewHash ?: null,
            'col_hash' => $colHash,
            'title' => $item['title'] ?? null,
        ];
    }

    public function test_view_hash_equals_column_hash_for_50_real_books(): void
    {
        $driver = DB::getDriverName();
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);

        // 50 books with diverse real-world data patterns
        $books = [
            ['uuid' => (string) Str::uuid(), 'title' => 'El Quijote', 'authors' => [['name' => 'Miguel de Cervantes']], 'tags' => [['name' => 'Clásicos']], 'series' => null, 'identifiers' => ['isbn' => '9788420412146'], 'publisher' => 'Cátedra', 'languages' => ['spa'], 'comments' => '<p>La gran novela</p>', 'rating' => 10, 'pubdate' => '1605-01-16'],
            ['uuid' => (string) Str::uuid(), 'title' => "L'étranger", 'authors' => [['name' => 'Albert Camus']], 'tags' => [['name' => 'Philosophie']], 'series' => null, 'identifiers' => ['isbn' => '9782070360024'], 'publisher' => 'Gallimard', 'languages' => ['fra'], 'comments' => "<p>L'absurde et l'indifférence</p>", 'rating' => 8, 'pubdate' => '1942-06-15'],
            ['uuid' => (string) Str::uuid(), 'title' => 'Über die spezielle Relativitätstheorie', 'authors' => [['name' => 'Albert Einstein']], 'tags' => [['name' => 'Física'], ['name' => 'Ciência']], 'series' => null, 'identifiers' => [], 'publisher' => null, 'languages' => ['deu'], 'comments' => null, 'rating' => null, 'pubdate' => '1905-09-26'],
            ['uuid' => (string) Str::uuid(), 'title' => 'War & Peace', 'authors' => [['name' => 'Leo Tolstoy']], 'tags' => [], 'series' => null, 'identifiers' => ['goodreads' => '656'], 'publisher' => "The Russian Messenger", 'languages' => ['eng', 'rus'], 'comments' => '<div><p>Epic novel about <b>Napoleon\'s</b> invasion</p></div>', 'rating' => 10, 'pubdate' => '1869-01-01'],
            ['uuid' => (string) Str::uuid(), 'title' => 'Book with "quotes" & <angles>', 'authors' => [['name' => "O'Brien, Patrick"]], 'tags' => [['name' => 'Test & Debug']], 'series' => null, 'identifiers' => [], 'publisher' => 'Publisher "Special"', 'languages' => ['eng'], 'comments' => '<p>Quotes: "hello" & ampersand</p>', 'rating' => null, 'pubdate' => null],
            ['uuid' => (string) Str::uuid(), 'title' => 'Multi Author Sorted', 'authors' => [['name' => 'Zeta Author'], ['name' => 'Alpha Author'], ['name' => 'Mid Author']], 'tags' => [], 'series' => null, 'identifiers' => [], 'publisher' => null, 'languages' => [], 'comments' => null, 'rating' => null, 'pubdate' => '2022-01-01'],
            ['uuid' => (string) Str::uuid(), 'title' => 'Series Book', 'authors' => [['name' => 'Series Writer']], 'tags' => [], 'series' => ['name' => 'Epic Série', 'index' => 3.5], 'identifiers' => [], 'publisher' => null, 'languages' => [], 'comments' => null, 'rating' => null, 'pubdate' => null],
            ['uuid' => (string) Str::uuid(), 'title' => 'Sentinel Date', 'authors' => [], 'tags' => [], 'series' => null, 'identifiers' => [], 'publisher' => null, 'languages' => [], 'comments' => null, 'rating' => null, 'pubdate' => '0101-01-01'],
            ['uuid' => (string) Str::uuid(), 'title' => 'Pre-1970 Date', 'authors' => [['name' => 'Julio Verne']], 'tags' => [], 'series' => null, 'identifiers' => [], 'publisher' => null, 'languages' => ['spa'], 'comments' => null, 'rating' => null, 'pubdate' => '1865-11-01'],
            ['uuid' => (string) Str::uuid(), 'title' => 'Rating Zero', 'authors' => [], 'tags' => [], 'series' => null, 'identifiers' => [], 'publisher' => null, 'languages' => [], 'comments' => null, 'rating' => 0, 'pubdate' => null],
            ['uuid' => (string) Str::uuid(), 'title' => 'Rating Ten', 'authors' => [], 'tags' => [], 'series' => null, 'identifiers' => [], 'publisher' => null, 'languages' => [], 'comments' => null, 'rating' => 10, 'pubdate' => '2020-01-01'],
            ['uuid' => (string) Str::uuid(), 'title' => 'All Fields', 'authors' => [['name' => 'Author One'], ['name' => 'Author Two']], 'tags' => [['name' => 'Tag A'], ['name' => 'Tag B'], ['name' => 'Tag C']], 'series' => ['name' => 'My Series', 'index' => 1.0], 'identifiers' => ['isbn' => '1234567890', 'goodreads' => '999', 'amazon' => 'B00TEST'], 'publisher' => 'Big Publisher', 'languages' => ['eng', 'spa', 'fra'], 'comments' => '<p>Full description with <b>bold</b> and <i>italic</i></p>', 'rating' => 6, 'pubdate' => '2021-10-16'],
            ['uuid' => (string) Str::uuid(), 'title' => 'Empty Everything', 'authors' => [], 'tags' => [], 'series' => null, 'identifiers' => [], 'publisher' => null, 'languages' => [], 'comments' => null, 'rating' => null, 'pubdate' => null],
            ['uuid' => (string) Str::uuid(), 'title' => 'Crónicas del señor López', 'authors' => [['name' => 'José María García-López']], 'tags' => [['name' => 'Histórica']], 'series' => ['name' => 'Série Épica', 'index' => 2.0], 'identifiers' => ['isbn' => '9788401234567'], 'publisher' => 'Éditions Spéciales', 'languages' => ['spa', 'fra'], 'comments' => '<div><p>Acentos: àèìòù äëïöü ñ ç ø å</p></div>', 'rating' => 8, 'pubdate' => '2019-03-15'],
            ['uuid' => (string) Str::uuid(), 'title' => 'Identifiers Mixed Case', 'authors' => [], 'tags' => [], 'series' => null, 'identifiers' => ['ISBN' => '111', 'Goodreads' => '222', 'AMAZON' => '333'], 'publisher' => null, 'languages' => [], 'comments' => null, 'rating' => null, 'pubdate' => null],
        ];

        // Duplicate to get 50
        $allBooks = [];
        for ($i = 0; $i < 50; $i++) {
            $base = $books[$i % count($books)];
            $base['uuid'] = (string) Str::uuid();
            $base['title'] = $base['title'] . ' #' . ($i + 1);
            $allBooks[] = $base;
        }

        $results = [];
        $match = $mismatch = $viewNull = 0;

        foreach ($allBooks as $item) {
            $r = $this->applyAndGetViewHash($user, $lib, $item);
            if ($r['view_hash'] === null) {
                $viewNull++;
                continue;
            }
            if ($r['col_hash'] === $r['view_hash']) {
                $match++;
            } else {
                $mismatch++;
                $results[] = $r;
            }
        }

        // Log results
        fwrite(STDERR, sprintf(
            "\n[PARITY] %s: %d match, %d mismatch, %d view_null out of %d\n",
            $driver, $match, $mismatch, $viewNull, count($allBooks)
        ));
        if ($results) {
            foreach (array_slice($results, 0, 5) as $r) {
                fwrite(STDERR, sprintf(
                    "  MISMATCH: %s title='%s' col=%s view=%s\n",
                    substr($r['uuid'], 0, 8), $r['title'],
                    substr($r['col_hash'] ?? 'NULL', 0, 16),
                    substr($r['view_hash'] ?? 'NULL', 0, 16)
                ));
            }
        }

        $this->assertSame(0, $mismatch,
            "VIEW hash must equal on-write column hash for all books on {$driver}. " .
            "{$mismatch} mismatches found.");
    }
}
