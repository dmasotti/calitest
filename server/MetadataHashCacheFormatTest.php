<?php

namespace Tests\Server;

use App\Models\Library;
use App\Models\User;
use App\Models\UserBook;
use Carbon\Carbon;
use Illuminate\Foundation\Testing\RefreshDatabase;
use Tests\TestCase;

class MetadataHashCacheFormatTest extends TestCase
{
    use RefreshDatabase;

    public function test_user_book_metadata_hash_cache_uses_v2_versioned_format(): void
    {
        $user = User::factory()->create();
        $library = Library::factory()->create(['user_id' => $user->id]);

        $book = UserBook::factory()->create([
            'user_id' => $user->id,
            'library_id' => $library->id,
            'uuid' => '99999999-9999-9999-9999-999999999999',
            'title' => 'Versioned Metadata Hash Cache',
            'path' => 'Versioned Metadata Hash Cache',
            'last_modified' => Carbon::create(2026, 3, 11, 12, 34, 56, 'UTC'),
        ]);

        $hash = $book->getMetadataHash();

        $book->refresh();
        $this->assertNotNull($hash);
        $this->assertMatchesRegularExpression('/^[0-9a-f]{64}$/', (string) $hash);
        $this->assertMatchesRegularExpression('/^v2:[0-9a-f]{64}:\d+$/', (string) $book->metadata_hash_cache);
    }
}
