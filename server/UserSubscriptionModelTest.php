<?php

namespace Tests\Server;

use App\Models\User;
use App\Models\Library;
use App\Models\UserBook;
use App\Models\BookFile;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Config;
use Tests\TestCase;

class UserSubscriptionModelTest extends TestCase
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
                'features' => ['sync', 'covers'],
            ],
            'basic' => [
                'max_libraries' => 3,
                'max_books' => 600,
                'max_storage_mb' => 3072,
                'features' => ['sync', 'covers', 'export'],
            ],
        ]);
    }

    /**
     * Test getSubscriptionLimits() returns correct limits
     */
    public function test_get_subscription_limits_returns_correct_limits(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        $limits = $user->getSubscriptionLimits();
        
        $this->assertEquals(1, $limits['max_libraries']);
        $this->assertEquals(50, $limits['max_books']);
        $this->assertEquals(500, $limits['max_storage_mb']);
    }

    /**
     * Test canCreateLibrary() returns true when under limit
     */
    public function test_can_create_library_when_under_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        $this->assertTrue($user->canCreateLibrary());
    }

    /**
     * Test canCreateLibrary() returns false when at limit
     */
    public function test_cannot_create_library_when_at_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        // Create max libraries (1 for free tier)
        Library::factory()->create(['user_id' => $user->id]);
        
        $this->assertFalse($user->canCreateLibrary());
    }

    /**
     * Test canAddBook() returns true when under limit
     */
    public function test_can_add_book_when_under_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        // Create 25 books (under limit of 50)
        UserBook::factory()->count(25)->create(['user_id' => $user->id]);
        
        $this->assertTrue($user->canAddBook());
    }

    /**
     * Test canAddBook() returns false when at limit
     */
    public function test_cannot_add_book_when_at_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        // Create max books (50 for free tier)
        UserBook::factory()->count(50)->create(['user_id' => $user->id]);
        
        $this->assertFalse($user->canAddBook());
    }

    /**
     * Test getStorageUsedBytes() calculates correctly
     */
    public function test_get_storage_used_bytes_calculates_correctly(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        // Create a user book
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        // Create book file with size
        $bookFile = BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 5242880, // 5 MB
            'is_uploaded' => true,
        ]);
        
        $storageBytes = $user->getStorageUsedBytes();
        
        $this->assertEquals(5242880, $storageBytes);
    }

    /**
     * Test getStorageUsedMB() returns correct value
     */
    public function test_get_storage_used_mb_returns_correct_value(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        // 5 MB
        BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 5242880,
            'is_uploaded' => true,
        ]);
        
        $storageMB = $user->getStorageUsedMB();
        
        $this->assertEquals(5.0, $storageMB);
    }

    /**
     * Test canAddStorage() returns true when under limit
     */
    public function test_can_add_storage_when_under_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        // Free tier has 500 MB limit, try to add 100 MB
        $this->assertTrue($user->canAddStorage(100));
    }

    /**
     * Test canAddStorage() returns false when would exceed limit
     */
    public function test_cannot_add_storage_when_would_exceed_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        // Free tier has 500 MB limit, try to add 600 MB
        $this->assertFalse($user->canAddStorage(600));
    }

    /**
     * Test canAddStorage() considers existing storage
     */
    public function test_can_add_storage_considers_existing_storage(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        // Add 400 MB of storage
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 400 * 1024 * 1024, // 400 MB
            'is_uploaded' => true,
        ]);
        
        // Can add 100 MB (total would be 500 MB, at limit)
        $this->assertTrue($user->canAddStorage(100));
        
        // Cannot add 101 MB (total would be 501 MB, over limit)
        $this->assertFalse($user->canAddStorage(101));
    }

    /**
     * Test hasFeature() returns true for available feature
     */
    public function test_has_feature_returns_true_for_available_feature(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        $this->assertTrue($user->hasFeature('sync'));
        $this->assertTrue($user->hasFeature('covers'));
    }

    /**
     * Test hasFeature() returns false for unavailable feature
     */
    public function test_has_feature_returns_false_for_unavailable_feature(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        $this->assertFalse($user->hasFeature('export'));
    }

    /**
     * Test isSubscriptionActive() returns true for active free tier
     */
    public function test_is_subscription_active_returns_true_for_free_tier(): void
    {
        $user = User::factory()->create([
            'subscription_tier' => 'free',
            'subscription_status' => 'active',
        ]);
        
        $this->assertTrue($user->isSubscriptionActive());
    }

    /**
     * Test isSubscriptionActive() returns false for expired subscription
     */
    public function test_is_subscription_active_returns_false_for_expired(): void
    {
        $user = User::factory()->create([
            'subscription_tier' => 'basic',
            'subscription_status' => 'expired',
            'subscription_expires_at' => now()->subDay(),
        ]);
        
        $this->assertFalse($user->isSubscriptionActive());
    }

    /**
     * Test isSubscriptionActive() returns false for cancelled subscription
     */
    public function test_is_subscription_active_returns_false_for_cancelled(): void
    {
        $user = User::factory()->create([
            'subscription_tier' => 'basic',
            'subscription_status' => 'cancelled',
        ]);
        
        $this->assertFalse($user->isSubscriptionActive());
    }

    /**
     * Test getStorageUsedBytes() only counts uploaded files
     */
    public function test_storage_only_counts_uploaded_files(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        
        $userBook = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);
        
        // Create uploaded file
        BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 5242880,
            'is_uploaded' => true,
        ]);
        
        // Create non-uploaded file (should not count)
        BookFile::factory()->create([
            'book_id' => $userBook->id,
            'uncompressed_size' => 10485760,
            'is_uploaded' => false,
        ]);
        
        $storageBytes = $user->getStorageUsedBytes();
        
        // Should only count the uploaded file (5 MB)
        $this->assertEquals(5242880, $storageBytes);
    }
}
