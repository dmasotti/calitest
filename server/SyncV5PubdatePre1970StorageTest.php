<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Tests\TestCase;

/**
 * Test that pre-1970 pubdates are stored correctly (not converted to NULL).
 */
class SyncV5PubdatePre1970StorageTest extends TestCase
{
    use RefreshDatabase;

    private function applyAndRefresh(UserBook $book, array $item, User $user, int $libraryId): UserBook
    {
        app(BookMetadataHandler::class)->applyBookMetadata($book, $item, $user, $libraryId);
        $book->refresh();
        return $book;
    }

    public function test_pre_1970_pubdate_string_stored_not_null(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::create([
            'id' => 70001, 'uuid' => (string) Str::uuid(),
            'user_id' => $user->id, 'library_id' => (string) $lib->id,
            'title' => 'Pre 1970', 'path' => 'pre1970', 'last_modified' => now(),
        ]);

        $this->applyAndRefresh($book, [
            'uuid' => $book->uuid, 'title' => 'Pre 1970',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null,
            'pubdate' => '1966-12-31 23:00:00',
        ], $user, $lib->id);

        $this->assertNotNull($book->pubdate, 'Pre-1970 pubdate must not be nullified');
        $this->assertStringContains('1966', (string) $book->pubdate);
    }

    public function test_pre_1970_pubdate_epoch_stored_not_null(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::create([
            'id' => 70002, 'uuid' => (string) Str::uuid(),
            'user_id' => $user->id, 'library_id' => (string) $lib->id,
            'title' => 'Pre 1970 Epoch', 'path' => 'pre1970e', 'last_modified' => now(),
        ]);

        $this->applyAndRefresh($book, [
            'uuid' => $book->uuid, 'title' => 'Pre 1970 Epoch',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null,
            'pubdate' => -94698000,  // 1966-12-31 23:00:00 UTC
        ], $user, $lib->id);

        $this->assertNotNull($book->pubdate, 'Pre-1970 epoch pubdate must not be nullified');
    }

    public function test_sentinel_0101_pubdate_stored_as_null(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::create([
            'id' => 70003, 'uuid' => (string) Str::uuid(),
            'user_id' => $user->id, 'library_id' => (string) $lib->id,
            'title' => 'Sentinel', 'path' => 'sentinel', 'last_modified' => now(),
        ]);

        $this->applyAndRefresh($book, [
            'uuid' => $book->uuid, 'title' => 'Sentinel',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null,
            'pubdate' => '0101-01-01 00:00:00',
        ], $user, $lib->id);

        $this->assertNull($book->pubdate, 'Sentinel 0101-01-01 must be stored as NULL');
    }

    public function test_normal_pubdate_stored_correctly(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::create([
            'id' => 70004, 'uuid' => (string) Str::uuid(),
            'user_id' => $user->id, 'library_id' => (string) $lib->id,
            'title' => 'Normal', 'path' => 'normal', 'last_modified' => now(),
        ]);

        $this->applyAndRefresh($book, [
            'uuid' => $book->uuid, 'title' => 'Normal',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null,
            'pubdate' => '2021-10-16 20:00:00',
        ], $user, $lib->id);

        $this->assertNotNull($book->pubdate);
        $this->assertStringContains('2021', (string) $book->pubdate);
    }

    public function test_null_pubdate_stays_null(): void
    {
        $user = User::factory()->create();
        $lib = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::create([
            'id' => 70005, 'uuid' => (string) Str::uuid(),
            'user_id' => $user->id, 'library_id' => (string) $lib->id,
            'title' => 'No Date', 'path' => 'nodate', 'last_modified' => now(),
        ]);

        $this->applyAndRefresh($book, [
            'uuid' => $book->uuid, 'title' => 'No Date',
            'authors' => [], 'tags' => [], 'series' => null,
            'identifiers' => [], 'publisher' => null, 'languages' => [],
            'comments' => null, 'rating' => null,
            'pubdate' => null,
        ], $user, $lib->id);

        $this->assertNull($book->pubdate);
    }

    private function assertStringContains(string $needle, string $haystack): void
    {
        $this->assertTrue(
            str_contains($haystack, $needle),
            "Expected '{$haystack}' to contain '{$needle}'"
        );
    }
}
