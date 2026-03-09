<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\SyncMapping;
use App\Models\User;
use App\Models\UserBook;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Foundation\Http\Middleware\VerifyCsrfToken;
use Illuminate\Support\Facades\Schema;
use Illuminate\Support\Str;
use Tests\TestCase;

class TombstoneAdminTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();
    }

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
            'uuid' => Str::uuid()->toString(),
        ]);
        $book->deleted_at = now()->subDays(5);
        $book->save();
        if (Schema::hasTable('sync_mappings')) {
            SyncMapping::create([
                'user_id' => $admin->id,
                'library_id' => $library->id,
                'entity_type' => 'books',
                'client_key' => 'calibre:' . $library->calibre_library_id . ':500',
                'server_id' => 500,
            ]);
        }

        session()->start();
        $response = $this->actingAs($admin)
            ->from('/superadmin/library/' . $library->id . '/tombstones')
            ->post('/superadmin/library/tombstones/cleanup', [
                'older_than_days' => 1,
                'library_id' => $library->id,
                '_token' => session()->token(),
            ]);

        $response->assertStatus(302);
        $this->assertDatabaseMissing('books', ['id' => 500, 'library_id' => $library->id]);
        if (Schema::hasTable('sync_mappings')) {
            $this->assertDatabaseMissing('sync_mappings', [
                'library_id' => $library->id,
                'entity_type' => 'books',
                'server_id' => 500,
            ]);
        }
    }

    public function test_resolve_tombstones_creates_sync_mapping(): void
    {
        $this->withoutMiddleware(VerifyCsrfToken::class);
        $admin = User::factory()->create(['is_superadmin' => true]);
        $library = Library::factory()->create(['user_id' => $admin->id]);

        session()->start();
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
                '_token' => session()->token(),
            ]);

        $response->assertStatus(302);
        if (Schema::hasTable('sync_mappings')) {
            $this->assertDatabaseHas('sync_mappings', [
                'user_id' => $admin->id,
                'library_id' => $library->id,
                'entity_type' => 'books',
                'client_key' => 'calibre:' . $library->calibre_library_id . ':900',
                'server_id' => 900,
            ]);
        } else {
            $response->assertSessionHas('status', 'Mappings disabled: sync_mappings table removed');
        }
    }
}
