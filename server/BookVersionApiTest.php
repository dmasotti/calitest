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

    private function seedVersionForBook(User $user, Library $library, UserBook $book, array $snapshot = []): UserBookVersion
    {
        return UserBookVersion::create([
            'book_id' => $book->uuid,
            'library_id' => $library->id,
            'user_id' => $user->id,
            'snapshot' => array_merge([
                'user_id' => $user->id,
                'library_id' => $library->id,
                'id' => $book->id,
                'title' => $book->title,
                'favorite' => false,
            ], $snapshot),
        ]);
    }

    public function test_versions_endpoint_includes_trashed_book(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $book->update(['favorite' => true]);
        $this->seedVersionForBook($user, $library, $book);
        $book->delete();

        Sanctum::actingAs($user);

        $response = $this->getJson('/api/items/uuid/' . $book->uuid . '/versions?calibre_library_uuid=' . $library->calibre_library_id);
        $response->assertStatus(200);
        $response->assertJsonStructure([
            'book' => ['id', 'client_id', 'library_id'],
            'versions',
        ]);
        $this->assertNotEmpty($response->json('versions'));
    }

    public function test_versions_endpoint_uuid_includes_trashed_book(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $book->update(['favorite' => true]);
        $this->seedVersionForBook($user, $library, $book);
        $book->delete();

        Sanctum::actingAs($user);

        $response = $this->getJson('/api/items/uuid/' . $book->uuid . '/versions?calibre_library_uuid=' . $library->calibre_library_id);
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
        $version = $this->seedVersionForBook($user, $library, $book, [
            'favorite' => false,
            'status' => null,
        ]);

        $book->delete();
        $this->assertSoftDeleted('books', [
            'id' => $book->id,
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        Sanctum::actingAs($user);

        $response = $this->postJson(
            '/api/items/uuid/' . $book->uuid . '/versions/' . $version->id . '/restore-and-undelete?calibre_library_uuid=' . $library->calibre_library_id
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

    public function test_restore_and_undelete_uuid_restores_snapshot_and_undeletes_book(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $book->update(['favorite' => true]);
        $version = $this->seedVersionForBook($user, $library, $book, [
            'favorite' => false,
            'status' => null,
        ]);

        $book->delete();
        $this->assertSoftDeleted('books', [
            'id' => $book->id,
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        Sanctum::actingAs($user);

        $response = $this->postJson(
            '/api/items/uuid/' . $book->uuid . '/versions/' . $version->id . '/restore-and-undelete?calibre_library_uuid=' . $library->calibre_library_id
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

    public function test_web_restore_and_undelete_returns_not_found_for_trashed_route_binding(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        $book->update(['favorite' => true]);
        $version = $this->seedVersionForBook($user, $library, $book, [
            'favorite' => false,
            'status' => null,
        ]);

        $book->delete();
        $this->actingAs($user);
        $token = 'test-csrf-token';
        $this->withSession(['_token' => $token]);

        $response = $this->post('/library/' . $library->calibre_library_id . '/book/' . $book->uuid . '/versions/' . $version->id . '/restore-and-undelete', [
            '_token' => $token,
        ]);
        $response->assertStatus(404);

        $book->refresh();
        $this->assertTrue($book->trashed());
    }
}
