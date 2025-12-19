<?php

namespace Tests\Server;

use App\Models\User;
use App\Models\Library;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Config;
use Tests\TestCase;
use Laravel\Sanctum\Sanctum;

class SubscriptionLimitsMiddlewareTest extends TestCase
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
     * Test middleware allows library creation when under limit
     */
    public function test_middleware_allows_library_creation_when_under_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        Sanctum::actingAs($user);

        $response = $this->postJson('/api/libraries', [
            'name' => 'Test Library',
            'calibre_library_id' => 'test-uuid-123',
        ]);

        $response->assertStatus(201);
        $this->assertDatabaseHas('libraries', [
            'user_id' => $user->id,
            'name' => 'Test Library',
        ]);
    }

    /**
     * Test middleware blocks library creation when at limit
     */
    public function test_middleware_blocks_library_creation_when_at_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        // Create max libraries (1 for free tier)
        Library::factory()->create(['user_id' => $user->id]);
        
        Sanctum::actingAs($user);

        $response = $this->postJson('/api/libraries', [
            'name' => 'Second Library',
            'calibre_library_id' => 'test-uuid-456',
        ]);

        $response->assertStatus(403)
            ->assertJson([
                'error' => 'Limite librerie raggiunto (1). Upgrade richiesto.',
                'upgrade_required' => true,
                'current_tier' => 'free',
                'limit' => 1,
                'resource' => 'libraries',
            ]);
    }

    /**
     * Test middleware allows superadmin to bypass limits
     */
    public function test_middleware_allows_superadmin_to_bypass_limits(): void
    {
        $user = User::factory()->create([
            'subscription_tier' => 'free',
            'is_superadmin' => true,
        ]);
        
        // Create max libraries
        Library::factory()->create(['user_id' => $user->id]);
        
        Sanctum::actingAs($user);

        // Superadmin should be able to create more libraries
        $response = $this->postJson('/api/libraries', [
            'name' => 'Superadmin Library',
            'calibre_library_id' => 'test-uuid-789',
        ]);

        $response->assertStatus(201);
    }

    /**
     * Test middleware downgrades expired subscription to free
     */
    public function test_middleware_downgrades_expired_subscription(): void
    {
        $user = User::factory()->create([
            'subscription_tier' => 'basic',
            'subscription_status' => 'expired',
            'subscription_expires_at' => now()->subDay(),
        ]);
        
        Sanctum::actingAs($user);

        // Make any request to trigger middleware
        $this->getJson('/api/subscription');

        $user->refresh();
        
        $this->assertEquals('free', $user->subscription_tier);
        $this->assertEquals('expired', $user->subscription_status);
    }

    /**
     * Test middleware does not downgrade active subscription
     */
    public function test_middleware_does_not_downgrade_active_subscription(): void
    {
        $user = User::factory()->create([
            'subscription_tier' => 'basic',
            'subscription_status' => 'active',
            'subscription_expires_at' => now()->addMonth(),
        ]);
        
        Sanctum::actingAs($user);

        $this->getJson('/api/subscription');

        $user->refresh();
        
        $this->assertEquals('basic', $user->subscription_tier);
        $this->assertEquals('active', $user->subscription_status);
    }
}
