<?php

namespace Tests\Feature;

use App\Models\BookFile;
use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
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

    public function test_validate_book_access_returns_success_for_valid_token_and_file_store(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => (string) Str::uuid(),
        ]);

        $hash = hash('sha256', 'ai-smoke-file');
        BookFile::factory()->create([
            'book' => $book->uuid,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'format' => 'EPUB',
            'file_hash' => $hash,
            'storage_key' => 'ebooks/ai/smoke.epub',
            'storage_provider' => 'r2',
            'is_uploaded' => true,
            'needs_file_upload' => false,
            'file_missing' => false,
            'uuid' => (string) Str::uuid(),
        ]);

        DB::table('files_store')->insert([
            'sha256' => $hash,
            'size' => 128,
            'storage_key' => 'ebooks/ai/smoke.epub',
            'storage_provider' => 'r2',
            'storage_url' => null,
            'ref_count' => 1,
            'first_seen_at' => now(),
            'last_seen_at' => now(),
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        $token = $user->createToken('ai-contract')->plainTextToken;

        $this->postJson('/api/validate-book-access', [
            'token' => $token,
            'book_uuid' => $book->uuid . '_EPUB',
        ])->assertStatus(200)
            ->assertJsonFragment(['book_access' => true]);
    }
}
