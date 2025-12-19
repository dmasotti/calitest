<?php

namespace Tests\Server;

use App\Models\User;
use App\Models\Library;
use App\Models\UserBook;
use App\Models\Device;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Config;
use Tests\TestCase;
use Laravel\Sanctum\Sanctum;

class SyncLimitsTest extends TestCase
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
        ]);
    }

    /**
     * Test POST /api/sync - Blocks when book limit exceeded
     */
    public function test_sync_blocks_when_book_limit_exceeded(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        $library = Library::factory()->create(['user_id' => $user->id]);
        $device = Device::factory()->create(['user_id' => $user->id]);
        
        // Create max books (50 for free tier)
        UserBook::factory()->count(50)->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        Sanctum::actingAs($user);

        $response = $this->postJson('/api/sync?library_id=' . $library->id, [
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

        $response->assertStatus(403)
            ->assertJson([
                'error' => 'Limite libri raggiunto',
                'upgrade_required' => true,
                'current_tier' => 'free',
                'max_books' => 50,
                'current_books' => 50,
            ]);
    }

    /**
     * Test POST /api/sync - Blocks when storage limit exceeded
     */
    public function test_sync_blocks_when_storage_limit_exceeded(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        // Add 450 MB of storage (close to 500 MB limit)
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        \App\Models\BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 450 * 1024 * 1024, // 450 MB
            'is_uploaded' => true,
        ]);
        
        Sanctum::actingAs($user);

        // Try to sync a book with 100 MB file (would exceed 500 MB limit)
        $response = $this->postJson('/api/sync?library_id=' . $library->id, [
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'calibre_book_id' => 999,
                        'title' => 'New Book',
                        'authors' => ['Test Author'],
                        'files' => [
                            [
                                'format' => 'EPUB',
                                'uncompressed_size' => 100 * 1024 * 1024, // 100 MB
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
                'upgrade_required' => true,
                'current_tier' => 'free',
                'max_storage_mb' => 500,
            ]);
    }

    /**
     * Test POST /api/sync - Allows sync when under limits
     */
    public function test_sync_allows_when_under_limits(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        Sanctum::actingAs($user);

        $response = $this->postJson('/api/sync?library_id=' . $library->id, [
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'calibre_book_id' => 1,
                        'title' => 'Test Book',
                        'authors' => ['Test Author'],
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
     * Test POST /api/sync - Dry run does not enforce limits
     */
    public function test_sync_dry_run_does_not_enforce_limits(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        // Create max books
        UserBook::factory()->count(50)->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        Sanctum::actingAs($user);

        // Dry run should not check limits
        $response = $this->postJson('/api/sync?library_id=' . $library->id, [
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'calibre_book_id' => 999,
                        'title' => 'New Book',
                        'authors' => ['Test Author'],
                    ],
                    'idempotency_key' => 'test-key-4',
                ],
            ],
            'client_cursor' => null,
            'options' => ['dry_run' => true],
        ]);

        // Dry run should not return 403
        $this->assertNotEquals(403, $response->status());
    }

    /**
     * Test sync estimates storage correctly from files array
     */
    public function test_sync_estimates_storage_from_files(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        Sanctum::actingAs($user);

        // Try to sync with file that would exceed limit
        $response = $this->postJson('/api/sync?library_id=' . $library->id, [
            'changes' => [
                [
                    'op' => 'create',
                    'item' => [
                        'calibre_book_id' => 1,
                        'title' => 'Test Book',
                        'authors' => ['Test Author'],
                        'files' => [
                            [
                                'format' => 'EPUB',
                                'uncompressed_size' => 600 * 1024 * 1024, // 600 MB (exceeds 500 MB limit)
                            ],
                        ],
                    ],
                    'idempotency_key' => 'test-key-5',
                ],
            ],
            'client_cursor' => null,
        ]);

        $response->assertStatus(403)
            ->assertJson([
                'error' => 'Limite storage raggiunto',
            ]);
    }
}
