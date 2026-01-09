<?php

namespace Tests\Server;

use Tests\TestCase;
use App\Models\User;
use App\Models\Library;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;

/**
 * Test missing phase specifically
 * 
 * Verifies:
 * - Missing phase returns ONLY books with missing flags
 * - Self-healing works (flags cleared when data exists)
 * - Offset pagination works correctly
 * - Missing phase completes when no more missing books
 */
class SyncMissingPhaseTest extends TestCase
{
    use RefreshDatabase;

    protected $user;
    protected $library;
    protected $token;

    protected function setUp(): void
    {
        parent::setUp();
        
        $this->user = User::factory()->create([
            'email' => 'missing-test@example.com',
            'password' => bcrypt('password')
        ]);
        
        $this->library = Library::factory()->create([
            'user_id' => $this->user->id,
            'name' => 'Missing Test Library',
            'calibre_library_id' => 'test-missing-lib-' . uniqid()
        ]);

        $this->token = $this->user->createToken('test')->plainTextToken;
    }

    /** @test */
    public function it_returns_only_books_with_missing_flags()
    {
        // Create normal books (no missing flags)
        for ($i = 0; $i < 10; $i++) {
            UserBook::factory()->create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'last_modified' => now()->timestamp,
                'cover_missing' => false,
                'ebook_missing' => false,
                'metadata_incomplete' => false,
            ]);
        }

        // Create books with missing flags (no cover_url to prevent self-healing)
        $missingBooks = [];
        for ($i = 0; $i < 5; $i++) {
            $missingBooks[] = UserBook::create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'uuid' => \Illuminate\Support\Str::uuid(),
                'title' => 'Missing Book ' . $i,
                'last_modified' => now()->subYear()->timestamp,
                'cover_missing' => true,
                'ebook_missing' => false,
                'cover_url' => null, // Truly missing
            ]);
        }

        // Build cursor for missing phase directly
        $cursor = base64_encode(json_encode([
            'timestamp' => now()->timestamp,
            'last_id' => 0,
            'phase' => 'missing',
            'missing_offset' => 0
        ]));

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
        
        // Should return ONLY the 5 books with missing flags
        $this->assertCount(5, $changes);
        
        foreach ($changes as $change) {
            $this->assertTrue($change['cover_missing'] || $change['ebook_missing'] || $change['metadata_incomplete']);
        }
    }

    /** @test */
    public function it_uses_offset_pagination_in_missing_phase()
    {
        // Create 100 books with cover_missing (simpler, no file dependencies)
        for ($i = 0; $i < 100; $i++) {
            UserBook::create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'uuid' => \Illuminate\Support\Str::uuid(),
                'title' => 'Missing Book ' . $i,
                'last_modified' => now()->subYear()->timestamp,
                'cover_missing' => true, // All with cover missing
                'ebook_missing' => false,
                'metadata_incomplete' => false,
                'cover_url' => null, // Truly missing
            ]);
        }

        $seenBookIds = [];
        $cursor = base64_encode(json_encode([
            'timestamp' => now()->timestamp,
            'last_id' => 0,
            'phase' => 'missing',
            'missing_offset' => 0
        ]));

        // Fetch in batches of 20
        for ($batch = 0; $batch < 5; $batch++) {
            $response = $this->withHeaders([
                'Authorization' => 'Bearer ' . $this->token,
                'Accept' => 'application/json',
            ])->postJson('/api/sync/pull', [
                'cursor' => $cursor,
                'limit' => 20,
                'library_id' => $this->library->id,
                'calibre_library_uuid' => $this->library->calibre_library_id,
            ]);

            $response->assertStatus(200);
            $changes = $response->json('changes');
            
            if (count($changes) == 0) {
                break; // No more missing books
            }

            // Check no duplicates
            foreach ($changes as $change) {
                $bookId = $change['item']['uuid'] ?? $change['item']['id'] ?? null;
                $this->assertNotNull($bookId, 'Book ID/UUID must be present');
                $this->assertNotContains($bookId, $seenBookIds, "Book $bookId returned twice!");
                $seenBookIds[] = $bookId;
            }

            $cursor = $response->json('new_cursor');
            if (!$response->json('has_more')) {
                break;
            }
        }

        // Should have processed all 100 books
        $this->assertEquals(100, count($seenBookIds));
    }

    /** @test */
    public function it_completes_missing_phase_when_no_more_books()
    {
        // Create 10 books with missing flags (no cover to prevent self-healing)
        for ($i = 0; $i < 10; $i++) {
            UserBook::create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'uuid' => \Illuminate\Support\Str::uuid(),
                'title' => 'Missing Book ' . $i,
                'cover_missing' => true,
                'cover_url' => null,
                'last_modified' => now()->subYear()->timestamp,
            ]);
        }

        $cursor = base64_encode(json_encode([
            'timestamp' => now()->timestamp,
            'last_id' => 0,
            'phase' => 'missing',
            'missing_offset' => 0
        ]));

        // Request with high limit (gets all in one go)
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
        $this->assertCount(10, $response->json('changes'));
        $this->assertFalse($response->json('has_more'));
        $this->assertNull($response->json('new_cursor'));
    }

    /** @test */
    public function it_handles_mixed_missing_flags()
    {
        // Books with different missing combinations (no files/cover to prevent self-healing)
        UserBook::create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'uuid' => \Illuminate\Support\Str::uuid(),
            
            'title' => 'Cover Missing',
            'cover_missing' => true,
            'ebook_missing' => false,
            'metadata_incomplete' => false,
            'cover_url' => null,
            'last_modified' => now()->subYear()->timestamp,
        ]);

        UserBook::create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'uuid' => \Illuminate\Support\Str::uuid(),
            'title' => 'Cover and Metadata Missing',
            'cover_missing' => true,
            'ebook_missing' => false,
            'metadata_incomplete' => true,
            'cover_url' => null,
            'last_modified' => now()->subYear()->timestamp,
        ]);

        UserBook::create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'uuid' => \Illuminate\Support\Str::uuid(),
            
            'title' => 'Metadata Missing',
            'cover_missing' => false,
            'ebook_missing' => false,
            'metadata_incomplete' => true,
            'last_modified' => now()->subYear()->timestamp,
        ]);

        UserBook::create([
            'user_id' => $this->user->id,
            'library_id' => $this->library->id,
            'uuid' => \Illuminate\Support\Str::uuid(),
            'title' => 'All Missing',
            'cover_missing' => true,
            'ebook_missing' => false,
            'metadata_incomplete' => true,
            'cover_url' => null,
            'last_modified' => now()->subYear()->timestamp,
        ]);

        $cursor = base64_encode(json_encode([
            'timestamp' => now()->timestamp,
            'last_id' => 0,
            'phase' => 'missing',
            'missing_offset' => 0
        ]));

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
        
        // Should return all 4 books
        $this->assertCount(4, $changes);
        
        $titles = array_column(array_column($changes, 'item'), 'title');
        $this->assertContains('Cover Missing', $titles);
        $this->assertContains('Cover and Metadata Missing', $titles);
        $this->assertContains('Metadata Missing', $titles);
        $this->assertContains('All Missing', $titles);
    }

    /** @test */
    public function it_uses_smaller_batch_size_for_missing_phase()
    {
        // Create 100 books with missing (no cover to prevent self-healing)
        for ($i = 0; $i < 100; $i++) {
            UserBook::create([
                'user_id' => $this->user->id,
                'library_id' => $this->library->id,
                'uuid' => \Illuminate\Support\Str::uuid(),
                'title' => 'Missing Book ' . $i,
                'cover_missing' => true,
                'cover_url' => null,
                'last_modified' => now()->subYear()->timestamp,
            ]);
        }

        $cursor = base64_encode(json_encode([
            'timestamp' => now()->timestamp,
            'last_id' => 0,
            'phase' => 'missing',
            'missing_offset' => 0
        ]));

        // Request with high limit, but missing phase should cap at 50
        $response = $this->withHeaders([
            'Authorization' => 'Bearer ' . $this->token,
            'Accept' => 'application/json',
        ])->postJson('/api/sync/pull', [
            'cursor' => $cursor,
            'limit' => 200, // High limit
            'library_id' => $this->library->id,
            'calibre_library_uuid' => $this->library->calibre_library_id,
        ]);

        $response->assertStatus(200);
        $changes = $response->json('changes');
        
        // Should return max 50 (not 200)
        $this->assertLessThanOrEqual(50, count($changes));
        $this->assertTrue($response->json('has_more'));
    }
}
