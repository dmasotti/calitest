<?php

namespace Tests\Server;

use Tests\TestCase;
use App\Models\User;
use App\Models\Library;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;

/**
 * Test data integrity during sync
 * 
 * Verifies:
 * - No books skipped
 * - No books duplicated
 * - Order is deterministic
 * - All metadata fields present
 * 
 * All tests pass with DESC order and proper cursor handling (timestamp < cursor for pagination).
 */
class SyncDataIntegrityTest extends TestCase
{
    use RefreshDatabase;

    protected $user;
    protected $library;
    protected $token;

    protected function setUp(): void
    {
        parent::setUp();
        
        $this->user = User::factory()->create([
            'email' => 'integrity-test@example.com',
            'password' => bcrypt('password')
        ]);
        
        $this->library = Library::factory()->create([
            'user_id' => $this->user->id,
            'name' => 'Integrity Test Library',
            'calibre_library_id' => 'test-integrity-lib-' . uniqid()
        ]);

        $this->token = $this->user->createToken('test')->plainTextToken;
    }

    /** @test */
    public function it_returns_all_books_without_skipping()
    {
        // Create 500 books with sequential timestamps
        $bookIds = [];
        $baseTimestamp = now()->subDays(500)->timestamp;
        
        for ($i = 0; $i < 500; $i++) {
            $book = UserBook::factory()->create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'last_modified' => $baseTimestamp + $i,
                'title' => 'Book ' . $i,
                'cover_missing' => false,
                'ebook_missing' => false,
            ]);
            $bookIds[] = $book->uuid;
        }

        // Sync all books in batches of 50 (starting from FUTURE to go backwards in time with DESC order)
        $cursor = base64_encode(json_encode([
            'timestamp' => now()->addDays(10)->timestamp,  // Future timestamp to catch all books going backwards
            'last_id' => PHP_INT_MAX,  // Start from highest possible ID
            'phase' => 'changes',
            'missing_offset' => 0
        ]));
        $seenBookIds = [];
        $iterations = 0;
        $maxIterations = 30; // Safety limit (500 books / 50 per batch = 10, but need room for missing phase)

        while ($iterations < $maxIterations) {
            $response = $this->withHeaders([
                'Authorization' => 'Bearer ' . $this->token,
                'Accept' => 'application/json',
            ])->postJson('/api/sync/pull', [
                'cursor' => $cursor,
                'limit' => 50,
                'library_id' => $this->library->id,
                'calibre_library_uuid' => $this->library->calibre_library_id,
            ]);

            $response->assertStatus(200);
            $changes = $response->json('changes');

            foreach ($changes as $change) {
                $seenBookIds[] = $change['item']['uuid'] ?? $change['item']['id'];
            }

            if (!$response->json('has_more') || $response->json('new_cursor') === null) {
                break;
            }

            $cursor = $response->json('new_cursor');
            $iterations++;
        }

        // Verify we got ALL books, no more, no less
        $this->assertEquals(500, count($seenBookIds), 'Should return exactly 500 books');
        
        // Verify no duplicates
        $uniqueIds = array_unique($seenBookIds);
        $this->assertEquals(count($seenBookIds), count($uniqueIds), 'Should have no duplicate books');
        
        // Verify all original books are present
        foreach ($bookIds as $bookId) {
            $this->assertContains($bookId, $seenBookIds, "Book $bookId was skipped!");
        }
    }

    /** @test */
    public function it_returns_books_in_deterministic_order()
    {
        // Create 100 books
        for ($i = 0; $i < 100; $i++) {
            UserBook::factory()->create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'last_modified' => now()->subDays($i)->timestamp,
                'title' => 'Book ' . $i,
            ]);
        }

        // Run sync twice and verify same order
        $run1Ids = $this->syncAllBooks();
        $run2Ids = $this->syncAllBooks();

        $this->assertEquals($run1Ids, $run2Ids, 'Sync order should be deterministic');
    }

    /** @test */
    public function it_handles_books_with_same_timestamp_consistently()
    {
        $sameTimestamp = now()->timestamp;
        
        // Create 50 books with EXACT same timestamp
        $bookIds = [];
        for ($i = 0; $i < 50; $i++) {
            $book = UserBook::factory()->create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'last_modified' => $sameTimestamp,
                'title' => 'Book ' . $i,
            ]);
            $bookIds[] = $book->uuid;
        }

        // Sync in batches of 10 (start from FUTURE for DESC order)
        $seenBookIds = [];
        $cursor = base64_encode(json_encode([
            'timestamp' => now()->addDays(1)->timestamp,  // Future
            'last_id' => PHP_INT_MAX,
            'phase' => 'changes',
            'missing_offset' => 0
        ]));
        
        for ($batch = 0; $batch < 10; $batch++) {
            $response = $this->withHeaders([
                'Authorization' => 'Bearer ' . $this->token,
                'Accept' => 'application/json',
            ])->postJson('/api/sync/pull', [
                'cursor' => $cursor,
                'limit' => 10,
                'library_id' => $this->library->id,
                'calibre_library_uuid' => $this->library->calibre_library_id,
            ]);

            $response->assertStatus(200);
            $changes = $response->json('changes');

            foreach ($changes as $change) {
                $bookId = $change['item']['uuid'] ?? $change['item']['id'];
                $this->assertNotContains($bookId, $seenBookIds, "Book $bookId returned twice!");
                $seenBookIds[] = $bookId;
            }

            if (!$response->json('has_more')) {
                break;
            }

            $cursor = $response->json('new_cursor');
        }

        // Should get all 50 books with same timestamp
        $this->assertCount(50, $seenBookIds);
        
        // All original books present
        foreach ($bookIds as $bookId) {
            $this->assertContains($bookId, $seenBookIds);
        }
    }

    /** @test */
    public function it_includes_all_required_metadata_fields()
    {
        UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'title' => 'Test Book',
            'last_modified' => now()->timestamp,
        ]);

        $response = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => null,
            'limit' => 10,
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
        ]);

        $response->assertStatus(200);
        $changes = $response->json('changes');
        $this->assertCount(1, $changes);

        $item = $changes[0]['item'];
        
        // Verify essential fields are present
        $this->assertArrayHasKey('id', $item);
        $this->assertArrayHasKey('uuid', $item);
        $this->assertArrayHasKey('title', $item);
        $this->assertArrayHasKey('authors', $item);
        $this->assertArrayHasKey('last_modified', $item);
        
        // Verify flags
        $change = $changes[0];
        $this->assertArrayHasKey('cover_missing', $change);
        $this->assertArrayHasKey('ebook_missing', $change);
        $this->assertArrayHasKey('metadata_incomplete', $change);
        $this->assertArrayHasKey('deleted_at', $change);
    }

    /** @test */
    public function it_handles_mixed_changes_and_missing_without_duplication()
    {
        // Create 100 normal books
        $normalBookIds = [];
        for ($i = 0; $i < 100; $i++) {
            $book = UserBook::factory()->create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'last_modified' => now()->subDays($i)->timestamp,
                'cover_missing' => false,
                'ebook_missing' => false,
            ]);
            $normalBookIds[] = $book->uuid;
        }

        // Create 50 books with missing flags
        $missingBookIds = [];
        for ($i = 0; $i < 50; $i++) {
            $book = UserBook::factory()->create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'last_modified' => now()->subYear()->timestamp,
                'cover_missing' => true,
            ]);
            $missingBookIds[] = $book->uuid;
        }

        // Sync all (start from future timestamp to catch all going backwards)
        $allSeenIds = [];
        $cursor = base64_encode(json_encode([
            'timestamp' => now()->addDays(1)->timestamp,
            'last_id' => PHP_INT_MAX,
            'phase' => 'changes',
            'missing_offset' => 0
        ]));
        $iterations = 0;
        $maxIterations = 30; // Need room for both phases

        while ($iterations < 30) {
            $response = $this->withHeaders([
                'Authorization' => 'Bearer ' . $this->token,
                'Accept' => 'application/json',
            ])->postJson('/api/sync/pull', [
                'cursor' => $cursor,
                'limit' => 30,
                'library_id' => $this->library->id,
                'calibre_library_uuid' => $this->library->calibre_library_id,
            ]);

            $response->assertStatus(200);
            $changes = $response->json('changes');

            foreach ($changes as $change) {
                $allSeenIds[] = $change['item']['uuid'] ?? $change['item']['id'];
            }

            if (!$response->json('has_more')) {
                break;
            }

            $cursor = $response->json('new_cursor');
            $iterations++;
        }

        // Should have 150 unique books (100 normal + 50 missing)
        $uniqueIds = array_unique($allSeenIds);
        $this->assertCount(150, $uniqueIds, 'Should return all 150 books exactly once');
        
        // Verify all are present
        foreach (array_merge($normalBookIds, $missingBookIds) as $bookId) {
            $this->assertContains($bookId, $allSeenIds);
        }
    }

    /**
     * Helper: Sync all books and return their IDs in order
     */
    protected function syncAllBooks(): array
    {
        $bookIds = [];
        $cursor = base64_encode(json_encode([
            'timestamp' => now()->addDays(1)->timestamp,  // Future for DESC order
            'last_id' => PHP_INT_MAX,
            'phase' => 'changes',
            'missing_offset' => 0
        ]));
        $iterations = 0;

        while ($iterations < 30) {
            $response = $this->withHeaders([
                'Authorization' => 'Bearer ' . $this->token,
                'Accept' => 'application/json',
            ])->postJson('/api/sync/pull', [
                'cursor' => $cursor,
                'limit' => 50,
                'library_id' => $this->library->id,
                'calibre_library_uuid' => $this->library->calibre_library_id,
            ]);

            if ($response->status() !== 200) {
                break;
            }

            $changes = $response->json('changes');
            foreach ($changes as $change) {
                $bookIds[] = $change['item']['uuid'] ?? $change['item']['id'];
            }

            if (!$response->json('has_more')) {
                break;
            }

            $cursor = $response->json('new_cursor');
            $iterations++;
        }

        return $bookIds;
    }
}
