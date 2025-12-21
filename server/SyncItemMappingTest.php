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
        ]);

        $author = Author::create([
            'id' => 101,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => 'Author A',
        ]);
        DB::table('books_authors_link')->insert([
            'book' => $book->getAttribute('id'),
            'author' => $author->getAttribute('id'),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $tag = Tag::create([
            'id' => 201,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => 'Tag A',
        ]);
        DB::table('books_tags_link')->insert([
            'book' => $book->getAttribute('id'),
            'tag' => $tag->getAttribute('id'),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $series = Series::create([
            'id' => 301,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => 'Series A',
        ]);
        DB::table('books_series_link')->insert([
            'book' => $book->getAttribute('id'),
            'series' => $series->getAttribute('id'),
            'user_id' => $user->id,
            'library_id' => $library->id,
            'item_order' => 1,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $service = app(SyncService::class);
        $item = $service->buildItemFromUserBook($book->fresh());

        $this->assertSame(101, $item['authors'][0]['id']);
        $this->assertSame(201, $item['tags'][0]['id']);
        $this->assertSame(301, $item['series']['id']);
    }
}
