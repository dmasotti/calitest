<?php

namespace Tests\Server;

use Illuminate\Foundation\Testing\RefreshDatabase;
use Illuminate\Support\Facades\Schema;
use Tests\TestCase;

class MaterializedMerkleTablesTodoTest extends TestCase
{
    use RefreshDatabase;

    public function test_materialized_merkle_tables_exist_for_all_dimensions(): void
    {
        $this->assertTrue(Schema::hasTable('sync_merkle_leaves'));
        $this->assertTrue(Schema::hasTable('sync_merkle_branches'));
        $this->assertTrue(Schema::hasTable('sync_merkle_roots'));
    }
}
