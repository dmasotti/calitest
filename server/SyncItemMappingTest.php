<?php

namespace Tests\Server;

use App\Models\Author;
use App\Models\Library;
use App\Models\Series;
use App\Models\Tag;
use App\Models\User;
use App\Models\UserBook;
use App\Services\SyncService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Tests\TestCase;

class SyncItemMappingTest extends TestCase
{
    use RefreshDatabase;

    public function test_build_item_includes_author_tag_series_ids(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);

        $book = UserBook::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'id' => 10,
            'title' => 'Mapping Book',
            'last_modified' => now(),
            'uuid' => Str::uuid()->toString(),
        ]);

        $author = Author::create([
            'id' => 101,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => 'Author A',
            'uuid' => Str::uuid()->toString(),
        ]);
        DB::table('books_authors_link')->insert([
            'book' => $book->getAttribute('uuid'),
            'author' => $author->getAttribute('id'),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => now(),
            'updated_at' => now(),
            'uuid' => Str::uuid()->toString(),
        ]);

        $tag = Tag::create([
            'id' => 201,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => 'Tag A',
            'uuid' => Str::uuid()->toString(),
        ]);
        DB::table('books_tags_link')->insert([
            'book' => $book->getAttribute('uuid'),
            'tag' => $tag->getAttribute('id'),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => now(),
            'updated_at' => now(),
            'uuid' => Str::uuid()->toString(),
        ]);

        $series = Series::create([
            'id' => 301,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => 'Series A',
            'uuid' => Str::uuid()->toString(),
        ]);
        DB::table('books_series_link')->insert([
            'book' => $book->getAttribute('uuid'),
            'series' => $series->getAttribute('id'),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'series_index' => 1,
            'created_at' => now(),
            'updated_at' => now(),
            'uuid' => Str::uuid()->toString(),
        ]);

        $service = app(SyncService::class);
        $item = $service->buildItemFromUserBook($book->fresh());

        $this->assertSame(101, $item['authors'][0]['id']);
        $this->assertSame(201, $item['tags'][0]['id']);
        $this->assertSame(301, $item['series']['id']);
    }
}
