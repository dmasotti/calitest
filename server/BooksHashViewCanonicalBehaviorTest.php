<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Services\Sync\MetadataHasherV2;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Tests\TestCase;

class BooksHashViewCanonicalBehaviorTest extends TestCase
{
    use RefreshDatabase;

    public function test_books_hash_v2_normalizes_epoch_pubdate_and_uses_rating_link(): void
    {
        if (DB::getDriverName() !== 'mysql') {
            $this->markTestSkipped('Behavior check requires MySQL books_hash_v2 view semantics');
        }

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $now = now();
        $uuid = (string) Str::uuid();

        DB::table('books')->insert([
            'id' => 9101,
            'uuid' => $uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Canonical Book',
            'author_sort' => 'Doe, John',
            'series_index' => null,
            'pubdate' => '1634414400',
            'rating' => 5,
            'path' => 'canonical-book',
            'flags' => 1,
            'has_cover' => 0,
            'last_modified' => $now,
            'created_at' => $now,
            'updated_at' => $now,
        ]);

        DB::table('books_ratings')->insert([
            'id' => 9201,
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'rating' => 2,
            'created_at' => $now,
            'updated_at' => $now,
        ]);

        DB::table('books_ratings_links')->insert([
            'id' => 9301,
            'uuid' => (string) Str::uuid(),
            'book' => $uuid,
            'rating' => 9201,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => $now,
            'updated_at' => $now,
        ]);

        $row = DB::table('books_hash_v2')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('uuid', $uuid)
            ->selectRaw('hash_payload, SHA2(hash_payload, 256) as metadata_hash')
            ->first();

        $this->assertNotNull($row, 'books_hash_v2 row not found');

        $expectedHash = MetadataHasherV2::computeHash([
            'uuid' => $uuid,
            'title' => 'Canonical Book',
            'author_sort' => 'Doe, John',
            'series' => null,
            'series_index' => null,
            'tags' => [],
            'identifiers' => [],
            'languages' => [],
            'pubdate' => '2021-10-16 20:00:00+00:00',
            'rating' => 2,
        ]);

        $this->assertSame($expectedHash, strtolower((string) $row->metadata_hash));
    }

    public function test_books_hash_v2_maps_null_pubdate_and_scales_rating_to_calibre_value(): void
    {
        if (DB::getDriverName() !== 'mysql') {
            $this->markTestSkipped('Behavior check requires MySQL books_hash_v2 view semantics');
        }

        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $now = now();
        $uuid = (string) Str::uuid();

        DB::table('books')->insert([
            'id' => 9102,
            'uuid' => $uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Null Pubdate Book',
            'author_sort' => 'Roe, Jane',
            'series_index' => null,
            'pubdate' => null,
            'rating' => 1,
            'path' => 'null-pubdate-book',
            'flags' => 1,
            'has_cover' => 0,
            'last_modified' => $now,
            'created_at' => $now,
            'updated_at' => $now,
        ]);

        DB::table('books_ratings')->insert([
            'id' => 9202,
            'uuid' => (string) Str::uuid(),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'rating' => 1,
            'created_at' => $now,
            'updated_at' => $now,
        ]);

        DB::table('books_ratings_links')->insert([
            'id' => 9302,
            'uuid' => (string) Str::uuid(),
            'book' => $uuid,
            'rating' => 9202,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => $now,
            'updated_at' => $now,
        ]);

        $row = DB::table('books_hash_v2')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->where('uuid', $uuid)
            ->selectRaw('hash_payload, SHA2(hash_payload, 256) as metadata_hash')
            ->first();

        $this->assertNotNull($row, 'books_hash_v2 row not found');
        $this->assertStringContainsString(
            '|0101-01-01 00:00:00+00:00|2|',
            (string) $row->hash_payload,
            'hash_payload must use calibre sentinel pubdate and scaled rating'
        );

        $expectedHash = MetadataHasherV2::computeHash([
            'uuid' => $uuid,
            'title' => 'Null Pubdate Book',
            'author_sort' => 'Roe, Jane',
            'series' => null,
            'series_index' => null,
            'tags' => [],
            'identifiers' => [],
            'languages' => [],
            'pubdate' => '0101-01-01 00:00:00+00:00',
            'rating' => 2,
        ]);

        $this->assertSame($expectedHash, strtolower((string) $row->metadata_hash));
    }
}
