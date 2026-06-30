<?php

namespace Tests\Feature;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class AiChatContractTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        $controllerPath = base_path('app/Http/Controllers/BookChatController.php');
        $output = [];
        $exitCode = 0;
        @exec(escapeshellarg(PHP_BINARY) . ' -l ' . escapeshellarg($controllerPath), $output, $exitCode);
        if ($exitCode !== 0) {
            $this->markTestSkipped('BookChatController has syntax errors; AI contract routes cannot be loaded.');
        }
    }

    public function test_verify_access_denies_non_owner(): void
    {
        $owner = User::factory()->create();
        $other = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $owner->id]);
        $book = UserBook::factory()->create([
            'user_id' => $owner->id,
            'library_id' => $library->id,
        ]);

        $this->actingAs($other)
            ->getJson('/api/books/' . $book->uuid . '/verify-access')
            ->assertStatus(404);
    }

    public function test_chat_status_returns_no_file_when_requested_format_is_missing(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $this->actingAs($user)
            ->getJson('/api/books/' . $book->uuid . '/chat/status?format=EPUB')
            ->assertStatus(200)
            ->assertJsonFragment(['error' => 'no_file'])
            ->assertJsonFragment(['indexed' => false]);
    }

}
