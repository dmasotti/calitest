<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\SyncMapping;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Foundation\Http\Middleware\VerifyCsrfToken;
use Tests\TestCase;

class TombstoneAdminTest extends TestCase
{
    use RefreshDatabase;

    public function test_cleanup_tombstones_removes_records_and_mappings(): void
    {
        $this->withoutMiddleware(VerifyCsrfToken::class);
        $admin = User::factory()->create(['is_superadmin' => true]);
        $library = Library::factory()->create(['user_id' => $admin->id]);

        $book = UserBook::create([
            'user_id' => $admin->id,
            'library_id' => $library->id,
            'id' => 500,
            'title' => 'Deleted Book',
            'last_modified' => now()->subDays(10),
        ]);
        $book->deleted_at = now()->subDays(5);
        $book->save();

        SyncMapping::create([
            'user_id' => $admin->id,
            'library_id' => $library->id,
            'entity_type' => 'books',
            'client_key' => 'calibre:' . $library->calibre_library_id . ':500',
            'server_id' => $book->id,
            'uuid' => null,
        ]);

        $response = $this->actingAs($admin)
            ->from('/superadmin/library/' . $library->id . '/tombstones')
            ->post('/superadmin/library/tombstones/cleanup', [
                'older_than_days' => 1,
                'library_id' => $library->id,
            ]);

        $response->assertStatus(302);
        $this->assertDatabaseMissing('books', ['id' => 500, 'library_id' => $library->id]);
        $this->assertDatabaseMissing('sync_mappings', ['server_id' => 500, 'entity_type' => 'books']);
    }

    public function test_resolve_tombstones_creates_sync_mapping(): void
    {
        $this->withoutMiddleware(VerifyCsrfToken::class);
        $admin = User::factory()->create(['is_superadmin' => true]);
        $library = Library::factory()->create(['user_id' => $admin->id]);

        $response = $this->actingAs($admin)
            ->from('/superadmin/library/' . $library->id . '/tombstones')
            ->post('/superadmin/library/tombstones/resolve', [
                'library_id' => $library->id,
                'mappings' => [
                    [
                        'client_key' => 'calibre:' . $library->calibre_library_id . ':900',
                        'server_id' => 900,
                        'entity_type' => 'books',
                    ],
                ],
            ]);

        $response->assertStatus(302);
        $this->assertDatabaseHas('sync_mappings', [
            'user_id' => $admin->id,
            'library_id' => $library->id,
            'entity_type' => 'books',
            'client_key' => 'calibre:' . $library->calibre_library_id . ':900',
            'server_id' => 900,
        ]);
    }
}
