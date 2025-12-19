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

class SubscriptionApiTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        
        // Ensure config is loaded
        Config::set('subscription.tiers', [
            'free' => [
                'name' => 'Free',
                'max_libraries' => 1,
                'max_books' => 50,
                'max_storage_mb' => 500,
                'features' => ['sync', 'covers', 'community_support'],
                'pricing' => ['monthly' => 0, 'yearly' => 0],
            ],
            'basic' => [
                'name' => 'Basic',
                'max_libraries' => 3,
                'max_books' => 600,
                'max_storage_mb' => 3072,
                'features' => ['sync', 'covers', 'email_support', 'export'],
                'pricing' => ['monthly' => 499, 'yearly' => 4990],
            ],
        ]);
    }

    /**
     * Test GET /api/subscription - Get subscription status
     */
    public function test_get_subscription_status_returns_correct_data(): void
    {
        $user = User::factory()->create([
            'subscription_tier' => 'free',
            'subscription_status' => 'active',
        ]);

        Sanctum::actingAs($user);

        $response = $this->getJson('/api/subscription');

        $response->assertStatus(200)
            ->assertJsonStructure([
                'subscription' => [
                    'tier',
                    'status',
                    'expires_at',
                    'trial_ends_at',
                    'is_active',
                ],
                'limits' => [
                    'max_libraries',
                    'max_books',
                    'max_storage_mb',
                ],
                'usage' => [
                    'libraries',
                    'books',
                    'storage_mb',
                    'storage_bytes',
                ],
                'usage_percentages' => [
                    'libraries',
                    'books',
                    'storage',
                ],
                'features',
            ]);

        $response->assertJson([
            'subscription' => [
                'tier' => 'free',
                'status' => 'active',
                'is_active' => true,
            ],
            'limits' => [
                'max_libraries' => 1,
                'max_books' => 50,
                'max_storage_mb' => 500,
            ],
        ]);
    }

    /**
     * Test GET /api/subscription - Unauthenticated returns 401
     */
    public function test_get_subscription_status_requires_authentication(): void
    {
        $response = $this->getJson('/api/subscription');

        $response->assertStatus(401);
    }

    /**
     * Test GET /api/subscription - Shows correct usage percentages
     */
    public function test_subscription_status_shows_correct_usage_percentages(): void
    {
        $user = User::factory()->create([
            'subscription_tier' => 'free',
        ]);

        // Create 1 library (max is 1, so 100%)
        Library::factory()->create(['user_id' => $user->id]);
        
        // Create 25 books (max is 50, so 50%)
        UserBook::factory()->count(25)->create(['user_id' => $user->id]);

        Sanctum::actingAs($user);

        $response = $this->getJson('/api/subscription');

        $response->assertStatus(200);
        $data = $response->json();

        $this->assertEquals(100.0, $data['usage_percentages']['libraries']);
        $this->assertEquals(50.0, $data['usage_percentages']['books']);
    }

    /**
     * Test GET /api/subscription/pricing - Returns all tiers
     */
    public function test_get_pricing_returns_all_tiers(): void
    {
        $user = User::factory()->create();
        Sanctum::actingAs($user);

        $response = $this->getJson('/api/subscription/pricing');

        $response->assertStatus(200)
            ->assertJsonStructure([
                'tiers' => [
                    'free' => [
                        'name',
                        'limits',
                        'features',
                        'pricing',
                    ],
                    'basic' => [
                        'name',
                        'limits',
                        'features',
                        'pricing',
                    ],
                ],
                'trial_days',
            ]);

        $data = $response->json();
        $this->assertArrayHasKey('free', $data['tiers']);
        $this->assertArrayHasKey('basic', $data['tiers']);
        $this->assertEquals('Free', $data['tiers']['free']['name']);
        $this->assertEquals('Basic', $data['tiers']['basic']['name']);
    }

    /**
     * Test GET /api/subscription/pricing - Pricing formatted correctly
     */
    public function test_pricing_formatted_correctly(): void
    {
        $user = User::factory()->create();
        Sanctum::actingAs($user);

        $response = $this->getJson('/api/subscription/pricing');

        $response->assertStatus(200);
        $data = $response->json();

        // Check free tier pricing
        $this->assertEquals(0, $data['tiers']['free']['pricing']['monthly']['amount']);
        $this->assertEquals('€0.00', $data['tiers']['free']['pricing']['monthly']['formatted']);

        // Check basic tier pricing
        $this->assertEquals(499, $data['tiers']['basic']['pricing']['monthly']['amount']);
        $this->assertEquals('€4.99', $data['tiers']['basic']['pricing']['monthly']['formatted']);
        $this->assertEquals(4990, $data['tiers']['basic']['pricing']['yearly']['amount']);
        $this->assertEquals('€49.90', $data['tiers']['basic']['pricing']['yearly']['formatted']);
    }

    /**
     * Test subscription status with expired subscription
     */
    public function test_subscription_status_shows_expired(): void
    {
        $user = User::factory()->create([
            'subscription_tier' => 'basic',
            'subscription_status' => 'expired',
            'subscription_expires_at' => now()->subDay(),
        ]);

        Sanctum::actingAs($user);

        $response = $this->getJson('/api/subscription');

        $response->assertStatus(200);
        $data = $response->json();

        $this->assertEquals('expired', $data['subscription']['status']);
        $this->assertFalse($data['subscription']['is_active']);
    }

    /**
     * Test subscription status with active subscription
     */
    public function test_subscription_status_shows_active(): void
    {
        $user = User::factory()->create([
            'subscription_tier' => 'basic',
            'subscription_status' => 'active',
            'subscription_expires_at' => now()->addMonth(),
        ]);

        Sanctum::actingAs($user);

        $response = $this->getJson('/api/subscription');

        $response->assertStatus(200);
        $data = $response->json();

        $this->assertEquals('active', $data['subscription']['status']);
        $this->assertTrue($data['subscription']['is_active']);
    }
}
