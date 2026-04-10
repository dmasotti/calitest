<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\DB;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncV5LibraryHashEndpointTest extends TestCase
{
    use RefreshDatabase;

    protected function setUp(): void
    {
        parent::setUp();

        if (DB::getDriverName() === 'sqlite') {
            $this->markTestSkipped('Library hash endpoint fallback/cache integration is validated on MySQL/PostgreSQL.');
        }
    }

    private function actingUserWithLibrary(): array
    {
        $user = User::factory()->create();
        $library = Library::factory()->create([
            'user_id' => $user->id,
            'name' => 'Library Hash Test',
        ]);
        Sanctum::actingAs($user);

        return [$user, $library];
    }

    public function test_library_hash_requires_authentication(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);

        $response->assertStatus(401);
    }

    public function test_library_hash_requires_library_id(): void
    {
        $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/library-hash');

        $response->assertStatus(400)
            ->assertJson(['error' => 'library_id or calibre_library_uuid required']);
    }

    public function test_library_hash_returns_404_when_library_not_found(): void
    {
        $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=999999');

        $response->assertStatus(404)
            ->assertJson(['error' => 'Library not found']);
    }

    public function test_library_hash_denies_other_user_library(): void
    {
        $this->actingUserWithLibrary();

        $otherUser = User::factory()->create();
        $otherLibrary = Library::factory()->create(['user_id' => $otherUser->id]);

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $otherLibrary->id);

        $response->assertStatus(404)
            ->assertJson(['error' => 'Library not found']);
    }

    public function test_library_hash_rejects_non_numeric_non_uuid_library_id(): void
    {
        $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=not-a-valid-id');

        $response->assertStatus(400)
            ->assertJson(['error' => 'library_id must be numeric or UUID']);
    }

    // ────────────────────────────────────────────────────────────────
    // 9 tests removed 2026-04-10 — they exercised the legacy
    // `library_hash` VIEW/table fallback path which was deleted from
    // SyncV5Controller::getLibraryHash. The endpoint now reads only
    // from sync_merkle_roots via materializedMerkleService.
    // Removed cases:
    //   - test_library_hash_returns_fallback_payload_when_view_is_unavailable
    //   - test_library_hash_uses_fresh_cache_when_view_is_unavailable
    //   - test_library_hash_returns_hash_data_when_source_exists
    //   - test_library_hash_rebuilds_stale_cache_from_view_source
    //   - test_library_hash_accepts_calibre_library_uuid_query_param
    //   - test_library_hash_accepts_uuid_in_library_id_for_backward_compatibility
    //   - test_library_hash_uses_request_user_resolver_when_auth_id_is_unavailable
    //   - test_library_hash_prefers_split_columns_when_available
    //   - test_library_hash_derives_cover_and_file_hashes_when_source_has_legacy_columns_only
    // ────────────────────────────────────────────────────────────────
}
