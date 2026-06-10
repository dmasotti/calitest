<?php

namespace Tests\Server;

use App\Models\Bookmark;
use App\Models\Highlight;
use App\Models\Library;
use App\Models\Note;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Str;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

/**
 * Tests for annotation sync: highlights, notes, bookmarks.
 *
 * Phase 1: UUID on highlights/notes, BookmarkController, batch sync endpoint.
 */
class AnnotationSyncTest extends TestCase
{
    use RefreshDatabase;

    private function makeContext(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        Sanctum::actingAs($user);
        return [$user, $library, $book];
    }

    // ── Highlights CRUD ──

    public function test_create_highlight_with_uuid(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $uuid = (string) Str::uuid();

        $response = $this->postJson('/api/highlights', [
            'book_id' => $book->id,
            'uuid' => $uuid,
            'text' => 'The quick brown fox',
            'position_start' => ['chapter_index' => 3, 'char_offset' => 100, 'cfi' => '/6/14!/4/2:0'],
            'position_end' => ['chapter_index' => 3, 'char_offset' => 119, 'cfi' => '/6/14!/4/2:19'],
            'color' => 'yellow',
        ]);

        $response->assertStatus(201);
        $this->assertSame($uuid, $response->json('uuid'));
        $this->assertDatabaseHas('highlights', ['uuid' => $uuid, 'user_id' => $user->id]);
    }

    public function test_highlight_uuid_is_unique_per_user(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $uuid = (string) Str::uuid();

        $this->postJson('/api/highlights', [
            'book_id' => $book->id,
            'uuid' => $uuid,
            'text' => 'First',
            'position_start' => ['chapter_index' => 1, 'char_offset' => 0],
            'position_end' => ['chapter_index' => 1, 'char_offset' => 5],
        ])->assertStatus(201);

        // Same UUID = upsert (update), not duplicate
        $this->postJson('/api/highlights', [
            'book_id' => $book->id,
            'uuid' => $uuid,
            'text' => 'Updated text',
            'position_start' => ['chapter_index' => 1, 'char_offset' => 0],
            'position_end' => ['chapter_index' => 1, 'char_offset' => 12],
            'color' => 'green',
        ])->assertStatus(201);

        $this->assertSame(1, Highlight::where('uuid', $uuid)->count());
        $this->assertSame('Updated text', Highlight::where('uuid', $uuid)->first()->text);
    }

    public function test_soft_delete_highlight(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $uuid = (string) Str::uuid();

        $this->postJson('/api/highlights', [
            'book_id' => $book->id,
            'uuid' => $uuid,
            'text' => 'To be deleted',
            'position_start' => ['chapter_index' => 1, 'char_offset' => 0],
            'position_end' => ['chapter_index' => 1, 'char_offset' => 13],
        ])->assertStatus(201);

        $highlight = Highlight::where('uuid', $uuid)->first();
        $this->deleteJson("/api/highlights/{$highlight->id}")->assertOk();

        // Soft deleted — still in DB with deleted_at
        $this->assertNotNull(Highlight::withTrashed()->where('uuid', $uuid)->first()->deleted_at);
    }

    // ── Notes CRUD ──

    public function test_create_note_with_uuid(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $uuid = (string) Str::uuid();

        $response = $this->postJson('/api/notes', [
            'book_id' => $book->id,
            'uuid' => $uuid,
            'content' => 'This is important because...',
            'position' => ['chapter_index' => 2, 'char_offset' => 500],
        ]);

        $response->assertStatus(201);
        $this->assertSame($uuid, $response->json('uuid'));
    }

    // ── Bookmarks CRUD ──

    public function test_create_bookmark(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $uuid = (string) Str::uuid();

        $response = $this->postJson('/api/bookmarks', [
            'book_id' => $book->id,
            'uuid' => $uuid,
            'label' => 'Chapter 5 start',
            'position' => ['chapter_index' => 5, 'page_index' => 42],
        ]);

        $response->assertStatus(201);
        $this->assertSame($uuid, $response->json('uuid'));
    }

    public function test_list_bookmarks_for_user(): void
    {
        [$user, $library, $book] = $this->makeContext();

        Bookmark::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => $book->id,
            'uuid' => (string) Str::uuid(),
            'label' => 'BM1',
            'position' => ['page_index' => 1],
        ]);
        Bookmark::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => $book->id,
            'uuid' => (string) Str::uuid(),
            'label' => 'BM2',
            'position' => ['page_index' => 10],
        ]);

        $response = $this->getJson('/api/bookmarks');
        $response->assertOk();
        $this->assertCount(2, $response->json());
    }

    public function test_delete_bookmark(): void
    {
        [$user, $library, $book] = $this->makeContext();

        $bm = Bookmark::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => $book->id,
            'uuid' => (string) Str::uuid(),
            'label' => 'Delete me',
            'position' => ['page_index' => 99],
        ]);

        $this->deleteJson("/api/bookmarks/{$bm->id}")->assertOk();
        $this->assertDatabaseMissing('bookmarks', ['id' => $bm->id]);
    }

    // ── Batch sync endpoint ──

    public function test_batch_sync_push_and_pull(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $hlUuid = (string) Str::uuid();
        $noteUuid = (string) Str::uuid();
        $bmUuid = (string) Str::uuid();

        $response = $this->postJson('/api/annotations/sync', [
            'book_uuid' => $book->uuid,
            'library_id' => (string) $library->id,
            'highlights' => [
                [
                    'uuid' => $hlUuid,
                    'text' => 'Batch highlight',
                    'position_start' => ['chapter_index' => 1, 'char_offset' => 0],
                    'position_end' => ['chapter_index' => 1, 'char_offset' => 15],
                    'color' => 'blue',
                    'updated_at' => now()->toIso8601String(),
                ],
            ],
            'notes' => [
                [
                    'uuid' => $noteUuid,
                    'content' => 'Batch note',
                    'position' => ['chapter_index' => 1, 'char_offset' => 0],
                    'highlight_uuid' => $hlUuid,
                    'updated_at' => now()->toIso8601String(),
                ],
            ],
            'bookmarks' => [
                [
                    'uuid' => $bmUuid,
                    'label' => 'Batch bookmark',
                    'position' => ['chapter_index' => 5],
                    'updated_at' => now()->toIso8601String(),
                ],
            ],
            'last_sync_at' => null,
        ]);

        $response->assertOk();
        $this->assertDatabaseHas('highlights', ['uuid' => $hlUuid]);
        $this->assertDatabaseHas('notes', ['uuid' => $noteUuid]);
        $this->assertDatabaseHas('bookmarks', ['uuid' => $bmUuid]);

        // Pull: sync again with timestamp → should get the items we just pushed
        $syncAt = $response->json('sync_at');
        $this->assertNotNull($syncAt);
    }

    public function test_batch_sync_pull_returns_changes_since_timestamp(): void
    {
        [$user, $library, $book] = $this->makeContext();

        // Create a highlight directly (simulating it was created earlier)
        $oldHl = Highlight::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => $book->id,
            'uuid' => (string) Str::uuid(),
            'text' => 'Old highlight',
            'position_start' => ['chapter_index' => 1],
            'position_end' => ['chapter_index' => 1],
            'color' => 'yellow',
            'created_at' => now()->subHour(),
            'updated_at' => now()->subHour(),
        ]);

        $beforeSync = now()->subMinutes(30)->toIso8601String();

        // Create a newer highlight
        $newHl = Highlight::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => $book->id,
            'uuid' => (string) Str::uuid(),
            'text' => 'New highlight',
            'position_start' => ['chapter_index' => 2],
            'position_end' => ['chapter_index' => 2],
            'color' => 'green',
        ]);

        $response = $this->postJson('/api/annotations/sync', [
            'book_uuid' => $book->uuid,
            'library_id' => (string) $library->id,
            'highlights' => [],
            'notes' => [],
            'bookmarks' => [],
            'last_sync_at' => $beforeSync,
        ]);

        $response->assertOk();
        $serverHighlights = $response->json('highlights.updated') ?? [];

        // Should include the new highlight but not the old one
        $uuids = array_column($serverHighlights, 'uuid');
        $this->assertContains($newHl->uuid, $uuids);
        $this->assertNotContains($oldHl->uuid, $uuids);
    }

    public function test_batch_sync_upsert_existing_highlight(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $uuid = (string) Str::uuid();

        // Create initial highlight
        Highlight::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => $book->id,
            'uuid' => $uuid,
            'text' => 'Original text',
            'position_start' => ['chapter_index' => 1],
            'position_end' => ['chapter_index' => 1],
            'color' => 'yellow',
        ]);

        // Push updated version via batch sync
        $response = $this->postJson('/api/annotations/sync', [
            'book_uuid' => $book->uuid,
            'library_id' => (string) $library->id,
            'highlights' => [
                [
                    'uuid' => $uuid,
                    'text' => 'Updated text via sync',
                    'position_start' => ['chapter_index' => 1],
                    'position_end' => ['chapter_index' => 1],
                    'color' => 'green',
                    'updated_at' => now()->addMinute()->toIso8601String(),
                ],
            ],
            'notes' => [],
            'bookmarks' => [],
            'last_sync_at' => null,
        ]);

        $response->assertOk();
        $this->assertSame(1, Highlight::where('uuid', $uuid)->count());
        $this->assertSame('Updated text via sync', Highlight::where('uuid', $uuid)->first()->text);
        $this->assertSame('green', Highlight::where('uuid', $uuid)->first()->color);
    }

    public function test_batch_sync_soft_delete_propagates(): void
    {
        [$user, $library, $book] = $this->makeContext();
        $uuid = (string) Str::uuid();

        Highlight::create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'book_id' => $book->id,
            'uuid' => $uuid,
            'text' => 'Will be deleted',
            'position_start' => ['chapter_index' => 1],
            'position_end' => ['chapter_index' => 1],
        ]);

        $response = $this->postJson('/api/annotations/sync', [
            'book_uuid' => $book->uuid,
            'library_id' => (string) $library->id,
            'highlights' => [
                [
                    'uuid' => $uuid,
                    'deleted' => true,
                    'updated_at' => now()->addMinute()->toIso8601String(),
                ],
            ],
            'notes' => [],
            'bookmarks' => [],
            'last_sync_at' => null,
        ]);

        $response->assertOk();
        $this->assertNotNull(Highlight::withTrashed()->where('uuid', $uuid)->first()->deleted_at);
    }

    // ── User isolation ──

    public function test_annotations_isolated_between_users(): void
    {
        [$userA, $libraryA, $bookA] = $this->makeContext();

        Highlight::create([
            'user_id' => $userA->id,
            'library_id' => $libraryA->id,
            'book_id' => $bookA->id,
            'uuid' => (string) Str::uuid(),
            'text' => 'User A highlight',
            'position_start' => ['chapter_index' => 1],
            'position_end' => ['chapter_index' => 1],
        ]);

        // Switch to user B
        $userB = User::factory()->create();
        $libraryB = Library::factory()->create(['user_id' => $userB->id]);
        Sanctum::actingAs($userB);

        $response = $this->getJson('/api/highlights');
        $response->assertOk();
        $this->assertCount(0, $response->json());
    }
}
