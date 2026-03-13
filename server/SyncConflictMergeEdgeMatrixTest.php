<?php

namespace Tests\Server;

use App\Models\Author;
use App\Models\Library;
use App\Models\Publisher;
use App\Models\Series;
use App\Models\SyncConflict;
use App\Models\Tag;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\ConflictHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncConflictMergeEdgeMatrixTest extends TestCase
{
    use RefreshDatabase;

    public function test_merge_unions_tags_without_conflict(): void
    {
        [$user, $library, $book] = $this->makeBook();
        $this->attachTag($user, $library, $book, 101, 'Server Tag', 0);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'tags' => [
                ['name' => 'Server Tag'],
                ['name' => 'Client Tag'],
            ],
        ]);

        $this->assertTrue($merged['merged']);
        $this->assertSame([], $merged['conflicting_fields']);
        $this->assertContains('tags', $merged['merged_fields']);
        $tagNames = array_map(static fn ($tag) => $tag['name'] ?? null, $merged['item']['tags'] ?? []);
        $this->assertSame(['Server Tag', 'Client Tag'], $tagNames);
    }

    public function test_merge_unions_authors_without_conflict(): void
    {
        [$user, $library, $book] = $this->makeBook();
        $this->attachAuthor($user, $library, $book, 201, 'Server Author', 0);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'authors' => [
                ['name' => 'Server Author'],
                ['name' => 'Client Author'],
            ],
        ]);

        $this->assertTrue($merged['merged']);
        $this->assertSame([], $merged['conflicting_fields']);
        $this->assertContains('authors', $merged['merged_fields']);
        $authorNames = array_map(static fn ($author) => $author['name'] ?? null, $merged['item']['authors'] ?? []);
        $this->assertSame(['Server Author', 'Client Author'], $authorNames);
    }

    public function test_merge_deduplicates_tags_case_insensitively(): void
    {
        [$user, $library, $book] = $this->makeBook();
        $this->attachTag($user, $library, $book, 101, 'Fantasy', 0);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'tags' => [
                ['name' => 'fantasy'],
                ['name' => '  '],
                ['name' => 'Adventure'],
            ],
        ]);

        $this->assertTrue($merged['merged']);
        $tagNames = array_map(static fn ($tag) => $tag['name'] ?? null, $merged['item']['tags'] ?? []);
        $this->assertSame(['Fantasy', 'Adventure'], $tagNames);
    }

    public function test_merge_does_not_duplicate_existing_author(): void
    {
        [$user, $library, $book] = $this->makeBook();
        $this->attachAuthor($user, $library, $book, 201, 'Server Author', 0);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'authors' => [
                ['name' => 'Server Author'],
            ],
        ]);

        $this->assertTrue($merged['merged']);
        $this->assertSame([], $merged['merged_fields']);
        $authorNames = array_map(static fn ($author) => $author['name'] ?? null, $merged['item']['authors'] ?? []);
        $this->assertSame(['Server Author'], $authorNames);
    }

    public function test_merge_prefers_longer_client_description_without_conflict(): void
    {
        [$user, $library, $book] = $this->makeBook();

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'comments' => 'A much longer client description',
        ]);

        $this->assertTrue($merged['merged']);
        $this->assertContains('description', $merged['merged_fields']);
        $this->assertSame('A much longer client description', $merged['item']['comments'] ?? null);
    }

    public function test_merge_does_not_replace_server_description_with_shorter_client_text(): void
    {
        [$user, $library, $book] = $this->makeBook(['description' => 'Server description that is clearly longer']);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'comments' => 'short',
        ]);

        $this->assertTrue($merged['merged']);
        $this->assertSame([], $merged['merged_fields']);
        $this->assertSame('Server description that is clearly longer', $merged['item']['comments'] ?? null);
    }

    public function test_title_mismatch_is_reported_as_conflict(): void
    {
        [$user, $library, $book] = $this->makeBook(['title' => 'Server Title']);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'title' => 'Client Title',
        ]);

        $this->assertFalse($merged['merged']);
        $this->assertContains('title', $merged['conflicting_fields']);
    }

    public function test_cover_hash_mismatch_is_reported_as_conflict(): void
    {
        [$user, $library, $book] = $this->makeBook([
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'has_cover' => true,
            'cover_url' => 'https://cdn.example.test/covers/server.jpg',
        ]);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'cover' => [
                'has_cover' => true,
                'cover_hash' => 'sha256:' . str_repeat('b', 64),
            ],
        ]);

        $this->assertFalse($merged['merged']);
        $this->assertContains('cover', $merged['conflicting_fields']);
    }

    public function test_publisher_mismatch_is_reported_as_conflict(): void
    {
        [$user, $library, $book] = $this->makeBook();
        $this->attachPublisher($user, $library, $book, 301, 'Server Publisher');

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'publisher' => 'Client Publisher',
        ]);

        $this->assertFalse($merged['merged']);
        $this->assertContains('publisher', $merged['conflicting_fields']);
    }

    public function test_explicit_publisher_removal_is_reported_as_conflict_when_server_has_value(): void
    {
        [$user, $library, $book] = $this->makeBook();
        $this->attachPublisher($user, $library, $book, 301, 'Server Publisher');

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'publisher' => null,
        ]);

        $this->assertFalse($merged['merged']);
        $this->assertContains('publisher', $merged['conflicting_fields']);
    }

    public function test_tag_order_only_difference_does_not_duplicate_or_conflict(): void
    {
        [$user, $library, $book] = $this->makeBook();
        $this->attachTag($user, $library, $book, 101, 'Server Tag', 0);
        $this->attachTag($user, $library, $book, 102, 'Client Tag', 1);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'tags' => [
                ['name' => 'Client Tag'],
                ['name' => 'Server Tag'],
            ],
        ]);

        $this->assertTrue($merged['merged']);
        $this->assertSame([], $merged['merged_fields']);
        $this->assertSame([], $merged['conflicting_fields']);
        $tagNames = array_map(static fn ($tag) => $tag['name'] ?? null, $merged['item']['tags'] ?? []);
        $this->assertSame(['Server Tag', 'Client Tag'], $tagNames);
    }

    public function test_series_mismatch_is_reported_as_conflict(): void
    {
        [$user, $library, $book] = $this->makeBook();
        $this->attachSeries($user, $library, $book, 401, 'Server Series', 1.0);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'series' => [
                'name' => 'Client Series',
                'index' => 1.0,
            ],
        ]);

        $this->assertFalse($merged['merged']);
        $this->assertContains('series', $merged['conflicting_fields']);
    }

    public function test_explicit_series_removal_is_reported_as_conflict_when_server_has_value(): void
    {
        [$user, $library, $book] = $this->makeBook();
        $this->attachSeries($user, $library, $book, 401, 'Server Series', 1.0);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'series' => null,
        ]);

        $this->assertFalse($merged['merged']);
        $this->assertContains('series', $merged['conflicting_fields']);
    }

    public function test_pubdate_mismatch_is_reported_as_conflict(): void
    {
        [$user, $library, $book] = $this->makeBook(['pubdate' => now()->subDay()]);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'pubdate' => now()->timestamp,
        ]);

        $this->assertFalse($merged['merged']);
        $this->assertContains('pubdate', $merged['conflicting_fields']);
    }

    public function test_explicit_pubdate_removal_is_reported_as_conflict_when_server_has_value(): void
    {
        [$user, $library, $book] = $this->makeBook(['pubdate' => now()->subDay()]);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'pubdate' => null,
        ]);

        $this->assertFalse($merged['merged']);
        $this->assertContains('pubdate', $merged['conflicting_fields']);
    }

    public function test_explicit_title_removal_is_reported_as_conflict_when_server_has_value(): void
    {
        [$user, $library, $book] = $this->makeBook(['title' => 'Server Title']);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'title' => null,
        ]);

        $this->assertFalse($merged['merged']);
        $this->assertContains('title', $merged['conflicting_fields']);
    }

    public function test_merge_keeps_safe_field_union_even_when_critical_title_conflicts(): void
    {
        [$user, $library, $book] = $this->makeBook(['title' => 'Server Title']);
        $this->attachTag($user, $library, $book, 101, 'Server Tag', 0);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'title' => 'Client Title',
            'tags' => [
                ['name' => 'Server Tag'],
                ['name' => 'Client Tag'],
            ],
        ]);

        $this->assertFalse($merged['merged']);
        $this->assertContains('title', $merged['conflicting_fields']);
        $this->assertContains('tags', $merged['merged_fields']);
        $tagNames = array_map(static fn ($tag) => $tag['name'] ?? null, $merged['item']['tags'] ?? []);
        $this->assertSame(['Server Tag', 'Client Tag'], $tagNames);
    }

    public function test_cover_with_same_hash_and_different_url_is_not_a_conflict(): void
    {
        [$user, $library, $book] = $this->makeBook([
            'cover_original_hash' => 'sha256:' . str_repeat('a', 64),
            'has_cover' => true,
            'cover_url' => 'https://cdn.example.test/covers/server.jpg',
        ]);

        $merged = app(ConflictHandler::class)->mergeBookChanges($book->fresh(), [
            'uuid' => $book->uuid,
            'cover' => [
                'has_cover' => true,
                'cover_hash' => 'sha256:' . str_repeat('a', 64),
                'cover_url' => 'https://cdn.example.test/covers/client-copy.jpg',
            ],
        ]);

        $this->assertTrue($merged['merged']);
        $this->assertSame([], $merged['conflicting_fields']);
    }

    public function test_conflict_resolution_merge_overwrite_updates_book_payload(): void
    {
        if (!SyncConflict::isStorageAvailable()) {
            $this->markTestSkipped('SyncConflict storage not available in this environment.');
        }

        [$user, $library, $book] = $this->makeBook(['title' => 'Server Title']);
        $conflict = SyncConflict::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'user_book_id' => $book->id,
            'calibre_book_id' => $book->id,
            'uuid' => $book->uuid,
            'reason' => 'manual_test',
            'status' => 'open',
            'conflicting_fields' => ['title'],
            'client_item' => ['title' => 'Client Title'],
            'server_item' => ['title' => 'Server Title'],
        ]);

        Sanctum::actingAs($user);

        $response = $this->postJson('/api/sync/conflicts/' . $conflict->id . '/resolve', [
            'resolution' => 'overwrite',
            'item' => [
                'id' => $book->id,
                'uuid' => $book->uuid,
                'title' => 'Resolved Title',
                'last_modified' => now()->timestamp,
                'authors' => [],
                'tags' => [],
                'languages' => [],
                'identifiers' => [],
            ],
        ]);

        $response->assertStatus(200);
        $book->refresh();
        $this->assertSame('Resolved Title', $book->title);
    }

    public function test_conflict_resolution_keep_server_marks_resolved_without_changing_book(): void
    {
        if (!SyncConflict::isStorageAvailable()) {
            $this->markTestSkipped('SyncConflict storage not available in this environment.');
        }

        [$user, $library, $book] = $this->makeBook(['title' => 'Server Title']);
        $conflict = SyncConflict::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'user_book_id' => $book->id,
            'calibre_book_id' => $book->id,
            'uuid' => $book->uuid,
            'reason' => 'manual_test',
            'status' => 'open',
            'conflicting_fields' => ['title'],
            'client_item' => ['title' => 'Client Title'],
            'server_item' => ['title' => 'Server Title'],
        ]);

        Sanctum::actingAs($user);

        $response = $this->postJson('/api/sync/conflicts/' . $conflict->id . '/resolve', [
            'resolution' => 'keep_server',
        ]);

        $response->assertStatus(200);
        $book->refresh();
        $conflict->refresh();
        $this->assertSame('Server Title', $book->title);
        $this->assertSame('resolved', $conflict->status);
        $this->assertSame('keep_server', $conflict->resolution_payload['resolution'] ?? null);
    }

    public function test_conflict_resolution_keep_server_ignores_spurious_item_payload(): void
    {
        if (!SyncConflict::isStorageAvailable()) {
            $this->markTestSkipped('SyncConflict storage not available in this environment.');
        }

        [$user, $library, $book] = $this->makeBook(['title' => 'Server Title']);
        $conflict = SyncConflict::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'user_book_id' => $book->id,
            'calibre_book_id' => $book->id,
            'uuid' => $book->uuid,
            'reason' => 'manual_test',
            'status' => 'open',
            'conflicting_fields' => ['title'],
            'client_item' => ['title' => 'Client Title'],
            'server_item' => ['title' => 'Server Title'],
        ]);

        Sanctum::actingAs($user);

        $response = $this->postJson('/api/sync/conflicts/' . $conflict->id . '/resolve', [
            'resolution' => 'keep_server',
            'item' => [
                'id' => $book->id,
                'uuid' => $book->uuid,
                'title' => 'Should Be Ignored',
                'last_modified' => now()->timestamp,
            ],
        ]);

        $response->assertStatus(200);
        $book->refresh();
        $this->assertSame('Server Title', $book->title);
    }

    private function makeBook(array $overrides = []): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::create(array_merge([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
            'id' => 200,
            'title' => 'Original Title',
            'path' => 'original-title',
            'last_modified' => now(),
        ], $overrides));

        return [$user, $library, $book];
    }

    private function attachTag(User $user, Library $library, UserBook $book, int $id, string $name, int $position): void
    {
        $tag = Tag::create([
            'id' => $id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => $name,
            'uuid' => (string) Str::uuid(),
        ]);

        DB::table('books_tags_link')->insert([
            'uuid' => (string) Str::uuid(),
            'book' => $book->uuid,
            'tag' => $tag->id,
            'position' => $position,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => now(),
            'updated_at' => now(),
        ]);
    }

    private function attachAuthor(User $user, Library $library, UserBook $book, int $id, string $name, int $position): void
    {
        $author = Author::create([
            'id' => $id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => $name,
            'uuid' => (string) Str::uuid(),
        ]);

        DB::table('books_authors_link')->insert([
            'uuid' => (string) Str::uuid(),
            'book' => $book->uuid,
            'author' => $author->id,
            'position' => $position,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => now(),
            'updated_at' => now(),
        ]);
    }

    private function attachPublisher(User $user, Library $library, UserBook $book, int $id, string $name): void
    {
        $publisher = Publisher::create([
            'id' => $id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => $name,
            'sort' => $name,
            'uuid' => (string) Str::uuid(),
        ]);

        DB::table('books_publishers_link')->insert([
            'uuid' => (string) Str::uuid(),
            'book' => $book->uuid,
            'publisher' => $publisher->id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => now(),
            'updated_at' => now(),
        ]);
    }

    private function attachSeries(User $user, Library $library, UserBook $book, int $id, string $name, float $seriesIndex): void
    {
        $series = Series::create([
            'id' => $id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'name' => $name,
            'sort' => $name,
            'uuid' => (string) Str::uuid(),
        ]);

        DB::table('books_series_link')->insert([
            'uuid' => (string) Str::uuid(),
            'book' => $book->uuid,
            'series' => $series->id,
            'series_index' => $seriesIndex,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => now(),
            'updated_at' => now(),
        ]);
    }
}
