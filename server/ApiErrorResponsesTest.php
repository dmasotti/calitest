<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Hash;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class ApiErrorResponsesTest extends TestCase
{
    use RefreshDatabase;

    public function test_login_rejects_invalid_credentials(): void
    {
        $user = User::factory()->create([
            'password' => Hash::make('secret123'),
        ]);

        $response = $this->postJson('/api/auth/login', [
            'email' => $user->email,
            'password' => 'wrong-password',
        ]);

        $response->assertStatus(422);
        $response->assertJsonValidationErrors(['email']);
        $this->assertSame('The provided credentials are incorrect.', $response->json('errors.email.0'));
    }

    public function test_api_errors_return_json_without_accept_header(): void
    {
        $user = User::factory()->create([
            'password' => Hash::make('secret123'),
        ]);

        $response = $this->post('/api/auth/login', [
            'email' => $user->email,
            'password' => 'wrong-password',
        ]);

        $response->assertStatus(422);
        $this->assertStringContainsString('application/json', (string) $response->headers->get('Content-Type'));
        $response->assertJsonValidationErrors(['email']);
    }

    public function test_sync_requires_authentication(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id);

        $response->assertStatus(401);
        $this->assertSame('Unauthenticated', $response->json('message'));
    }

    public function test_library_access_denied_for_other_user(): void
    {
        $user = User::factory()->create();
        $otherUser = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $otherUser->id]);

        Sanctum::actingAs($user);

        $response = $this->getJson('/api/libraries/uuid/' . $library->calibre_library_id);

        $response->assertStatus(404);
        $this->assertSame('Library not found', $response->json('error'));
    }

    public function test_item_access_denied_for_other_user(): void
    {
        $user = User::factory()->create();
        $otherUser = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $otherUser->id]);
        $book = UserBook::factory()->create([
            'user_id' => $otherUser->id,
            'library_id' => $library->id,
        ]);

        Sanctum::actingAs($user);

        $response = $this->getJson('/api/items/uuid/' . $book->uuid . '?calibre_library_uuid=' . $library->calibre_library_id);

        $response->assertStatus(404);
        $this->assertSame('Library not found or access denied', $response->json('error'));
    }

    public function test_sync_access_denied_for_other_user(): void
    {
        $user = User::factory()->create();
        $otherUser = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $otherUser->id]);

        Sanctum::actingAs($user);

        $response = $this->getJson('/api/sync?calibre_library_uuid=' . $library->calibre_library_id);

        $response->assertStatus(404);
        $this->assertSame('Library not found or access denied', $response->json('error'));
    }
}
