<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class BookMetadataHandlerRatingEdgeMatrixTest extends TestCase
{
    use RefreshDatabase;

    public function test_rating_noop_update_does_not_delete_existing_link(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $this->createRating($user, $library, 8);
        DB::table('books_ratings_links')->insert([
            'id' => -9801,
            'idx' => 9801,
            'uuid' => 'rating-pivot-1',
            'book' => $book->uuid,
            'rating' => 8,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'rating' => 8,
        ], $user, $library->id);

        $deleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete') && str_contains($sql, 'books_ratings_links');
        }));

        $this->assertSame([], $deleteQueries, 'No-op rating update must not delete and recreate pivot rows');
        $this->assertSame(8, $this->ratingForBook($book, $user, $library));
    }

    public function test_rating_edge_matrix_preserves_native_calibre_scale_zero_to_ten(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'rating' => 10,
        ], $user, $library->id);

        $this->assertSame(10, $this->ratingForBook($book, $user, $library));
    }

    public function test_rating_resolution_reuses_handler_cache_across_books(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $otherBook = UserBook::create([
            'id' => 9502,
            'uuid' => 'dd000000-0000-4000-8000-000000009502',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Rating Test Book 2',
            'path' => 'rating-test-book-2',
            'author_sort' => 'Tester, Rating',
            'last_modified' => now(),
        ]);
        $handler = app(BookMetadataHandler::class);

        $this->createRating($user, $library, 6);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $payload = ['rating' => 6];
        $handler->applyBookMetadata($book, $payload, $user, $library->id);
        $handler->applyBookMetadata($otherBook, $payload, $user, $library->id);

        $ratingSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'from `books_ratings`') && str_contains($sql, 'select');
        }));

        $this->assertLessThanOrEqual(
            2,
            count($ratingSelects),
            'Rating resolution should be cached across multiple books in the same handler lifecycle'
        );
    }

    public function test_rating_edge_matrix_explicit_null_clears_link(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'rating' => 6,
        ], $user, $library->id);

        $handler->applyBookMetadata($book, [
            'rating' => null,
        ], $user, $library->id);

        $this->assertNull($this->ratingForBook($book, $user, $library));
    }

    public function test_rating_edge_matrix_invalid_value_clears_existing_rating(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'rating' => 4,
        ], $user, $library->id);

        $handler->applyBookMetadata($book, [
            'rating' => 42,
        ], $user, $library->id);

        $this->assertNull($this->ratingForBook($book, $user, $library));
    }

    public function test_rating_change_updates_existing_link_without_delete(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $this->createRating($user, $library, 4);
        $this->createRating($user, $library, 8);

        DB::table('books_ratings_links')->insert([
            'id' => -9802,
            'idx' => 9802,
            'uuid' => 'rating-pivot-2',
            'book' => $book->uuid,
            'rating' => 4,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'rating' => 8,
        ], $user, $library->id);

        $deleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete') && str_contains($sql, 'books_ratings_links');
        }));

        $this->assertSame([], $deleteQueries, 'Changing rating to another existing value must update the link without delete+reinsert');
        $this->assertSame(8, $this->ratingForBook($book, $user, $library));
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Rating Edge Matrix',
        ]);

        $book = UserBook::create([
            'id' => 9501,
            'uuid' => 'dd000000-0000-4000-8000-000000009501',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Rating Test Book',
            'path' => 'rating-test-book',
            'author_sort' => 'Tester, Rating',
            'last_modified' => now(),
        ]);

        return [$user, $library, $book->fresh()];
    }

    private function createRating(User $user, Library $library, int $value): void
    {
        DB::table('books_ratings')->insert([
            'id' => $value,
            'idx' => $value,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'rating' => $value,
            'uuid' => sprintf('00000000-0000-4000-8000-%012d', $value),
            'created_at' => now(),
            'updated_at' => now(),
        ]);
    }

    private function ratingForBook(UserBook $book, User $user, Library $library): ?int
    {
        $ratingId = DB::table('books_ratings_links')
            ->where('book', $book->uuid)
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->value('rating');

        return $ratingId !== null ? (int) $ratingId : null;
    }
}
