<?php

namespace Tests\Server;

use Tests\TestCase;
use App\Models\User;
use App\Models\Library;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Artisan;

/**
 * Test composite cursor pagination for sync
 * 
 * Tests the two-phase sync approach:
 * - Phase 1: Changes based on last_modified
 * - Phase 2: Missing data (cover_missing, ebook_missing)
 * 
 * Verifies:
 * - No infinite loops
 * - Correct cursor progression
 * - Phase transitions
 * - Backward compatibility with legacy cursors
 */
class SyncCompositeCursorTest extends TestCase
{
    use RefreshDatabase;

    protected $user;
    protected $library;
    protected $token;

    protected function setUp(): void
    {
        parent::setUp();
        
        // Create test user and library
        $this->user = User::factory()->create([
            'email' => 'cursor-test@example.com',
            'password' => bcrypt('password')
        ]);
        
        $this->library = Library::factory()->create([
            'user_id' => $this->user->id,
            'name' => 'Cursor Test Library',
            'calibre_library_id' => 'test-cursor-lib-' . uniqid()
        ]);

        // Create API token
        $this->token = $this->user->createToken('test')->plainTextToken;
    }

    /** @test */
    public function it_parses_legacy_simple_cursor()
    {
        // Legacy cursor: base64(timestamp)
        $timestamp = 1767236044;
        $legacyCursor = base64_encode((string)$timestamp);

        $response = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => $legacyCursor,
            'limit' => 200,
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
            'stream' => false,
        ]);

        $response->assertStatus(200);
        $this->assertArrayHasKey('new_cursor', $response->json());
    }

    /** @test */
    public function it_parses_composite_cursor()
    {
        // Composite cursor: base64(json)
        $cursorData = [
            'timestamp' => 1767236044,
            'last_id' => 100,
            'phase' => 'changes',
            'missing_offset' => 0
        ];
        $compositeCursor = base64_encode(json_encode($cursorData));

        $response = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => $compositeCursor,
            'limit' => 200,
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
            'stream' => false,
        ]);

        $response->assertStatus(200);
        $this->assertArrayHasKey('new_cursor', $response->json());
    }

    /** @test */
    public function it_returns_composite_cursor_on_first_sync()
    {
        // Create two books so first page always returns a cursor with limit=1
        UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'last_modified' => now()->timestamp,
            'cover_missing' => false,
            'ebook_missing' => false,
        ]);
        UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'last_modified' => now()->subSecond()->timestamp,
            'cover_missing' => false,
            'ebook_missing' => false,
        ]);

        $response = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => null,
            'limit' => 1,
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
            'stream' => false,
        ]);

        $response->assertStatus(200);
        
        $newCursor = $response->json('new_cursor');
        $this->assertNotNull($newCursor);
        
        // Decode cursor and verify it's composite
        $decoded = json_decode(base64_decode($newCursor), true);
        $this->assertIsArray($decoded);
        $this->assertArrayHasKey('timestamp', $decoded);
        $this->assertArrayHasKey('last_id', $decoded);
        $this->assertArrayHasKey('phase', $decoded);
        $this->assertArrayHasKey('missing_offset', $decoded);
    }

    /** @test */
    public function it_excludes_missing_books_in_changes_phase()
    {
        // Create books with different states
        $bookWithChange = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'last_modified' => now()->timestamp,
            'cover_missing' => false,
            'ebook_missing' => false,
            'title' => 'Book with Change'
        ]);

        $bookWithMissing = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'last_modified' => now()->subYear()->timestamp, // Old timestamp
            'cover_missing' => true, // But missing!
            'ebook_missing' => false,
            'title' => 'Book with Missing Cover'
        ]);

        // First sync (changes phase)
        $response = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => null,
            'limit' => 200,
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
            'stream' => false,
        ]);

        $response->assertStatus(200);
        $changes = $response->json('changes');
        
        // Should only return the book with recent change, NOT the one with missing flag
        $this->assertCount(1, $changes);
        $this->assertEquals('Book with Change', $changes[0]['item']['title']);
    }

    /** @test */
    public function it_transitions_from_changes_to_missing_phase()
    {
        // Create 1 book with change and 1 with missing
        UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'last_modified' => now()->timestamp,
            'cover_missing' => false,
        ]);

        UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'last_modified' => now()->subYear()->timestamp,
            'metadata_incomplete' => true,
        ]);

        // Request #1: Changes phase (limit high enough to get all changes)
        $response1 = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => null,
            'limit' => 200,
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
            'stream' => false,
        ]);

        $response1->assertStatus(200);
        $cursor1 = $response1->json('new_cursor');
        $decoded1 = json_decode(base64_decode($cursor1), true);
        
        // Since we got < 200 books, should transition to missing phase
        $this->assertEquals('missing', $decoded1['phase']);
        
        // Request #2: Missing phase
        $response2 = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => $cursor1,
            'limit' => 200,
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
            'stream' => false,
        ]);

        $response2->assertStatus(200);
        $changes2 = $response2->json('changes');
        
        // Should return the book flagged as incomplete metadata
        $this->assertGreaterThan(0, count($changes2));
        $this->assertTrue($changes2[0]['metadata_incomplete']);
    }

    /** @test */
    public function it_completes_sync_without_infinite_loop()
    {
        // Create books that previously caused loops
        for ($i = 0; $i < 50; $i++) {
            UserBook::factory()->create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'last_modified' => now()->subYear()->timestamp, // Old timestamp
                'cover_missing' => true, // Missing flag
                'updated_at' => now(), // But recently updated
            ]);
        }

        $cursor = null;
        $iterations = 0;
        $maxIterations = 10;
        $seenCursors = [];

        while ($iterations < $maxIterations) {
            $response = $this->withHeaders([
                'Authorization' => 'Bearer ' . $this->token,
                'Accept' => 'application/json',
            ])->postJson('/api/sync/pull', [
                'cursor' => $cursor,
                'limit' => 50,
                'library_id' => $this->library->id,
                'calibre_library_uuid' => $this->library->calibre_library_id,
            'stream' => false,
            ]);

            $response->assertStatus(200);
            
            $hasMore = $response->json('has_more');
            $newCursor = $response->json('new_cursor');
            
            // Check for infinite loop: same cursor returned
            if (in_array($newCursor, $seenCursors)) {
                $this->fail('Infinite loop detected: cursor repeated!');
            }
            $seenCursors[] = $newCursor;
            
            if (!$hasMore || $newCursor === null) {
                // Sync completed successfully!
                $this->assertTrue(true);
                return;
            }
            
            $cursor = $newCursor;
            $iterations++;
        }

        $this->fail('Sync did not complete within ' . $maxIterations . ' iterations');
    }

    /** @test */
    public function it_handles_empty_library()
    {
        // No books in library
        $response = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => null,
            'limit' => 200,
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
            'stream' => false,
        ]);

        $response->assertStatus(200);
        $this->assertEquals([], $response->json('changes'));
        $this->assertFalse($response->json('has_more'));
        $this->assertNull($response->json('new_cursor'));
    }

    /** @test */
    public function it_uses_id_tie_breaker_for_same_timestamp()
    {
        $timestamp = now()->timestamp;
        
        // Create multiple books with SAME timestamp but different IDs
        $book1 = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'last_modified' => $timestamp,
            'title' => 'Book 1'
        ]);

        $book2 = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'last_modified' => $timestamp,
            'title' => 'Book 2'
        ]);

        $book3 = UserBook::factory()->create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'last_modified' => $timestamp,
            'title' => 'Book 3'
        ]);

        // Request with limit=1 to force pagination
        $response1 = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => null,
            'limit' => 1,
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
            'stream' => false,
        ]);

        $response1->assertStatus(200);
        $changes1 = $response1->json('changes');
        $this->assertCount(1, $changes1);
        
        $cursor1 = $response1->json('new_cursor');
        $decoded1 = json_decode(base64_decode($cursor1), true);
        
        // Cursor should have last_id for tie-breaking
        $this->assertArrayHasKey('last_id', $decoded1);
        $this->assertGreaterThan(0, $decoded1['last_id']);
        
        // Request #2 should get DIFFERENT book (not the same one)
        $response2 = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => $cursor1,
            'limit' => 1,
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
            'stream' => false,
        ]);

        $response2->assertStatus(200);
        $changes2 = $response2->json('changes');
        $this->assertCount(1, $changes2);
        
        // Should be different book
        $this->assertNotEquals($changes1[0]['item']['id'], $changes2[0]['item']['id']);
    }
}
