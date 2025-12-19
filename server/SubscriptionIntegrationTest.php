<?php

namespace Tests\Server;

use App\Models\User;
use App\Models\Library;
use App\Models\UserBook;
use App\Models\BookFile;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Config;
use Tests\TestCase;
use Laravel\Sanctum\Sanctum;

/**
 * Test di integrazione completa per subscription e limiti
 * Verifica il flusso completo end-to-end
 */
class SubscriptionIntegrationTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        
        Config::set('subscription.tiers', [
            'free' => [
                'max_libraries' => 1,
                'max_books' => 50,
                'max_storage_mb' => 500,
            ],
            'basic' => [
                'max_libraries' => 3,
                'max_books' => 600,
                'max_storage_mb' => 3072,
            ],
        ]);
    }

    /**
     * Test completo: utente free raggiunge tutti i limiti
     */
    public function test_free_user_reaches_all_limits(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        Sanctum::actingAs($user);

        // 1. Create library (should succeed)
        $libraryResponse = $this->postJson('/api/libraries', [
            'name' => 'My Library',
            'calibre_library_id' => 'test-uuid-1',
        ]);
        $libraryResponse->assertStatus(201);
        $libraryId = $libraryResponse->json('id');

        // 2. Try to create second library (should fail)
        $secondLibraryResponse = $this->postJson('/api/libraries', [
            'name' => 'Second Library',
            'calibre_library_id' => 'test-uuid-2',
        ]);
        $secondLibraryResponse->assertStatus(403);

        // 3. Create books up to limit
        $library = Library::find($libraryId);
        UserBook::factory()->count(50)->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        // 4. Try to sync new book (should fail)
        $syncResponse = $this->postJson("/api/sync?library_id={$libraryId}", [
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'calibre_book_id' => 999,
                        'title' => 'New Book',
                        'authors' => ['Test Author'],
                    ],
                    'idempotency_key' => 'test-key-1',
                ],
            ],
            'client_cursor' => null,
        ]);
        $syncResponse->assertStatus(403);

        // 5. Check subscription status shows limits reached
        $statusResponse = $this->getJson('/api/subscription');
        $statusResponse->assertStatus(200);
        $data = $statusResponse->json();

        $this->assertEquals(100.0, $data['usage_percentages']['libraries']);
        $this->assertEquals(100.0, $data['usage_percentages']['books']);
    }

    /**
     * Test completo: upgrade da free a basic sblocca limiti
     */
    public function test_upgrade_unlocks_limits(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        Sanctum::actingAs($user);

        // Create max libraries for free tier
        Library::factory()->create(['user_id' => $user->id]);

        // Try to create second library (should fail)
        $response = $this->postJson('/api/libraries', [
            'name' => 'Second Library',
            'calibre_library_id' => 'test-uuid-2',
        ]);
        $response->assertStatus(403);

        // Upgrade to basic
        $user->update([
            'subscription_tier' => 'basic',
            'subscription_status' => 'active',
            'subscription_expires_at' => now()->addMonth(),
        ]);

        // Now should be able to create more libraries
        $response = $this->postJson('/api/libraries', [
            'name' => 'Second Library',
            'calibre_library_id' => 'test-uuid-2',
        ]);
        $response->assertStatus(201);

        // Should be able to create up to 3 libraries total
        $response = $this->postJson('/api/libraries', [
            'name' => 'Third Library',
            'calibre_library_id' => 'test-uuid-3',
        ]);
        $response->assertStatus(201);
    }

    /**
     * Test completo: storage limit enforcement during sync
     */
    public function test_storage_limit_enforcement_during_sync(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        // Add 450 MB of storage
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 450 * 1024 * 1024, // 450 MB
            'is_uploaded' => true,
        ]);
        
        Sanctum::actingAs($user);

        // Try to sync book with 60 MB file (would exceed 500 MB limit)
        $response = $this->postJson("/api/sync?library_id={$library->id}", [
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'calibre_book_id' => 1,
                        'title' => 'Large Book',
                        'authors' => ['Test Author'],
                        'files' => [
                            [
                                'format' => 'EPUB',
                                'uncompressed_size' => 60 * 1024 * 1024, // 60 MB
                            ],
                        ],
                    ],
                    'idempotency_key' => 'test-key-2',
                ],
            ],
            'client_cursor' => null,
        ]);

        $response->assertStatus(403)
            ->assertJson([
                'error' => 'Limite storage raggiunto',
            ]);

        // Try to sync smaller book (should succeed)
        $response = $this->postJson("/api/sync?library_id={$library->id}", [
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'calibre_book_id' => 2,
                        'title' => 'Small Book',
                        'authors' => ['Test Author'],
                        'files' => [
                            [
                                'format' => 'EPUB',
                                'uncompressed_size' => 40 * 1024 * 1024, // 40 MB (total would be 490 MB)
                            ],
                        ],
                    ],
                    'idempotency_key' => 'test-key-3',
                ],
            ],
            'client_cursor' => null,
        ]);

        // Should not return 403 (limit error)
        $this->assertNotEquals(403, $response->status());
    }

    /**
     * Test completo: subscription status reflects current usage
     */
    public function test_subscription_status_reflects_usage(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        // Create 25 books (50% of limit)
        UserBook::factory()->count(25)->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        // Add 250 MB storage (50% of limit)
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 250 * 1024 * 1024, // 250 MB
            'is_uploaded' => true,
        ]);
        
        Sanctum::actingAs($user);

        $response = $this->getJson('/api/subscription');
        $response->assertStatus(200);
        $data = $response->json();

        $this->assertEquals(100.0, $data['usage_percentages']['libraries']); // 1/1 = 100%
        $this->assertEquals(50.0, $data['usage_percentages']['books']); // 25/50 = 50%
        $this->assertEquals(50.0, $data['usage_percentages']['storage']); // 250/500 = 50%
        $this->assertEquals(25, $data['usage']['books']);
        $this->assertEquals(250.0, $data['usage']['storage_mb']);
    }
}
