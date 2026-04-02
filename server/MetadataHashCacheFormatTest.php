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
        $this->markTestSkipped('metadata_hash_cache column deprecated — VIEW is only source of truth');
    }
}
