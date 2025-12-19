<?php

namespace Tests\Server;

use App\Models\User;
use App\Models\Library;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Config;
use Tests\TestCase;
use Laravel\Sanctum\Sanctum;

class LibraryLimitsTest extends TestCase
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
     * Test POST /api/libraries - Success when under limit
     */
    public function test_create_library_success_when_under_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        Sanctum::actingAs($user);

        $response = $this->postJson('/api/libraries', [
            'name' => 'My Library',
            'calibre_library_id' => 'test-uuid-123',
        ]);

        $response->assertStatus(201)
            ->assertJsonStructure([
                'id',
                'name',
                'calibre_library_id',
            ]);

        $this->assertDatabaseHas('libraries', [
            'user_id' => $user->id,
            'name' => 'My Library',
            'calibre_library_id' => 'test-uuid-123',
        ]);
    }

    /**
     * Test POST /api/libraries - Fails when at limit
     */
    public function test_create_library_fails_when_at_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        // Create max libraries
        Library::factory()->create(['user_id' => $user->id]);
        
        Sanctum::actingAs($user);

        $response = $this->postJson('/api/libraries', [
            'name' => 'Second Library',
            'calibre_library_id' => 'test-uuid-456',
        ]);

        $response->assertStatus(403)
            ->assertJson([
                'error' => 'Limite librerie raggiunto',
                'upgrade_required' => true,
                'current_tier' => 'free',
                'max_libraries' => 1,
            ]);
    }

    /**
     * Test POST /api/libraries - Basic tier can create 3 libraries
     */
    public function test_basic_tier_can_create_three_libraries(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'basic']);
        Sanctum::actingAs($user);

        // Create 3 libraries (max for basic)
        for ($i = 1; $i <= 3; $i++) {
            $response = $this->postJson('/api/libraries', [
                'name' => "Library {$i}",
                'calibre_library_id' => "test-uuid-{$i}",
            ]);

            $response->assertStatus(201);
        }

        // Try to create 4th library - should fail
        $response = $this->postJson('/api/libraries', [
            'name' => 'Library 4',
            'calibre_library_id' => 'test-uuid-4',
        ]);

        $response->assertStatus(403);
    }

    /**
     * Test POST /library (web) - Same limit enforcement
     */
    public function test_web_library_creation_enforces_limits(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        
        // Create max libraries
        Library::factory()->create(['user_id' => $user->id]);
        
        $response = $this->actingAs($user)->post('/library', [
            'name' => 'Second Library',
            'calibre_library_id' => 'test-uuid-789',
        ]);

        $response->assertRedirect('/subscription/upgrade');
        $response->assertSessionHas('error');
    }
}
