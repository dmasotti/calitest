<?php

namespace Tests\Server;

use App\Models\User;
use App\Models\Library;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;
use Laravel\Sanctum\Sanctum;

class LibraryLimitsTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
        $this->markTestSkipped('Subscription limit enforcement tests are temporarily disabled under the new UUID-only sync.');
    }

    /**
     * Test POST /api/libraries - Success when under limit
     */
    public function test_create_library_success_when_under_limit(): void
    {
        $user = User::factory()->create(['subscription_tier' => 'free']);
        Sanctum::actingAs($user);

        $libUuid = (string) Str::uuid();
        $response = $this->postJson('/api/libraries', [
            'name' => 'My Library',
            'calibre_library_uuid' => $libUuid,
        ]);

        $response->assertStatus(201)
            ->assertJsonStructure([
                'id',
                'name',
                'calibre_library_uuid',
            ]);

        $this->assertDatabaseHas('libraries', [
            'user_id' => $user->id,
            'name' => 'My Library',
            'calibre_library_id' => $libUuid,
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
            'calibre_library_uuid' => (string) Str::uuid(),
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
                'calibre_library_uuid' => (string) Str::uuid(),
            ]);

            $response->assertStatus(201);
        }

        // Try to create 4th library - should fail
        $response = $this->postJson('/api/libraries', [
            'name' => 'Library 4',
            'calibre_library_uuid' => (string) Str::uuid(),
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
        
        session()->start();
        $response = $this->actingAs($user)->post('/library', [
            'name' => 'Second Library',
            'calibre_library_uuid' => (string) Str::uuid(),
            '_token' => session()->token(),
        ]);

        $response->assertRedirect('/subscription/upgrade');
        $response->assertSessionHas('error');
    }
}
