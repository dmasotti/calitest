<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class BookMetadataHandlerLanguageEdgeMatrixTest extends TestCase
{
    use RefreshDatabase;

    public function test_languages_noop_update_does_not_delete_existing_links(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $englishId = $this->createLanguage($user, $library, 1101, 'eng');
        $italianId = $this->createLanguage($user, $library, 1102, 'ita');

        DB::table('books_languages_link')->insert([
            [
                'uuid' => 'lang-pivot-1',
                'book' => $book->uuid,
                'lang_code' => $englishId,
                'item_order' => 0,
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
            [
                'uuid' => 'lang-pivot-2',
                'book' => $book->uuid,
                'lang_code' => $italianId,
                'item_order' => 1,
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
        ]);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'languages' => ['eng', 'ita'],
        ], $user, $library->id);

        $deleteQueries = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'delete') && str_contains($sql, 'books_languages_link');
        }));

        $this->assertSame([], $deleteQueries, 'No-op language update must not delete and recreate pivot rows');
        $this->assertSame(['eng', 'ita'], $this->languageCodesForBook($book, $user, $library));
    }

    public function test_languages_existing_resolution_is_prefetched_not_one_query_per_language(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        foreach (['eng', 'ita', 'fra', 'deu', 'spa'] as $index => $langCode) {
            $this->createLanguage($user, $library, 1201 + $index, $langCode);
        }

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'languages' => ['eng', 'ita', 'fra', 'deu', 'spa'],
        ], $user, $library->id);

        $languageSelects = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'from `books_languages`') && str_contains($sql, 'select');
        }));

        $this->assertLessThanOrEqual(
            2,
            count($languageSelects),
            'Language resolution should be prefetched in bulk, not one SELECT per language code'
        );
        $this->assertSame(['deu', 'eng', 'fra', 'ita', 'spa'], $this->languageCodesForBook($book, $user, $library));
    }

    public function test_languages_edge_matrix_deduplicates_payload_and_uses_bulk_link_write(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $queries = [];
        DB::listen(static function ($query) use (&$queries): void {
            $queries[] = strtolower($query->sql);
        });

        $handler->applyBookMetadata($book, [
            'languages' => ['eng', ' ita ', 'eng', 'fra', ' '],
        ], $user, $library->id);

        $linkWrites = array_values(array_filter($queries, static function (string $sql): bool {
            return str_contains($sql, 'books_languages_link')
                && (str_contains($sql, 'insert') || str_contains($sql, 'update'));
        }));

        $this->assertLessThanOrEqual(
            2,
            count($linkWrites),
            'Language pivot persistence must use bulk write, not one insert/update per language row'
        );
        $this->assertSame(['eng', 'fra', 'ita'], $this->languageCodesForBook($book, $user, $library));
    }

    public function test_languages_edge_matrix_explicit_empty_array_clears_links(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $handler = app(BookMetadataHandler::class);

        $handler->applyBookMetadata($book, [
            'languages' => ['eng', 'ita'],
        ], $user, $library->id);

        $handler->applyBookMetadata($book, [
            'languages' => [],
        ], $user, $library->id);

        $this->assertSame([], $this->languageCodesForBook($book, $user, $library));
    }

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Language Edge Matrix',
        ]);

        $book = UserBook::create([
            'id' => 9101,
            'uuid' => 'ee000000-0000-4000-8000-000000009101',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Language Test Book',
            'path' => 'language-test-book',
            'author_sort' => 'Tester, Lang',
            'last_modified' => now(),
        ]);

        return [$user, $library, $book->fresh()];
    }

    private function createLanguage(User $user, Library $library, int $id, string $langCode): int
    {
        $row = [
            'id' => $id,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'lang_code' => $langCode,
            'uuid' => sprintf('00000000-0000-4000-8000-%012d', $id),
            'created_at' => now(),
            'updated_at' => now(),
        ];
        if (\Illuminate\Support\Facades\Schema::hasColumn('books_languages', 'idx')) {
            $row['idx'] = $id;
        }
        DB::table('books_languages')->insert($row);

        return $id;
    }

    private function languageCodesForBook(UserBook $book, User $user, Library $library): array
    {
        return DB::table('books_languages_link')
            ->join('books_languages', 'books_languages_link.lang_code', '=', 'books_languages.id')
            ->where('books_languages_link.book', $book->uuid)
            ->where('books_languages_link.user_id', $user->id)
            ->where('books_languages_link.library_id', $library->id)
            ->orderBy('books_languages.lang_code')
            ->pluck('books_languages.lang_code')
            ->values()
            ->all();
    }
}
