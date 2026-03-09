<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Services\Sync\BookMetadataHandler;
use App\Services\Sync\CoreDelegate;
use App\Services\SyncService;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Tests\TestCase;

class IdentifiersSyncEndToEndTest extends TestCase
{
    use RefreshDatabase;

    public function test_metadata_failure_on_tags_is_propagated_and_identifiers_are_not_persisted(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => '11111111-2222-3333-4444-555555555555',
        ]);

        $core = app(CoreDelegate::class);
        $handler = new class($core) extends BookMetadataHandler {
            protected function attachTagsToUserBook($userBook, $tags, $user, $libraryId): void
            {
                throw new \RuntimeException('forced tags failure');
            }

            protected function attachRatingToUserBook(UserBook $userBook, int $ratingValue, $user, int $libraryId): void
            {
                // Keep test focused on identifiers flow.
            }
        };

        try {
            $handler->applyBookMetadata($userBook, [
                'title' => 'Identifiers Book',
                'tags' => [['name' => 'will-fail']],
                'identifiers' => [
                    'isbn' => '9780262035613',
                    'google' => 'Np9SDQAAQBAJ',
                    'goodreads' => '30422361',
                ],
                'rating' => 0,
            ], $user, $library->id);
            $this->fail('Expected metadata failure when tags step throws.');
        } catch (\RuntimeException $e) {
            $this->assertStringContainsString('applyBookMetadata failed at step "tags"', $e->getMessage());
        }

        $this->assertDatabaseMissing('books_identifiers', [
            'book' => $userBook->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'type' => 'isbn',
        ]);
    }

    public function test_snapshot_item_includes_all_identifiers_not_only_isbn(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => 'aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee',
            'isbn' => '9780262035613',
        ]);

        DB::table('books_identifiers')->insert([
            'id' => -1,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book' => $userBook->uuid,
            'type' => 'google',
            'val' => 'Np9SDQAAQBAJ',
            'uuid' => '99999999-8888-7777-6666-555555555555',
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $service = app(SyncService::class);
        $snapshot = $service->buildSnapshotItem($userBook->fresh());

        $this->assertArrayHasKey('identifiers', $snapshot);
        $this->assertSame('9780262035613', $snapshot['identifiers']['isbn'] ?? null);
        $this->assertSame('Np9SDQAAQBAJ', $snapshot['identifiers']['google'] ?? null);
    }
}
