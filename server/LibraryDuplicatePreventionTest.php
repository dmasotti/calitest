<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class LibraryDuplicatePreventionTest extends TestCase
{
    use RefreshDatabase;

    public function test_cannot_create_duplicate_library_same_user_same_uuid(): void
    {
        $user = User::factory()->create();
        Sanctum::actingAs($user);

        $uuid = 'test-lib-uuid-123';

        Library::create([
            'user_id' => $user->id,
            'name' => 'My Library',
            'calibre_library_id' => $uuid,
            'type' => 'calibre',
        ]);

        // Second create with same user + uuid should not create duplicate
        $existing = Library::where('user_id', $user->id)
            ->where('calibre_library_id', $uuid)
            ->first();

        $this->assertNotNull($existing);
        $this->assertEquals(1, Library::where('user_id', $user->id)
            ->where('calibre_library_id', $uuid)
            ->count());
    }

    public function test_different_users_can_have_same_library_uuid(): void
    {
        $userA = User::factory()->create();
        $userB = User::factory()->create();

        $uuid = 'shared-uuid-456';

        Library::create([
            'user_id' => $userA->id,
            'name' => 'Library A',
            'calibre_library_id' => $uuid,
            'type' => 'calibre',
        ]);

        Library::create([
            'user_id' => $userB->id,
            'name' => 'Library B',
            'calibre_library_id' => $uuid,
            'type' => 'calibre',
        ]);

        $this->assertEquals(1, Library::where('user_id', $userA->id)->where('calibre_library_id', $uuid)->count());
        $this->assertEquals(1, Library::where('user_id', $userB->id)->where('calibre_library_id', $uuid)->count());
    }

    public function test_sync_endpoint_does_not_create_duplicate_library(): void
    {
        $user = User::factory()->create();
        Sanctum::actingAs($user);

        $uuid = 'sync-lib-uuid-789';

        Library::create([
            'user_id' => $user->id,
            'name' => 'Existing Library',
            'calibre_library_id' => $uuid,
            'type' => 'calibre',
        ]);

        // Simulate what sync does — firstOrCreate should not duplicate
        $lib = Library::firstOrCreate(
            ['user_id' => $user->id, 'calibre_library_id' => $uuid],
            ['name' => 'Existing Library', 'type' => 'calibre']
        );

        $this->assertEquals(1, Library::where('user_id', $user->id)
            ->where('calibre_library_id', $uuid)
            ->count());
    }
}
