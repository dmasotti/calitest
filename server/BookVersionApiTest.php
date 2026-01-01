<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use App\Models\UserBookVersion;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class BookVersionApiTest extends TestCase
{
    use RefreshDatabase;

    public function test_versions_endpoint_includes_trashed_book(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $book->update(['favorite' => true]);
        $book->delete();

        Sanctum::actingAs($user);

        $response = $this->getJson('/api/items/' . $book->id . '/versions?library_id=' . $library->id);
        $response->assertStatus(200);
        $response->assertJsonStructure([
            'book' => ['id', 'client_id', 'library_id'],
            'versions',
        ]);
        $this->assertNotEmpty($response->json('versions'));
    }

    public function test_restore_and_undelete_restores_snapshot_and_undeletes_book(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $book->update(['favorite' => true]);
        $version = UserBookVersion::where('book_id', $book->id)
            ->orderByDesc('created_at')
            ->first();

        $this->assertNotNull($version);

        $book->delete();
        $this->assertSoftDeleted('books', [
            'id' => $book->id,
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        Sanctum::actingAs($user);

        $response = $this->postJson(
            '/api/items/' . $book->id . '/versions/' . $version->id . '/restore-and-undelete?library_id=' . $library->id
        );
        $response->assertStatus(200);
        $response->assertJson([
            'status' => 'restored',
            'undeleted' => true,
        ]);

        $book->refresh();
        $this->assertFalse($book->trashed());
        $this->assertNull($book->status);
        $this->assertFalse((bool) $book->favorite);
    }

    public function test_web_restore_and_undelete_redirects_and_restores(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $book->update(['favorite' => true]);
        $version = UserBookVersion::where('book_id', $book->id)
            ->orderByDesc('created_at')
            ->first();

        $this->assertNotNull($version);

        $book->delete();
        $this->actingAs($user);
        $token = 'test-csrf-token';
        $this->withSession(['_token' => $token]);

        $response = $this->post('/library/' . $library->id . '/book/' . $book->id . '/versions/' . $version->id . '/restore-and-undelete', [
            '_token' => $token,
        ]);
        $response->assertRedirect('/library/' . $library->id . '/book/' . $book->id . '/versions');

        $book->refresh();
        $this->assertFalse($book->trashed());
        $this->assertNull($book->status);
        $this->assertFalse((bool) $book->favorite);
    }
}
