<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class UuidWebRoutesTest extends TestCase
{
    use RefreshDatabase;

    public function test_library_and_book_routes_accept_uuid_only(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
        ]);
        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
        ]);

        Sanctum::actingAs($user);

        $this->get('/library/' . $library->calibre_library_id)->assertStatus(200);
        $this->get('/library/' . $library->id)->assertStatus(404);

        $this->get('/library/' . $library->calibre_library_id . '/book/' . $book->uuid)->assertStatus(200);
        $this->get('/library/' . $library->calibre_library_id . '/book/' . $book->id)->assertStatus(404);
    }
}
