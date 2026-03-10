<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Schema;
use Tests\TestCase;

class SyncMappingsSchemaTest extends TestCase
{
    use RefreshDatabase;

    public function test_sync_mappings_table_exists_in_runtime_schema(): void
    {
        $this->assertTrue(
            Schema::hasTable('sync_mappings'),
            'sync_mappings must exist in runtime schema because sync metadata persistence depends on it'
        );
    }
}
