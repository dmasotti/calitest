<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Schema;
use Tests\TestCase;

/**
 * RED tests: pubdate pre-1970 must work on MySQL after TIMESTAMP → DATETIME migration.
 *
 * Production issue: MySQL TIMESTAMP rejects dates before 1970-01-01.
 * Books like "Lord of the Rings" (1954) get pubdate=NULL silently.
 * 1462 books in production have NULL pubdate — some may be pre-1970 losses.
 *
 * After fix: books.pubdate is DATETIME, accepts any date 1000-01-01 → 9999-12-31.
 */
class PubdatePre1970MysqlTest extends TestCase
{
    use RefreshDatabase;

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::create([
            'user_id' => $user->id,
            'name' => 'Test Library',
            'uuid' => 'test-lib-pubdate-uuid',
        ]);
        return [$user, $library];
    }

    // ─────────────────────────────────────────────────────────────────
    // 1. Column type: pubdate must be DATETIME, not TIMESTAMP
    // ─────────────────────────────────────────────────────────────────

    public function test_pubdate_column_is_datetime_not_timestamp(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('SQLite has no column type distinction');
        }

        $col = DB::selectOne(
            "SELECT DATA_TYPE FROM information_schema.columns
             WHERE table_schema = DATABASE()
               AND table_name = 'books'
               AND column_name = 'pubdate'"
        );

        $this->assertNotNull($col, 'pubdate column not found');
        $this->assertSame(
            'datetime',
            strtolower($col->DATA_TYPE),
            "books.pubdate must be DATETIME (not TIMESTAMP) to support pre-1970 dates"
        );
    }

    // ─────────────────────────────────────────────────────────────────
    // 2. INSERT pre-1970 date: must not error
    // ─────────────────────────────────────────────────────────────────

    public function test_insert_pre_1970_pubdate_does_not_error(): void
    {
        [$user, $library] = $this->makeContext();

        $book = UserBook::create([
            'uuid' => 'pre1970-test-uuid-001',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'The Lord of the Rings',
            'path' => 'tolkien/lotr',
            'author_sort' => 'Tolkien, J.R.R.',
            'pubdate' => Carbon::create(1954, 7, 29, 0, 0, 0, 'UTC'),
            'last_modified' => now(),
        ]);

        $this->assertNotNull($book->id);

        // Read back and verify
        $saved = UserBook::find($book->id);
        $this->assertNotNull($saved->pubdate, 'pubdate must not be NULL after save');
        $this->assertSame(1954, $saved->pubdate->year, 'pubdate year must be 1954');
    }

    // ─────────────────────────────────────────────────────────────────
    // 3. Hash view: pre-1970 pubdate → negative epoch in hash payload
    // ─────────────────────────────────────────────────────────────────

    public function test_hash_view_shows_negative_epoch_for_pre_1970(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('SQLite books_hash_v2 uses different SQL');
        }

        [$user, $library] = $this->makeContext();

        UserBook::create([
            'uuid' => 'pre1970-hash-test-uuid',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Nineteen Eighty-Four',
            'path' => 'orwell/1984',
            'author_sort' => 'Orwell, George',
            'pubdate' => Carbon::create(1949, 6, 8, 0, 0, 0, 'UTC'),
            'last_modified' => now(),
        ]);

        $row = DB::table('books_hash_v2')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('uuid', 'pre1970-hash-test-uuid')
            ->first(['hash_payload', 'pubdate']);

        $this->assertNotNull($row, 'Book not found in books_hash_v2');
        $this->assertNotNull($row->pubdate, 'pubdate in view must not be NULL');

        // hash_payload must contain a negative epoch for pubdate
        $this->assertStringContainsString(
            '"pubdate":-',
            $row->hash_payload,
            'hash_payload must contain negative pubdate epoch for pre-1970 date'
        );
    }

    // ─────────────────────────────────────────────────────────────────
    // 4. NULL pubdate preserved: books without pubdate stay NULL
    // ─────────────────────────────────────────────────────────────────

    public function test_null_pubdate_preserved(): void
    {
        [$user, $library] = $this->makeContext();

        $book = UserBook::create([
            'uuid' => 'null-pubdate-test-uuid',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'No Pubdate Book',
            'path' => 'unknown/nopub',
            'author_sort' => 'Unknown',
            'pubdate' => null,
            'last_modified' => now(),
        ]);

        $saved = UserBook::find($book->id);
        $this->assertNull($saved->pubdate, 'NULL pubdate must stay NULL');
    }

    // ─────────────────────────────────────────────────────────────────
    // 5. Post-1970 pubdate: still works normally
    // ─────────────────────────────────────────────────────────────────

    public function test_post_1970_pubdate_still_works(): void
    {
        [$user, $library] = $this->makeContext();

        $book = UserBook::create([
            'uuid' => 'post1970-test-uuid',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Modern Book',
            'path' => 'modern/book',
            'author_sort' => 'Author, Modern',
            'pubdate' => Carbon::create(2024, 1, 15, 0, 0, 0, 'UTC'),
            'last_modified' => now(),
        ]);

        $saved = UserBook::find($book->id);
        $this->assertNotNull($saved->pubdate);
        $this->assertSame(2024, $saved->pubdate->year);
    }

    // ─────────────────────────────────────────────────────────────────
    // 6. 2038 boundary: DATETIME handles post-2038 (TIMESTAMP wouldn't)
    // ─────────────────────────────────────────────────────────────────

    public function test_post_2038_pubdate_works_with_datetime(): void
    {
        [$user, $library] = $this->makeContext();

        $book = UserBook::create([
            'uuid' => 'post2038-test-uuid',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Future Book',
            'path' => 'future/book',
            'author_sort' => 'Author, Future',
            'pubdate' => Carbon::create(2040, 6, 15, 0, 0, 0, 'UTC'),
            'last_modified' => now(),
        ]);

        $saved = UserBook::find($book->id);
        $this->assertNotNull($saved->pubdate);
        $this->assertSame(2040, $saved->pubdate->year);
    }

    // ─────────────────────────────────────────────────────────────────
    // 7. Guard removed: normalizePubdateForSync returns Carbon for pre-1970
    // ─────────────────────────────────────────────────────────────────

    public function test_normalize_pubdate_does_not_drop_pre_1970(): void
    {
        $handlerPath = app_path('Services/Sync/BookMetadataHandler.php');
        if (!file_exists($handlerPath)) {
            $this->markTestSkipped('BookMetadataHandler not found');
        }

        $source = file_get_contents($handlerPath);

        // Find normalizePubdateForSync method
        $methodStart = strpos($source, 'function normalizePubdateForSync');
        if ($methodStart === false) {
            // Method might be named differently
            $this->markTestSkipped('normalizePubdateForSync method not found');
        }

        $methodBody = substr($source, $methodStart, 500);

        // The guard that drops pre-1970 should be removed
        $hasTimestampGuard = str_contains($methodBody, '$ts < 0');

        $this->assertFalse(
            $hasTimestampGuard,
            'normalizePubdateForSync must NOT drop pre-1970 dates ($ts < 0 guard should be removed). '
            . 'With DATETIME column, pre-1970 dates are valid.'
        );
    }

    // ─────────────────────────────────────────────────────────────────
    // 8. Hash parity: pre-1970 pubdate hash identical across engines
    // ─────────────────────────────────────────────────────────────────

    public function test_pre_1970_hash_payload_contains_signed_epoch(): void
    {
        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('SQLite hash view uses different SQL');
        }

        [$user, $library] = $this->makeContext();

        UserBook::create([
            'uuid' => 'parity-pre1970-uuid',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Old Book',
            'path' => 'old/book',
            'author_sort' => 'Author, Old',
            'pubdate' => Carbon::create(1900, 1, 1, 0, 0, 0, 'UTC'),
            'last_modified' => now(),
        ]);

        $row = DB::table('books_hash_v2')
            ->where('uuid', 'parity-pre1970-uuid')
            ->first(['hash_payload']);

        $this->assertNotNull($row);

        // Parse the pubdate from hash_payload
        if (preg_match('/"pubdate":(-?\d+)/', $row->hash_payload, $matches)) {
            $epoch = (int) $matches[1];
            $this->assertLessThan(0, $epoch, 'Pre-1970 pubdate must have negative epoch in hash');
        } else {
            $this->fail('pubdate not found in hash_payload or is null');
        }
    }

    // ─────────────────────────────────────────────────────────────────
    // 9. Benchmark: allow_pre_1970 works on MySQL
    // ─────────────────────────────────────────────────────────────────

    public function test_benchmark_seeder_pre_1970_works_on_mysql(): void
    {
        if (!in_array(DB::getDriverName(), ['mysql', 'mariadb'], true)) {
            $this->markTestSkipped('MySQL-only test');
        }

        [$user, $library] = $this->makeContext();

        // Simulate what the benchmark seeder does with pre-1970 pubdate
        $pre1970Epoch = -410247000; // ~1956-12-31
        $pubdate = Carbon::createFromTimestamp($pre1970Epoch, 'UTC');

        // This INSERT should NOT throw on MySQL after DATETIME migration
        $book = UserBook::create([
            'uuid' => 'bench-pre1970-uuid',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Benchmark Pre-1970',
            'path' => 'bench/pre1970',
            'author_sort' => 'Bench, Author',
            'pubdate' => $pubdate,
            'last_modified' => now(),
        ]);

        $saved = UserBook::find($book->id);
        $this->assertNotNull($saved->pubdate);
        $this->assertSame(1956, $saved->pubdate->year);
    }
}
