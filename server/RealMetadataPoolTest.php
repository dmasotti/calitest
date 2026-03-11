<?php

namespace Tests\Server;

use App\Services\Sync\Benchmark\RealMetadataPool;
use Tests\TestCase;

class RealMetadataPoolTest extends TestCase
{
    public function test_loads_real_titles_and_authors_from_large_calibre_fixture(): void
    {
        $pool = app(RealMetadataPool::class)->load(
            base_path('../tests/plugin/fixtures/CalibreLargeLocal/metadata.db'),
            50
        );

        $this->assertGreaterThanOrEqual(10, count($pool));
        foreach (array_slice($pool, 0, 10) as $entry) {
            $this->assertIsInt($entry['source_book_id']);
            $this->assertIsString($entry['title']);
            $this->assertNotSame('', trim($entry['title']));
            $this->assertIsArray($entry['authors']);
            $this->assertNotSame([], $entry['authors']);
        }
    }
}
