<?php

namespace Tests\Server;

use App\Http\Controllers\Api\SyncV5Controller;
use App\Models\Library;
use App\Models\User;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;
use Laravel\Sanctum\Sanctum;
use Tests\TestCase;

class SyncV5LibraryHashEndpointTest extends TestCase
{
    use RefreshDatabase;

    private function assertSplitHashKeys(array $data): void
    {
        $this->assertArrayHasKey('library_metadata_hash', $data);
        $this->assertArrayHasKey('library_covers_hash', $data);
        $this->assertArrayHasKey('library_files_hash', $data);
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

    public function test_library_hash_returns_fallback_payload_when_view_is_unavailable(): void
    {
        [, $library] = $this->actingUserWithLibrary();

        DB::table('library_hash_cache')->where('library_id', $library->id)->delete();
        DB::statement('DROP VIEW IF EXISTS library_hash');
        DB::statement('DROP TABLE IF EXISTS library_hash');

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);

        $response->assertStatus(200)
            ->assertJson([
                'library_hash' => null,
                'library_metadata_hash' => null,
                'library_covers_hash' => null,
                'library_files_hash' => null,
                'total_books' => 0,
                'last_modified' => null,
                'error' => 'Fast path not available',
            ]);
    }

    public function test_library_hash_uses_fresh_cache_when_view_is_unavailable(): void
    {
        [$user, $library] = $this->actingUserWithLibrary();

        DB::table('library_hash_cache')->updateOrInsert(
            [
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
            [
                'library_hash' => str_repeat('f', 64),
                'total_books' => 23,
                'last_modified' => '2026-03-02 15:00:00',
                'computed_at' => now(),
                'is_stale' => 0,
                'created_at' => now(),
                'updated_at' => now(),
            ]
        );

        DB::statement('DROP VIEW IF EXISTS library_hash');
        DB::statement('DROP TABLE IF EXISTS library_hash');

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);

        $response->assertStatus(200)
            ->assertJson([
                'library_hash' => str_repeat('f', 64),
                'library_metadata_hash' => str_repeat('f', 64),
                'library_covers_hash' => null,
                'library_files_hash' => null,
                'total_books' => 23,
                'last_modified' => '2026-03-02 15:00:00',
            ]);
    }

    public function test_library_hash_returns_hash_data_when_source_exists(): void
    {
        [$user, $library] = $this->actingUserWithLibrary();

        DB::statement('DROP VIEW IF EXISTS library_hash');
        DB::statement('DROP TABLE IF EXISTS library_hash');
        DB::statement("
            CREATE TABLE library_hash (
                user_id INTEGER,
                library_id INTEGER,
                library_hash TEXT,
                total_books INTEGER,
                last_modified TEXT
            )
        ");

        DB::table('library_hash')->insert([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'library_hash' => str_repeat('a', 64),
            'total_books' => 42,
            'last_modified' => '2026-03-02T10:00:00Z',
        ]);
        DB::table('library_hash')->insert([
            'user_id' => $user->id + 1000,
            'library_id' => $library->id + 1000,
            'library_hash' => str_repeat('b', 64),
            'total_books' => 99,
            'last_modified' => '2026-03-02T11:00:00Z',
        ]);

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);

        $response->assertStatus(200)
            ->assertJson([
                'library_hash' => str_repeat('a', 64),
                'library_metadata_hash' => str_repeat('a', 64),
                'library_covers_hash' => null,
                'library_files_hash' => null,
                'total_books' => 42,
                'last_modified' => '2026-03-02T10:00:00Z',
            ]);

        $cacheRow = DB::table('library_hash_cache')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->first();
        $this->assertNotNull($cacheRow);
        $this->assertSame(0, (int) $cacheRow->is_stale);
        $this->assertSame(str_repeat('a', 64), $cacheRow->library_hash);
    }

    public function test_library_hash_rebuilds_stale_cache_from_view_source(): void
    {
        [$user, $library] = $this->actingUserWithLibrary();

        DB::table('library_hash_cache')->updateOrInsert(
            [
                'user_id' => $user->id,
                'library_id' => $library->id,
            ],
            [
                'library_hash' => str_repeat('1', 64),
                'total_books' => 1,
                'last_modified' => '2026-03-02 11:00:00',
                'computed_at' => now()->subDay(),
                'is_stale' => 1,
                'created_at' => now()->subDay(),
                'updated_at' => now()->subDay(),
            ]
        );

        DB::statement('DROP VIEW IF EXISTS library_hash');
        DB::statement('DROP TABLE IF EXISTS library_hash');
        DB::statement("
            CREATE TABLE library_hash (
                user_id INTEGER,
                library_id INTEGER,
                library_hash TEXT,
                total_books INTEGER,
                last_modified TEXT
            )
        ");
        DB::table('library_hash')->insert([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'library_hash' => str_repeat('9', 64),
            'total_books' => 321,
            'last_modified' => '2026-03-02T16:00:00Z',
        ]);

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);

        $response->assertStatus(200)
            ->assertJson([
                'library_hash' => str_repeat('9', 64),
                'library_metadata_hash' => str_repeat('9', 64),
                'library_covers_hash' => null,
                'library_files_hash' => null,
                'total_books' => 321,
                'last_modified' => '2026-03-02T16:00:00Z',
            ]);

        $cacheRow = DB::table('library_hash_cache')
            ->where('user_id', $user->id)
            ->where('library_id', $library->id)
            ->first();
        $this->assertNotNull($cacheRow);
        $this->assertSame(0, (int) $cacheRow->is_stale);
        $this->assertSame(str_repeat('9', 64), $cacheRow->library_hash);
        $this->assertSame(321, (int) $cacheRow->total_books);
    }

    public function test_library_hash_accepts_calibre_library_uuid_query_param(): void
    {
        [$user, $library] = $this->actingUserWithLibrary();

        DB::statement('DROP VIEW IF EXISTS library_hash');
        DB::statement('DROP TABLE IF EXISTS library_hash');
        DB::statement("
            CREATE TABLE library_hash (
                user_id INTEGER,
                library_id INTEGER,
                library_hash TEXT,
                total_books INTEGER,
                last_modified TEXT
            )
        ");
        DB::table('library_hash')->insert([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'library_hash' => str_repeat('d', 64),
            'total_books' => 77,
            'last_modified' => '2026-03-02T13:00:00Z',
        ]);

        $response = $this->getJson('/api/sync/v5/library-hash?calibre_library_uuid=' . $library->calibre_library_id);

        $response->assertStatus(200)
            ->assertJson([
                'library_hash' => str_repeat('d', 64),
                'library_metadata_hash' => str_repeat('d', 64),
                'library_covers_hash' => null,
                'library_files_hash' => null,
                'total_books' => 77,
                'last_modified' => '2026-03-02T13:00:00Z',
            ]);
    }

    public function test_library_hash_accepts_uuid_in_library_id_for_backward_compatibility(): void
    {
        [$user, $library] = $this->actingUserWithLibrary();

        DB::statement('DROP VIEW IF EXISTS library_hash');
        DB::statement('DROP TABLE IF EXISTS library_hash');
        DB::statement("
            CREATE TABLE library_hash (
                user_id INTEGER,
                library_id INTEGER,
                library_hash TEXT,
                total_books INTEGER,
                last_modified TEXT
            )
        ");
        DB::table('library_hash')->insert([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'library_hash' => str_repeat('e', 64),
            'total_books' => 12,
            'last_modified' => '2026-03-02T14:00:00Z',
        ]);

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->calibre_library_id);

        $response->assertStatus(200)
            ->assertJson([
                'library_hash' => str_repeat('e', 64),
                'library_metadata_hash' => str_repeat('e', 64),
                'library_covers_hash' => null,
                'library_files_hash' => null,
                'total_books' => 12,
                'last_modified' => '2026-03-02T14:00:00Z',
            ]);
    }

    public function test_library_hash_rejects_non_numeric_non_uuid_library_id(): void
    {
        $this->actingUserWithLibrary();

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=not-a-valid-id');

        $response->assertStatus(400)
            ->assertJson(['error' => 'library_id must be numeric or UUID']);
    }

    public function test_library_hash_uses_request_user_resolver_when_auth_id_is_unavailable(): void
    {
        [$user, $library] = $this->actingUserWithLibrary();

        DB::statement('DROP VIEW IF EXISTS library_hash');
        DB::statement('DROP TABLE IF EXISTS library_hash');
        DB::statement("
            CREATE TABLE library_hash (
                user_id INTEGER,
                library_id INTEGER,
                library_hash TEXT,
                total_books INTEGER,
                last_modified TEXT
            )
        ");
        DB::table('library_hash')->insert([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'library_hash' => str_repeat('c', 64),
            'total_books' => 5,
            'last_modified' => '2026-03-02T12:00:00Z',
        ]);

        $request = Request::create('/api/sync/v5/library-hash', 'GET', [
            'library_id' => $library->id,
        ]);
        $request->setUserResolver(function () use ($user) {
            return $user;
        });

        /** @var SyncV5Controller $controller */
        $controller = app(SyncV5Controller::class);
        $response = $controller->getLibraryHash($request);

        $this->assertSame(200, $response->getStatusCode());
        $data = $response->getData(true);
        $this->assertSplitHashKeys($data);
        $this->assertSame(str_repeat('c', 64), $data['library_hash'] ?? null);
        $this->assertSame(str_repeat('c', 64), $data['library_metadata_hash'] ?? null);
        $this->assertSame(5, $data['total_books'] ?? null);
        $this->assertSame('2026-03-02T12:00:00Z', $data['last_modified'] ?? null);
    }

    public function test_library_hash_prefers_split_columns_when_available(): void
    {
        [$user, $library] = $this->actingUserWithLibrary();

        DB::statement('DROP VIEW IF EXISTS library_hash');
        DB::statement('DROP TABLE IF EXISTS library_hash');
        DB::statement("
            CREATE TABLE library_hash (
                user_id INTEGER,
                library_id INTEGER,
                library_hash TEXT,
                library_metadata_hash TEXT,
                library_covers_hash TEXT,
                library_files_hash TEXT,
                total_books INTEGER,
                last_modified TEXT
            )
        ");
        DB::table('library_hash')->insert([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'library_hash' => str_repeat('a', 64),
            'library_metadata_hash' => str_repeat('b', 64),
            'library_covers_hash' => str_repeat('c', 64),
            'library_files_hash' => str_repeat('d', 64),
            'total_books' => 4,
            'last_modified' => '2026-03-03T11:00:00Z',
        ]);

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);
        $response->assertStatus(200);
        $response->assertJson([
            'library_hash' => str_repeat('a', 64),
            'library_metadata_hash' => str_repeat('b', 64),
            'library_covers_hash' => str_repeat('c', 64),
            'library_files_hash' => str_repeat('d', 64),
            'total_books' => 4,
            'last_modified' => '2026-03-03T11:00:00Z',
        ]);
    }

    public function test_library_hash_derives_cover_and_file_hashes_when_source_has_legacy_columns_only(): void
    {
        [$user, $library] = $this->actingUserWithLibrary();

        DB::table('books')->insert([
            'uuid' => 'aaaaaaaa-1111-2222-3333-444444444444',
            'id' => 101,
            'user_id' => $user->id,
            'library_id' => $library->id,
            'title' => 'Derive Hash Book',
            'path' => 'Derive Hash Book',
            'cover_original_hash' => 'sha256:' . str_repeat('c', 64),
            'created_at' => now(),
            'updated_at' => now(),
            'last_modified' => now(),
        ]);
        DB::table('books_files')->insert([
            'uuid' => 'bbbbbbbb-1111-2222-3333-444444444444',
            'book' => 'aaaaaaaa-1111-2222-3333-444444444444',
            'format' => 'EPUB',
            'name' => 'derive.epub',
            'user_id' => $user->id,
            'library_id' => $library->id,
            'file_hash' => str_repeat('d', 64),
            'uncompressed_size' => 123,
            'is_uploaded' => true,
            'file_missing' => false,
            'needs_file_upload' => false,
            'storage_key' => 'ebooks/derive.epub',
            'storage_provider' => 'r2',
            'file_path' => 'derive.epub',
            'created_at' => now(),
            'updated_at' => now(),
        ]);

        DB::statement('DROP VIEW IF EXISTS library_hash');
        DB::statement('DROP TABLE IF EXISTS library_hash');
        DB::statement("
            CREATE TABLE library_hash (
                user_id INTEGER,
                library_id INTEGER,
                library_hash TEXT,
                total_books INTEGER,
                last_modified TEXT
            )
        ");
        DB::table('library_hash')->insert([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'library_hash' => str_repeat('a', 64),
            'total_books' => 1,
            'last_modified' => '2026-03-03T11:30:00Z',
        ]);

        $response = $this->getJson('/api/sync/v5/library-hash?library_id=' . $library->id);
        $response->assertStatus(200);
        $data = $response->json();
        $this->assertSame(hash('sha256', str_repeat('c', 64)), $data['library_covers_hash'] ?? null);
        $this->assertSame(hash('sha256', str_repeat('d', 64)), $data['library_files_hash'] ?? null);
        $this->assertSame(str_repeat('a', 64), $data['library_metadata_hash'] ?? null);
    }
}
